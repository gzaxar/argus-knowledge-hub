"""Floor plans drawn by ARGUS as a room schedule (docs/plan-drawing.md): the building's fabric, its column grid with axis
bubbles, each room in the colour of what it is for, with its name in a label that fits inside it, its number and area,
doors, shielding around a bunker, north and a scale bar (1 m = 10 px).

Two ways in:
- "Draw a plan": a layout in metres (the building's width and depth, its rooms) becomes a drawing — `from_layout`.
  A drawn plan opens again as its layout (`layout_of`) and is redrawn from the changed one; the building keeps its
  origin, so every point already on the plan stays where it was.
- The demos: `redraw(svg)` reads a first-generation demo drawing (a building rectangle, then for each room a
  rectangle with its name and number) and draws it again at the same plan pixels.

The model is kept in the drawing's <desc>, so drawing it again changes nothing.
"""
from __future__ import annotations

import html
import json
import re

MARK = "argus-demo-plan/2"
FONT = "Helvetica, Arial, sans-serif"
PX_PER_M = 10                                             # the demos' scale, written on every drawing

# What a room is for, by its name, and its colour (fill, edge).
USES = [
    (("bunker", "tunnel", "vault", "linac"), ("#f6dede", "#b45f5f")),
    (("klystron", "rf", "modulator"), ("#f4ecc8", "#a08a3c")),
    (("laser",), ("#e6e0f5", "#7c6aa8")),
    (("control", "operations", "noc"), ("#d6eedf", "#4f8a63")),
    (("electrical", "power", "ups", "switchboard"), ("#f3e3a6", "#a1842a")),
    (("server", "data hall", "network", "mdf", "idf", "comms", "rack"), ("#d7e4f3", "#55779c")),
    (("experimental", "users", "undulator", "beamline", "target"), ("#dce3f6", "#5b6fa8")),
    (("plant", "utilities", "cooling", "pump", "chiller", "boiler", "mechanical"), ("#f3dcc8", "#a7764d")),
    (("corridor", "circulation", "lobby", "hall"), ("#e4e8ee", "#7b8794")),
    (("office", "reception", "meeting", "library", "reading", "study", "lab"), ("#dfeaf5", "#6683a3")),
    (("store", "storage", "spares", "workshop"), ("#e9e4dc", "#8b7f6c")),
]
DEFAULT = ("#e8edf3", "#6b7a8c")


class PlanDrawingError(ValueError):
    pass


def _use(name: str) -> tuple[str, str]:
    n = name.lower()
    for words, colours in USES:
        if any(re.search(rf"\b{re.escape(w)}", n) for w in words):
            return colours
    return DEFAULT


def _num(s: str) -> float:
    return float(s)


def _attrs(tag: str) -> dict[str, str]:
    return dict(re.findall(r'([\w-]+)="([^"]*)"', tag))


def read(svg: str) -> dict:
    """The drawing's model: size, building, rooms, beam lines, north, title."""
    kept = re.search(r"<desc>(.*?)</desc>", svg, re.S)
    if kept and MARK in svg:
        return json.loads(html.unescape(kept.group(1)))
    root = _attrs(re.search(r"<svg[^>]*>", svg).group(0))
    w, h = (_num(v) for v in root["viewBox"].split()[2:])
    model: dict = {"width": w, "height": h, "rooms": [], "lines": [], "north": None, "title": "", "note": ""}
    items = re.findall(r"(<rect[^>]*/>|<text[^>]*>[^<]*</text>|<polyline[^>]*/>|<g transform=\"translate\([^)]*\)\">)", svg)
    i = 0
    while i < len(items):
        it = items[i]
        if it.startswith("<rect"):
            a = _attrs(it)
            if a.get("stroke") == "#0f172a":
                model["building"] = [_num(a["x"]), _num(a["y"]), _num(a["width"]), _num(a["height"])]
            elif a.get("stroke") == "#334155":
                texts = []
                while i + 1 < len(items) and items[i + 1].startswith("<text") and len(texts) < 2:
                    i += 1
                    texts.append(html.unescape(re.sub(r"<[^>]*>", "", items[i])))
                model["rooms"].append({"box": [_num(a["x"]), _num(a["y"]), _num(a["width"]), _num(a["height"])],
                                       "name": texts[0] if texts else "", "number": texts[1] if len(texts) > 1 else ""})
        elif it.startswith("<polyline"):
            a = _attrs(it)
            pts = [[_num(v) for v in p.split(",")] for p in a["points"].split()]
            label = ""
            if i + 1 < len(items) and items[i + 1].startswith("<text") and _attrs(items[i + 1]).get("fill") == a["stroke"]:
                i += 1
                label = html.unescape(re.sub(r"<[^>]*>", "", items[i]))
            model["lines"].append({"points": pts, "colour": a["stroke"], "dashed": bool(a.get("stroke-dasharray")),
                                   "label": label})
        elif it.startswith("<g transform"):
            x, y = (_num(v) for v in re.search(r"translate\(([^)]*)\)", it).group(1).split(","))
            model["north"] = [x, y]
            i += 1                                               # its N
        elif it.startswith("<text"):
            t = html.unescape(re.sub(r"<[^>]*>", "", it))
            a = _attrs(it)
            if a.get("font-weight") == "bold" and not model["title"]:
                model["title"] = t
            elif not model["note"]:
                model["note"] = t
        i += 1
    model.setdefault("building", [2, 2, w - 4, h - 64])
    return model


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def _fit(name: str, width: float, height: float) -> tuple[float, list[str]]:
    """The largest size (5.5–10) at which the name fits the room in at most three lines."""
    words = name.upper().split()
    for fs in (10, 9, 8, 7, 6.5, 6, 5.5):
        per = fs * 0.64                                         # a bold capital's width, roughly
        room = max(width - 12, 10)
        lines: list[str] = []
        for wd in words:
            if lines and len(lines[-1] + " " + wd) * per <= room:
                lines[-1] += " " + wd
            else:
                lines.append(wd)
        if len(lines) <= 3 and all(len(ln) * per <= room for ln in lines) and len(lines) * fs * 1.2 + 8 <= height * 0.7:
            return fs, lines
    return 5.5, [name.upper()]


def _crosses(points: list, x: float, y: float, w: float, h: float) -> bool:
    """Whether a polyline passes through a box (sampled along each segment)."""
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        for k in range(21):
            px, py = x0 + (x1 - x0) * k / 20, y0 + (y1 - y0) * k / 20
            if x <= px <= x + w and y <= py <= y + h:
                return True
    return False


MARKER = 9.0                                               # a point drawn over the plan, and its ticket badge, in px


def _covered(box: tuple, avoid: dict, lines: list, below: float = 0) -> float:
    """How much of what is drawn over the plan a label in `box` (and its number and area, `below` it) would sit
    under: points on the name, points at its edge or on the number, lines through it."""
    x, y, w, h = box

    def near(px, py, pad, extra=0.0):
        return x - pad <= px <= x + w + pad and y - pad <= py <= y + h + extra + pad
    pts = avoid.get("points", ())
    on = sum(1 for px, py in pts if near(px, py, 4))                 # a point on the name hides a word
    by = sum(1 for px, py in pts if near(px, py, MARKER, below)) - on  # at its edge, or on the number: a detail
    h += below
    crossed = sum(1 for p in avoid.get("lines", ()) if _crosses(p, x - 3, y - 3, w + 6, h + 6))
    beam = sum(1 for ln in lines if _crosses(ln["points"], x, y - 3, w, h + 6))
    return 10 * on + by + 15 * crossed + 40 * beam


def _label_spot(room: tuple, pw: float, ph: float, below: float, avoid: dict, lines: list) -> tuple[float, float]:
    """Where a room's label goes: high in the room and centred, unless what is drawn over the plan or the beam
    would cover it there; then the free spot nearest to that, among a few across the room."""
    x, y, w, h = room
    full = ph + below                                         # the label and the number and area under it
    home = (x + (w - pw) / 2, y + max(5.0, min(h * 0.18, h - full - 2)))
    rows = [home[1]] + [y + 3 + (h - full - 6) * k / 10 for k in range(11)]
    cols = [home[0]] + [x + 3 + (w - pw - 6) * k / 8 for k in range(9)]
    spots = [(cx, cy) for cy in rows for cx in cols if x + 2 <= cx and cx + pw <= x + w - 2
             and y + 2 <= cy and cy + full <= y + h - 1]
    if not spots:
        return home
    # The least covered spot; of those, the nearest to where a label is usually read.
    return min(spots, key=lambda s: (_covered((s[0], s[1], pw, ph), avoid, lines, below),
                                     (s[0] - home[0]) ** 2 + (s[1] - home[1]) ** 2))


def draw(m: dict, avoid: dict | None = None) -> str:
    """The drawing of model `m`. `avoid` holds what ARGUS draws over the plan — `points` and `lines` in the
    drawing's pixels — so the room labels are put where nothing covers them; it is not kept in the model."""
    avoid = avoid or {}
    W, H = m["width"], m["height"]
    bx, by, bw, bh = m["building"]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:g} {H:g}" width="{W:g}" height="{H:g}">',
           f"<desc>{_esc(json.dumps(m, separators=(',', ':')))}</desc>",
           f"<!-- {MARK}: synthetic demo plan, redrawn by backend/scripts/demo_plan_drawing.py -->",
           "<defs>"
           '<pattern id="hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
           '<rect width="5" height="5" fill="#d9d4cc"/><line x1="0" y1="0" x2="0" y2="5" stroke="#8f8578" stroke-width="1.4"/>'
           "</pattern>"
           '<pattern id="ground" width="8" height="8" patternUnits="userSpaceOnUse">'
           '<rect width="8" height="8" fill="#f3f5f8"/><circle cx="1" cy="1" r="0.5" fill="#dde3ea"/></pattern>'
           "</defs>",
           f'<rect x="0" y="0" width="{W:g}" height="{H:g}" fill="url(#ground)"/>']
    # The building: its fabric, a double outer wall.
    out.append(f'<rect x="{bx:g}" y="{by:g}" width="{bw:g}" height="{bh:g}" fill="#eceff3" stroke="#1f2937" stroke-width="4"/>')
    out.append(f'<rect x="{bx + 3.5:g}" y="{by + 3.5:g}" width="{bw - 7:g}" height="{bh - 7:g}" fill="none" '
               'stroke="#1f2937" stroke-width="0.8"/>')
    # The column grid every 5 m, with its axes: numbers along the top, letters up the left side.
    step = 5 * PX_PER_M
    grid = []
    xs = [bx + step * k for k in range(1, int(bw // step) + 1) if bx + step * k < bx + bw - 4]
    ys = [by + step * k for k in range(1, int(bh // step) + 1) if by + step * k < by + bh - 4]
    for x in xs:
        grid.append(f'<line x1="{x:g}" y1="{by + 4:g}" x2="{x:g}" y2="{by + bh - 4:g}"/>')
    for y in ys:
        grid.append(f'<line x1="{bx + 4:g}" y1="{y:g}" x2="{bx + bw - 4:g}" y2="{y:g}"/>')
    out.append('<g stroke="#c7cfd9" stroke-width="0.5" stroke-dasharray="3 3">' + "".join(grid) + "</g>")
    for x in xs:
        for y in ys:
            out.append(f'<rect x="{x - 1.6:g}" y="{y - 1.6:g}" width="3.2" height="3.2" fill="#9aa5b1"/>')
    bubbles = []
    ax = by - 10 if by >= 16 else by + 9                       # the axes outside the walls when there is room
    ay = bx - 10 if bx >= 16 else bx + 9
    for k, x in enumerate(xs, start=1):
        bubbles.append(f'<circle cx="{x:g}" cy="{ax:g}" r="5"/><text x="{x:g}" y="{ax + 2.3:g}">{k}</text>')
    for k, y in enumerate(reversed(ys)):
        bubbles.append(f'<circle cx="{ay:g}" cy="{y:g}" r="5"/><text x="{ay:g}" y="{y + 2.3:g}">{chr(65 + k)}</text>')
    out.append(f'<g fill="#fff" stroke="#94a3b8" stroke-width="0.6" font-family="{FONT}" font-size="6.5" '
               'text-anchor="middle">' + "".join(bubbles).replace("<text", '<text fill="#64748b" stroke="none"') + "</g>")
    cy = by + bh / 2
    # Shielding first, around the rooms that need it.
    for r in m["rooms"]:
        x, y, w, h = r["box"]
        if re.search(r"\b(bunker|tunnel|vault)", r["name"].lower()):
            out.append(f'<rect x="{x - 6:g}" y="{y - 6:g}" width="{w + 12:g}" height="{h + 12:g}" fill="url(#hatch)" '
                       'stroke="#6b6358" stroke-width="0.8"/>')
    for r in m["rooms"]:
        x, y, w, h = r["box"]
        fill, edge = _use(r["name"])
        out.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" fill="{fill}" stroke="#334155" stroke-width="2.2"/>')
        out.append(f'<rect x="{x + 2:g}" y="{y + 2:g}" width="{w - 4:g}" height="{h - 4:g}" fill="none" stroke="{edge}" '
                   'stroke-width="0.6" stroke-opacity="0.7"/>')
        # A door on the side facing the middle of the building, near a corner: a gap in the wall and its swing.
        if w >= 30 and h >= 24:
            d = min(10.0, w / 5)
            dx = x + 6
            if y + h / 2 < cy:                                    # the room is in the upper half: door below
                wy, sy, sweep = y + h, -1, 0
            else:
                wy, sy, sweep = y, 1, 1
            out.append(f'<line x1="{dx:g}" y1="{wy:g}" x2="{dx + d:g}" y2="{wy:g}" stroke="{fill}" stroke-width="3"/>')
            out.append(f'<path d="M{dx:g},{wy:g} L{dx:g},{wy + sy * d:g} A{d:g},{d:g} 0 0 {sweep} {dx + d:g},{wy:g}" '
                       'fill="none" stroke="#475569" stroke-width="0.6"/>')
    # The beam axis and any other line the drawing had.
    for ln in m["lines"]:
        pts = " ".join(f"{px:g},{py:g}" for px, py in ln["points"])
        dash = ' stroke-dasharray="7 4"' if ln["dashed"] else ""
        width = 2.5 if not ln["dashed"] else 2
        out.append(f'<polyline points="{pts}" fill="none" stroke="{ln["colour"]}" stroke-width="{width}" '
                   f'stroke-linecap="round"{dash}/>')
        if ln["label"]:
            (x0, y0) = ln["points"][0]
            out.append(f'<text x="{x0:g}" y="{y0 + 11:g}" font-family="{FONT}" font-size="7" fill="{ln["colour"]}" '
                       f'font-weight="bold" letter-spacing="0.3" paint-order="stroke" stroke="#ffffff" stroke-width="2.5">'
                       f'{_esc(ln["label"])}</text>')
    # Room labels, last, over everything of the drawing.
    for r in m["rooms"]:
        x, y, w, h = r["box"]
        area = w * h / PX_PER_M ** 2
        sub = f"{r['number']} · {area:.0f} m²" if r["number"] else f"{area:.0f} m²"
        sfs = 6 if w >= 48 else 5
        if len(sub) * sfs * 0.55 > w - 6:
            sub = r["number"]
        below = sfs + 4 if sub else 0
        # The label as it fits best; in a room full of points, a word a line or a smaller size may find a free spot.
        fs, lines = _fit(r["name"], w, h)
        words = r["name"].upper().split()
        variants = [(fs, lines)] + ([(fs, words)] if len(words) > 1 and len(words) <= 3 else []) + \
                   [(max(5.5, fs * 0.8), lines), (max(5.5, fs * 0.8), words if len(words) <= 3 else lines),
                    (max(5.5, fs * 0.65), lines)]
        best = None
        for vfs, vlines in variants:
            vlh = vfs * 1.2
            vpw = min(max(len(t) for t in vlines) * vfs * 0.64 + 10, w - 4)
            vph = len(vlines) * vlh + 5
            if vph + below > h - 4:
                continue
            spot = _label_spot((x, y, w, h), vpw, vph, below, avoid, m["lines"])
            score = _covered((spot[0], spot[1], vpw, vph), avoid, m["lines"], below)
            if best is None or score < best[0]:
                best = (score, vfs, vlines, vpw, vph, spot)
            if score == 0:
                break
        if best is None:
            lh = fs * 1.2
            pw, ph = min(max(len(t) for t in lines) * fs * 0.64 + 10, w - 4), len(lines) * lh + 5
            px, py = _label_spot((x, y, w, h), pw, ph, below, avoid, m["lines"])
        else:
            _, fs, lines, pw, ph, (px, py) = best
            lh = fs * 1.2
        mid = px + pw / 2
        out.append(f'<rect x="{px:g}" y="{py:g}" width="{pw:g}" height="{ph:g}" rx="3" fill="#ffffff" fill-opacity="0.94" '
                   'stroke="#94a3b8" stroke-width="0.6"/>')
        for k, s in enumerate(lines):
            out.append(f'<text x="{mid:g}" y="{py + 2.5 + lh * (k + 1) - lh * 0.25:g}" font-family="{FONT}" '
                       f'font-size="{fs:g}" font-weight="bold" letter-spacing="0.2" text-anchor="middle" '
                       f'fill="#0f172a">{_esc(s)}</text>')
        if py + ph + 3 + sfs < y + h - 2 and sub:
            out.append(f'<text x="{mid:g}" y="{py + ph + 2 + sfs:g}" font-family="{FONT}" font-size="{sfs:g}" '
                       f'text-anchor="middle" fill="#475569">{_esc(sub)}</text>')
    # The title block under the building: title and the synthetic note on the left; north and a scale bar on the right.
    top = by + bh + 4
    band = H - top
    if band >= 24:
        right = 10 * PX_PER_M + 40                                  # the scale bar and north
        avail = bw - 18 - right
        title = m["title"]
        note = (m.get("note") if m.get("kind") == "drawn" else None) or (
            "Drawn in ARGUS · schematic, not a survey" if m.get("kind") == "drawn"
            else "Synthetic demo plan · not a real building")
        tfs = max(7.0, min(15.0, band * 0.28, avail / max(len(title) * 0.56, 1)))
        nfs = max(5.5, min(tfs * 0.62, avail / max(len(note) * 0.5, 1)))
        out.append(f'<text x="{bx + 6:g}" y="{top + tfs + 3:g}" font-family="{FONT}" font-size="{tfs:g}" font-weight="bold" '
                   f'fill="#0f172a">{_esc(title)}</text>')
        out.append(f'<text x="{bx + 6:g}" y="{top + tfs + 5 + nfs * 1.25:g}" font-family="{FONT}" font-size="{nfs:g}" '
                   f'fill="#b91c1c">{_esc(note)}</text>')
        sx, sy = bx + bw - 6 - 10 * PX_PER_M, top + band * 0.3
        bar = []
        for k in range(2):
            bar.append(f'<rect x="{sx + k * 5 * PX_PER_M:g}" y="{sy:g}" width="{5 * PX_PER_M:g}" height="3" '
                       f'fill="{"#1f2937" if k == 0 else "#ffffff"}" stroke="#1f2937" stroke-width="0.6"/>')
        for k, label in enumerate(("0", "5", "10 m")):
            bar.append(f'<text x="{sx + k * 5 * PX_PER_M:g}" y="{sy + 10:g}" font-family="{FONT}" font-size="6" '
                       f'text-anchor="middle" fill="#334155">{label}</text>')
        out.append("".join(bar))
        if m["north"]:
            nx, ny = sx - 30, top + band * 0.45
            out.append(f'<g transform="translate({nx:g},{ny:g})"><circle r="9" fill="#ffffff" stroke="#334155" stroke-width="0.8"/>'
                       '<polygon points="0,-7 3.5,3.5 0,1.2 -3.5,3.5" fill="#0f172a"/>'
                       f'<text x="12" y="3" font-family="{FONT}" font-size="7" font-weight="bold" fill="#0f172a">N</text></g>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def redraw(svg: str, avoid: dict | None = None) -> str:
    return draw(read(svg), avoid)


# --------------------------------------------------------------------------- a layout in metres

MAX_SIDE_M = 400                                           # 4000 px a side, the size of a plan picture
BAND = 64                                                  # the title block under the building, in px
ORIGIN = 20.0                                              # the outer wall's corner, in px: room for the axes


def _m(v, what: str, low: float, high: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise PlanDrawingError(f"{what}: a number of metres") from None
    if not (low <= f <= high):
        raise PlanDrawingError(f"{what}: between {low:g} and {high:g} m")
    return round(f, 2)


def layout_of(model: dict) -> dict:
    """The layout in metres a drawing was made from (or reads as): the building's size, and each room from the
    building's top-left corner."""
    bx, by, bw, bh = model["building"]
    rooms = []
    for r in model["rooms"]:
        x, y, w, h = r["box"]
        rooms.append({"name": r["name"], "number": r.get("number") or "", "record": r.get("record"),
                      "x": round((x - bx) / PX_PER_M, 2), "y": round((y - by) / PX_PER_M, 2),
                      "w": round(w / PX_PER_M, 2), "d": round(h / PX_PER_M, 2)})
    return {"title": model.get("title") or "", "width_m": round(bw / PX_PER_M, 2), "depth_m": round(bh / PX_PER_M, 2),
            "rooms": rooms, "north": bool(model.get("north"))}


def from_layout(layout: dict, before: dict | None = None) -> dict:
    """The drawing's model from a layout in metres. Redrawing a plan (`before`), the building keeps its corner and
    the drawing keeps what a layout does not say (the beam axis, a demo's note)."""
    if not isinstance(layout, dict):
        raise PlanDrawingError("a layout: the building's size and its rooms")
    W = _m(layout.get("width_m"), "the building's width", 2, MAX_SIDE_M)
    D = _m(layout.get("depth_m"), "the building's depth", 2, MAX_SIDE_M)
    title = str(layout.get("title") or "").strip()[:120]
    if not title:
        raise PlanDrawingError("the plan needs a title")
    bx, by = (before["building"][0], before["building"][1]) if before else (ORIGIN, ORIGIN)
    raw = layout.get("rooms") or []
    if not isinstance(raw, list) or len(raw) > 200:
        raise PlanDrawingError("rooms: a list, at most 200")
    rooms, boxes = [], []
    for n, r in enumerate(raw, start=1):
        if not isinstance(r, dict):
            raise PlanDrawingError(f"room {n}: its name, where it is and its size")
        name = str(r.get("name") or "").strip()[:80]
        if not name:
            raise PlanDrawingError(f"room {n}: a name")
        x, y = _m(r.get("x"), f"{name}: x", 0, W), _m(r.get("y"), f"{name}: y", 0, D)
        w, d = _m(r.get("w"), f"{name}: width", 1, W), _m(r.get("d"), f"{name}: depth", 1, D)
        if x + w > W + 1e-6 or y + d > D + 1e-6:
            raise PlanDrawingError(f"{name} goes past the building's walls")
        for other, (ox, oy, ow, od) in boxes:
            if x < ox + ow - 1e-6 and ox < x + w - 1e-6 and y < oy + od - 1e-6 and oy < y + d - 1e-6:
                raise PlanDrawingError(f"{name} overlaps {other}")
        boxes.append((name, (x, y, w, d)))
        room = {"box": [bx + x * PX_PER_M, by + y * PX_PER_M, w * PX_PER_M, d * PX_PER_M], "name": name,
                "number": str(r.get("number") or "").strip()[:20]}
        if r.get("record"):
            room["record"] = str(r["record"])
        rooms.append(room)
    width, height = bx * 2 + W * PX_PER_M, by * 2 + D * PX_PER_M + BAND
    if before and before.get("kind") != "drawn":                        # a demo keeps its own size and band
        width, height = max(width, before["width"]), max(height, before["height"])
    model = {"width": round(width, 2), "height": round(height, 2), "building": [bx, by, W * PX_PER_M, D * PX_PER_M],
             "rooms": rooms, "lines": (before or {}).get("lines", []),
             "north": [0, 0] if layout.get("north", True) else None, "title": title,
             "note": (before or {}).get("note", ""), "kind": (before or {}).get("kind", "drawn")}
    return model


def drawn_model(svg: str) -> dict | None:
    """The model of a drawing made here, or None for any other picture."""
    if MARK not in svg:
        return None
    return read(svg)
