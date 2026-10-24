"""Indoors: floors, floor plans placed on the map, and records placed inside (models/indoor.py).

* **A plan's picture.** An image is kept as it is (anything but PNG or JPEG becomes PNG); an SVG as it is; a
  PDF's first page is drawn as a PNG (pypdfium2); a DXF or DWG drawing becomes an SVG (services/drawings). The
  file given is kept beside it.
* **Placing a plan on the map.** Control points pair a pixel of the plan with the longitude and latitude it is
  at. Two points give a similarity (scale, rotation, position: the plan keeps its shape); three or more an affine
  transform fitted by least squares, with each point's residual in metres — a point far from the fit is a point
  clicked in the wrong place. The fit is made in metres around the points (a local east/north plane), so the
  residuals are distances on the ground.
* **Placing a record inside.** In a place (a room, a hall), on a level, at a point of a plan — what is known.
  The approved placement supersedes the one before (kept). A point on a plan placed on the map gives the
  record its position too (source "plan", as accurate as the plan's fit).
* **What it says.** A place lists what is placed in it; a record lists the place it is in, and the places that
  place is in (a room in a hall in a building).
"""
from __future__ import annotations

import io
import math
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.indoor import FloorPlan, IndoorPlacement, PlaceLevel

PLANS_DIR = os.path.join(os.environ.get("ATTACHMENTS_DIR", "/data/attachments"), "plans")
MAX_PLAN_BYTES = 40 * 1024 * 1024
MAX_SIDE_PX = 12000
PDF_LONG_SIDE_PX = 3000
M_PER_DEG_LAT = 110_540.0
M_PER_DEG_LON_EQUATOR = 111_320.0
# A GPS fix less precise than this does not move a record placed indoors: it is noted, not sent to review.
INDOOR_GPS_M = 10.0
IMAGE_KINDS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/png",
               ".webp": "image/png", ".bmp": "image/png", ".tif": "image/png", ".tiff": "image/png"}


class IndoorError(ValueError):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- levels

def levels(db: Session, place_uid: str) -> list[PlaceLevel]:
    return list(db.scalars(select(PlaceLevel).where(PlaceLevel.place_uid == place_uid)
                           .order_by(PlaceLevel.ordinal, PlaceLevel.name)))


def _number(v, what: str, low: float = -10000, high: float = 10000) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise IndoorError(f"{what} is a number") from None
    if not math.isfinite(v) or not low <= v <= high:
        raise IndoorError(f"{what} {v} is not plausible")
    return v


def save_level(db: Session, place: Asset, *, name: str, ordinal: int = 0, elevation_m=None, height_m=None,
               actor: Optional[str], level: Optional[PlaceLevel] = None) -> PlaceLevel:
    name = (name or "").strip()
    if not name:
        raise IndoorError("a floor has a name")
    if not -50 <= int(ordinal) <= 200:
        raise IndoorError("a floor's order is between -50 and 200")
    same = db.scalar(select(PlaceLevel).where(PlaceLevel.place_uid == place.uid, PlaceLevel.name == name))
    if same is not None and (level is None or same.uid != level.uid):
        raise IndoorError(f"{place.name} has a floor called {name!r} already")
    height = _number(height_m, "the floor's height", 0, 1000)
    if height is not None and height <= 0:
        raise IndoorError("a floor's height is above 0 m")
    if level is None:
        level = PlaceLevel(uid=str(uuid.uuid4()), workspace_id=place.workspace_id, place_uid=place.uid,
                           created_by=actor, created_at=now())
        db.add(level)
    level.name, level.ordinal = name[:120], int(ordinal)
    level.elevation_m, level.height_m = _number(elevation_m, "the floor's elevation"), height
    db.flush()
    return level


# --------------------------------------------------------------------------- a plan's picture

def _svg_size(svg: bytes) -> tuple[float, float]:
    head = svg[:4096].decode("utf-8", errors="ignore")
    m = re.search(r'viewBox\s*=\s*["\']\s*[-\d.eE]+[\s,]+[-\d.eE]+[\s,]+([\d.eE]+)[\s,]+([\d.eE]+)', head)
    if m:
        return float(m.group(1)), float(m.group(2))
    w = re.search(r'\swidth\s*=\s*["\']([\d.]+)', head)
    h = re.search(r'\sheight\s*=\s*["\']([\d.]+)', head)
    if w and h:
        return float(w.group(1)), float(h.group(1))
    raise IndoorError("the SVG says neither its size nor its viewBox")


def picture(filename: str, content: bytes) -> tuple[bytes, str, float, float, str]:
    """(picture, its media type, width, height, the kind of file given) of a plan's file."""
    if not content:
        raise IndoorError("the file is empty")
    if len(content) > MAX_PLAN_BYTES:
        raise IndoorError(f"a plan is at most {MAX_PLAN_BYTES // (1024 * 1024)} MB")
    ext = os.path.splitext((filename or "").lower())[1]
    if ext == ".svg":
        if b"<svg" not in content[:4096]:
            raise IndoorError("that is not an SVG")
        w, h = _svg_size(content)
        return content, "image/svg+xml", w, h, "svg"
    if ext == ".pdf":
        try:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(content)
            page = doc[0]
            pw, ph = page.get_size()
            scale = PDF_LONG_SIDE_PX / max(pw, ph)
            image = page.render(scale=scale).to_pil()
        except Exception as e:  # a damaged or encrypted PDF is a person's message, not a crash
            raise IndoorError(f"the PDF could not be drawn: {e}") from None
        out = io.BytesIO()
        image.save(out, "PNG", optimize=True)
        return out.getvalue(), "image/png", float(image.width), float(image.height), "pdf"
    if ext in (".dxf", ".dwg"):
        from app.services.drawings import dwg_to_dxf, render_sheets
        dxf, error = (dwg_to_dxf(content) if ext == ".dwg" else (content, None))
        if dxf is None:
            raise IndoorError(f"the drawing could not be converted: {error}")
        sheets, error = render_sheets(dxf)
        if not sheets:
            raise IndoorError(f"the drawing has no sheet to show: {error}")
        svg = sheets[0][1]
        w, h = _svg_size(svg)
        return svg, "image/svg+xml", w, h, "dxf"
    if ext in IMAGE_KINDS:
        from PIL import Image
        try:
            image = Image.open(io.BytesIO(content))
            image.load()
        except Exception:
            raise IndoorError("the picture could not be read") from None
        if max(image.size) > MAX_SIDE_PX:
            raise IndoorError(f"the picture is {image.width}×{image.height}: at most {MAX_SIDE_PX} pixels a side")
        if ext in (".png", ".jpg", ".jpeg"):
            return content, IMAGE_KINDS[ext], float(image.width), float(image.height), "image"
        out = io.BytesIO()
        image.convert("RGBA").save(out, "PNG", optimize=True)
        return out.getvalue(), "image/png", float(image.width), float(image.height), "image"
    raise IndoorError("a plan is an image (PNG, JPEG…), an SVG, a PDF or a DXF/DWG drawing")


def _store(name: str, content: bytes) -> str:
    os.makedirs(PLANS_DIR, exist_ok=True)
    path = os.path.join(PLANS_DIR, name)
    with open(path, "wb") as f:
        f.write(content)
    return path


def add_plan(db: Session, place: Asset, filename: str, content: bytes, *, name: Optional[str],
             level: Optional[PlaceLevel], actor: Optional[str]) -> FloorPlan:
    image, mime, w, h, kind = picture(filename, content)
    uid = str(uuid.uuid4())
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg"}[mime]
    plan = FloorPlan(uid=uid, workspace_id=place.workspace_id, place_uid=place.uid,
                     level_uid=level.uid if level else None,
                     name=(name or os.path.splitext(filename or "plan")[0] or "Plan").strip()[:200],
                     storage_path=_store(uid + ext, image), mime_type=mime, width_px=w, height_px=h,
                     source_filename=(filename or "")[:255], source_kind=kind,
                     source_path=_store(uid + "-source" + os.path.splitext(filename or "")[1].lower(), content)
                     if kind in ("pdf", "dxf") else None,
                     created_by=actor, created_at=now(), updated_at=now())
    db.add(plan)
    db.flush()
    return plan


# --------------------------------------------------------------------------- placing a plan on the map

def _solve3(m: list[list[float]], v: list[float]) -> list[float]:
    """A 3×3 linear system, by Cramer's rule."""
    def det(a):
        return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
                + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    d = det(m)
    if abs(d) < 1e-9:
        raise IndoorError("the control points are in a line: choose points spread over the plan")
    out = []
    for i in range(3):
        mi = [row[:] for row in m]
        for r in range(3):
            mi[r][i] = v[r]
        out.append(det(mi) / d)
    return out


def fit(points: list[dict], width: float, height: float) -> dict:
    """The transform of a plan's pixels to WGS 84 from control points ({x, y, longitude, latitude}), with each
    point's residual and their root mean square, in metres, and the plan's scale and rotation."""
    if len(points) < 2:
        raise IndoorError("place a plan with two control points at least (three or more give its residuals)")
    if len(points) > 50:
        raise IndoorError("at most 50 control points")
    pts = []
    for i, p in enumerate(points, start=1):
        try:
            x, y, lon, lat = float(p["x"]), float(p["y"]), float(p["longitude"]), float(p["latitude"])
        except (KeyError, TypeError, ValueError):
            raise IndoorError(f"control point {i}: x, y, longitude and latitude are numbers") from None
        if not (0 <= x <= width and 0 <= y <= height):
            raise IndoorError(f"control point {i} is outside the plan ({width:g}×{height:g})")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            raise IndoorError(f"control point {i}: {lon}, {lat} is not a WGS 84 longitude and latitude")
        pts.append((x, y, lon, lat))
    if len({(x, y) for x, y, _, _ in pts}) < len(pts) or len({(lo, la) for _, _, lo, la in pts}) < len(pts):
        raise IndoorError("two control points are at the same place")
    lon0 = sum(p[2] for p in pts) / len(pts)
    lat0 = sum(p[3] for p in pts) / len(pts)
    kx = math.cos(math.radians(lat0)) * M_PER_DEG_LON_EQUATOR
    ky = M_PER_DEG_LAT
    ground = [(x, y, (lon - lon0) * kx, (lat - lat0) * ky) for x, y, lon, lat in pts]
    if len(ground) == 2:
        (x1, y1, e1, n1), (x2, y2, e2, n2) = ground
        # Pixels' y grows downwards, north upwards: z = x − i·y keeps the plan from being mirrored.
        z1, z2, w1, w2 = complex(x1, -y1), complex(x2, -y2), complex(e1, n1), complex(e2, n2)
        a = (w2 - w1) / (z2 - z1)
        b = w1 - a * z1
        ce = (a.real, a.imag, b.real)                 # E = ar·x + ai·y + Br
        cn = (a.imag, -a.real, b.imag)                # N = ai·x − ar·y + Bi
    else:
        sxx = sum(x * x for x, _, _, _ in ground)
        sxy = sum(x * y for x, y, _, _ in ground)
        syy = sum(y * y for _, y, _, _ in ground)
        sx, sy, n = sum(g[0] for g in ground), sum(g[1] for g in ground), float(len(ground))
        normal = [[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, n]]
        ce = tuple(_solve3(normal, [sum(x * e for x, _, e, _ in ground), sum(y * e for _, y, e, _ in ground),
                                    sum(e for _, _, e, _ in ground)]))
        cn = tuple(_solve3(normal, [sum(x * nn for x, _, _, nn in ground), sum(y * nn for _, y, _, nn in ground),
                                    sum(nn for _, _, _, nn in ground)]))
    det = ce[0] * cn[1] - ce[1] * cn[0]
    if abs(det) < 1e-12:
        raise IndoorError("the control points do not place the plan: choose points spread over it")
    residuals = []
    for x, y, e, nn in ground:
        de = ce[0] * x + ce[1] * y + ce[2] - e
        dn = cn[0] * x + cn[1] * y + cn[2] - nn
        residuals.append(round(math.hypot(de, dn), 3))
    rms = math.sqrt(sum(r * r for r in residuals) / len(residuals))
    transform = {"a": ce[0] / kx, "b": ce[1] / kx, "c": lon0 + ce[2] / kx,
                 "d": cn[0] / ky, "e": cn[1] / ky, "f": lat0 + cn[2] / ky}
    return {"transform": transform, "residuals_m": residuals, "residual_m": round(rms, 3),
            "metres_per_px": round(math.sqrt(abs(det)), 6),
            # The plan's x axis, in degrees anticlockwise from east.
            "rotation_deg": round(math.degrees(math.atan2(cn[0], ce[0])) % 360, 2)}


def to_lonlat(t: dict, x: float, y: float) -> tuple[float, float]:
    return t["a"] * x + t["b"] * y + t["c"], t["d"] * x + t["e"] * y + t["f"]


def to_plan(t: dict, lon: float, lat: float) -> tuple[float, float]:
    det = t["a"] * t["e"] - t["b"] * t["d"]
    dl, dt = lon - t["c"], lat - t["f"]
    return (t["e"] * dl - t["b"] * dt) / det, (t["a"] * dt - t["d"] * dl) / det


def corners(plan: FloorPlan) -> Optional[list[list[float]]]:
    """[longitude, latitude] of the plan's top-left, top-right, bottom-right and bottom-left corners."""
    if not plan.transform:
        return None
    w, h = plan.width_px, plan.height_px
    return [list(to_lonlat(plan.transform, x, y)) for x, y in ((0, 0), (w, 0), (w, h), (0, h))]


def georeference(db: Session, plan: FloorPlan, points: list[dict]) -> dict:
    result = fit(points, plan.width_px, plan.height_px)
    plan.control_points = [{k: float(p[k]) for k in ("x", "y", "longitude", "latitude")} for p in points]
    plan.transform, plan.residual_m, plan.updated_at = result["transform"], result["residual_m"], now()
    db.flush()
    return result


def unplace(db: Session, plan: FloorPlan) -> None:
    plan.control_points = plan.transform = plan.residual_m = None
    plan.updated_at = now()
    db.flush()


# --------------------------------------------------------------------------- records placed inside

def current(db: Session, asset_uid: str) -> Optional[IndoorPlacement]:
    return db.scalar(select(IndoorPlacement).where(IndoorPlacement.asset_uid == asset_uid,
                                                   IndoorPlacement.state == "confirmed"))


def history(db: Session, asset_uid: str) -> list[IndoorPlacement]:
    return list(db.scalars(select(IndoorPlacement).where(IndoorPlacement.asset_uid == asset_uid)
                           .order_by(IndoorPlacement.valid_from.desc())))


def place(db: Session, asset: Asset, *, place_uid: Optional[str] = None, level_uid: Optional[str] = None,
          plan_uid: Optional[str] = None, x=None, y=None, actor: Optional[str], source: str = "manual",
          note: Optional[str] = None) -> IndoorPlacement:
    """Place a record inside: in a place, on a level, at a point of a plan (what is known). A point on a plan
    placed on the map gives the record its position too."""
    plan = db.get(FloorPlan, plan_uid) if plan_uid else None
    if plan_uid and (plan is None or plan.workspace_id != asset.workspace_id):
        raise IndoorError("no such plan here")
    px, py = _number(x, "x", 0, 1e7), _number(y, "y", 0, 1e7)
    if (px is None) != (py is None):
        raise IndoorError("a point on a plan has both x and y")
    if px is not None:
        if plan is None:
            raise IndoorError("a point needs its plan")
        if not (0 <= px <= plan.width_px and 0 <= py <= plan.height_px):
            raise IndoorError("the point is outside the plan")
    place_uid = place_uid or (plan.place_uid if plan else None)
    if not place_uid and px is None:
        raise IndoorError("say where it is: a place (a room, a hall) or a point on a plan")
    if place_uid == asset.uid:
        raise IndoorError("a record is not inside itself")
    place_rec = db.get(Asset, place_uid) if place_uid else None
    if place_uid and (place_rec is None or place_rec.deleted_at is not None or place_rec.workspace_id != asset.workspace_id):
        raise IndoorError("no such place here")
    level_uid = level_uid or (plan.level_uid if plan else None)
    level = db.get(PlaceLevel, level_uid) if level_uid else None
    if level_uid and (level is None or level.workspace_id != asset.workspace_id):
        raise IndoorError("no such floor here")
    if place_rec is not None and _inside_chain(db, place_rec.uid, asset.uid):
        raise IndoorError(f"{place_rec.name} is inside {asset.name}: a record cannot be inside what is inside it")
    at = now()
    previous = current(db, asset.uid)
    if previous is not None:
        previous.state, previous.valid_until = "superseded", at
        db.flush()
    placed = IndoorPlacement(uid=str(uuid.uuid4()), workspace_id=asset.workspace_id, asset_uid=asset.uid,
                             place_uid=place_uid, level_uid=level_uid, plan_uid=plan.uid if plan else None,
                             plan_x=px, plan_y=py, source=source, note=note, state="confirmed", valid_from=at,
                             confirmed_by=actor, created_at=at)
    db.add(placed)
    db.flush()
    words = [f"in {place_rec.name}" if place_rec else None, f"on {level.name}" if level else None,
             f"at {px:.0f}, {py:.0f} of the plan {plan.name}" if px is not None else None]
    _history(db, asset, "Placed indoors: " + ", ".join(w for w in words if w), actor, at)
    if px is not None and plan.transform:
        from app.services import spatial
        lon, lat = to_lonlat(plan.transform, px, py)
        try:
            spatial.set_location(db, asset, spatial.point(lat, lon), actor=actor, source="plan",
                                 accuracy_m=max(plan.residual_m or 0.0, 0.5), note=f"from the plan {plan.name}",
                                 provenance={"plan": plan.uid, "x": px, "y": py})
        except spatial.SpatialError:
            pass                                       # a type not placed on the map: indoors only
    return placed


def remove(db: Session, asset: Asset, actor: Optional[str]) -> bool:
    previous = current(db, asset.uid)
    if previous is None:
        return False
    at = now()
    previous.state, previous.valid_until = "removed", at
    _history(db, asset, "No longer placed indoors", actor, at)
    db.flush()
    return True


def _history(db: Session, asset: Asset, details: str, actor: Optional[str], at) -> None:
    from app.models.asset_subresources import AssetHistory
    db.add(AssetHistory(uid=str(uuid.uuid4()), asset_uid=asset.uid, type="location", author=actor or "argus",
                        details=details, timestamp=at))
    asset.updated_at = at


def _inside_chain(db: Session, start_uid: str, target_uid: str, depth: int = 12) -> bool:
    """Whether `start_uid` is (directly or through other places) inside `target_uid`."""
    uid, seen = start_uid, set()
    for _ in range(depth):
        p = current(db, uid)
        if p is None or not p.place_uid or p.place_uid in seen:
            return False
        if p.place_uid == target_uid:
            return True
        seen.add(p.place_uid)
        uid = p.place_uid
    return False


def containers(db: Session, asset_uid: str, depth: int = 8) -> list[Asset]:
    """The places a record is in, nearest first: its room, the hall the room is in, the building…"""
    out, uid, seen = [], asset_uid, {asset_uid}
    for _ in range(depth):
        p = current(db, uid)
        if p is None or not p.place_uid or p.place_uid in seen:
            break
        rec = db.get(Asset, p.place_uid)
        if rec is None or rec.deleted_at is not None:
            break
        out.append(rec)
        seen.add(rec.uid)
        uid = rec.uid
    return out


def placed_in(db: Session, place_uid: str, limit: int = 1000) -> list[tuple[Asset, IndoorPlacement]]:
    return list(db.execute(select(Asset, IndoorPlacement).join(IndoorPlacement, IndoorPlacement.asset_uid == Asset.uid)
                           .where(IndoorPlacement.place_uid == place_uid, IndoorPlacement.state == "confirmed",
                                  Asset.deleted_at.is_(None)).limit(limit)))


def on_plan(db: Session, plan_uid: str, limit: int = 2000) -> list[tuple[Asset, IndoorPlacement]]:
    return list(db.execute(select(Asset, IndoorPlacement).join(IndoorPlacement, IndoorPlacement.asset_uid == Asset.uid)
                           .where(IndoorPlacement.plan_uid == plan_uid, IndoorPlacement.state == "confirmed",
                                  IndoorPlacement.plan_x.is_not(None), Asset.deleted_at.is_(None)).limit(limit)))


def plan_out(db: Session, plan: FloorPlan) -> dict:
    level = db.get(PlaceLevel, plan.level_uid) if plan.level_uid else None
    place_rec = db.get(Asset, plan.place_uid)
    return {"uid": plan.uid, "name": plan.name, "place": {"uid": plan.place_uid, "name": place_rec.name if place_rec else None},
            "level": level_out(level) if level else None, "width_px": plan.width_px, "height_px": plan.height_px,
            "mime_type": plan.mime_type, "source_kind": plan.source_kind, "source_filename": plan.source_filename,
            "control_points": plan.control_points or [], "transform": plan.transform, "residual_m": plan.residual_m,
            "corners": corners(plan), "created_at": plan.created_at, "updated_at": plan.updated_at}


def level_out(level: PlaceLevel) -> dict:
    return {"uid": level.uid, "place_uid": level.place_uid, "name": level.name, "ordinal": level.ordinal,
            "elevation_m": level.elevation_m, "height_m": level.height_m}


def placement_out(db: Session, p: IndoorPlacement) -> dict:
    place_rec = db.get(Asset, p.place_uid) if p.place_uid else None
    level = db.get(PlaceLevel, p.level_uid) if p.level_uid else None
    plan = db.get(FloorPlan, p.plan_uid) if p.plan_uid else None
    return {"uid": p.uid, "place": {"uid": place_rec.uid, "key": place_rec.key, "name": place_rec.name,
                                    "type": place_rec.type} if place_rec else None,
            "level": level_out(level) if level else None,
            "plan": {"uid": plan.uid, "name": plan.name, "width_px": plan.width_px, "height_px": plan.height_px}
            if plan else None,
            "x": p.plan_x, "y": p.plan_y, "source": p.source, "note": p.note, "state": p.state,
            "valid_from": p.valid_from, "valid_until": p.valid_until, "confirmed_by": p.confirmed_by}
