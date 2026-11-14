"""A rack surveyed from a phone (services/rack_census.py, docs/rack-census.md).

- `POST /v1/rack-census` `{rack_uid?, place_uid?}` — start; `GET /v1/rack-census` — the surveys still open, to resume.
- `GET /v1/rack-census/{uid}`; `DELETE` — leave it (abandoned, nothing changed).
- `POST /{uid}/photos` (multipart: `role` rack_front|rack_rear|device|label, `item`, `file`) — a photo, and what was
  read on it as proposals with evidence and confidence.
- `PUT /{uid}/rack` — the rack is an existing one, or a new one's name, units, room and confirmed plan point.
- `PUT /{uid}/items/{item}` — the person's values, and link / create / skip; `DELETE` — drop a unit.
- `GET /{uid}/review` — what is missing, overlapping or possibly a duplicate; `POST /{uid}/apply` — make it so.
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_identity, require_permission
from app.db import get_db
from app.routers.ledger import actor_of
from app.services import rack_census as census

router = APIRouter(prefix="/v1/rack-census", tags=["rack census"])

MAX_PHOTO = 20 * 1024 * 1024


def _fail(e: Exception):
    raise HTTPException(status_code=422, detail={"error": str(e), "code": "rack_census"})


class StartIn(BaseModel):
    rack_uid: Optional[str] = None
    place_uid: Optional[str] = None


class RackIn(BaseModel):
    existing: Optional[str] = None
    values: Optional[dict] = None


class ItemIn(BaseModel):
    values: Optional[dict] = None
    decision: Optional[str] = None
    asset_uid: Optional[str] = None
    duplicate_checked: Optional[bool] = None


@router.post("", status_code=201)
def start(body: StartIn, workspace_id: str = Depends(require_permission("create")), identity=Depends(get_identity),
          db: Session = Depends(get_db)):
    try:
        c = census.start(db, workspace_id, actor_of(identity), rack_uid=body.rack_uid, place_uid=body.place_uid)
    except (census.CensusError, ValueError) as e:
        db.rollback()
        _fail(e)
    db.commit()
    return census.view(db, c)


@router.get("")
def open_surveys(workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """The surveys left open, most recently touched first: each with its rack and how many units it has."""
    out = []
    for c in census.open_surveys(db, workspace_id):
        v = census.view(db, c)
        out.append({"uid": c.uid, "updated_at": c.updated_at, "created_by": c.created_by,
                    "rack": (v["rack"]["record"] or {}).get("name") or (v["rack"].get("values") or {}).get("name"),
                    "items": len(v["items"])})
    return out


@router.get("/{uid}")
def get_survey(uid: str, workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    try:
        return census.view(db, census.get(db, workspace_id, uid))
    except census.CensusError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{uid}")
def abandon(uid: str, workspace_id: str = Depends(require_permission("create")), db: Session = Depends(get_db)):
    try:
        c = census.abandon(db, workspace_id, uid)
    except census.CensusError as e:
        _fail(e)
    db.commit()
    return census.view(db, c)


@router.post("/{uid}/photos")
async def photo(uid: str, role: str = Form(...), item: str = Form(""), file: UploadFile = File(...),
                workspace_id: str = Depends(require_permission("create")), identity=Depends(get_identity),
                db: Session = Depends(get_db)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="The photo was empty.")
    if len(content) > MAX_PHOTO:
        raise HTTPException(status_code=413, detail="That photo is larger than 20 MB.")
    try:
        out = census.add_photo(db, workspace_id, actor_of(identity), uid, role, content, file.filename or "photo.jpg",
                               file.content_type or "image/jpeg", item_id=item or None)
    except census.CensusError as e:
        db.rollback()
        _fail(e)
    db.commit()
    return out


@router.put("/{uid}/rack")
def set_rack(uid: str, body: RackIn, workspace_id: str = Depends(require_permission("create")),
             db: Session = Depends(get_db)):
    try:
        c = census.set_rack(db, workspace_id, uid, existing=body.existing, values=body.values)
    except (census.CensusError, ValueError) as e:
        db.rollback()
        _fail(e)
    db.commit()
    return census.view(db, c)


@router.put("/{uid}/items/{item}")
def set_item(uid: str, item: str, body: ItemIn, workspace_id: str = Depends(require_permission("create")),
             db: Session = Depends(get_db)):
    try:
        c = census.set_item(db, workspace_id, uid, item, values=body.values, decision=body.decision,
                            asset_uid=body.asset_uid, duplicate_checked=body.duplicate_checked)
    except census.CensusError as e:
        db.rollback()
        _fail(e)
    db.commit()
    return census.view(db, c)


@router.delete("/{uid}/items/{item}")
def remove_item(uid: str, item: str, workspace_id: str = Depends(require_permission("create")),
                db: Session = Depends(get_db)):
    try:
        c = census.remove_item(db, workspace_id, uid, item)
    except census.CensusError as e:
        _fail(e)
    db.commit()
    return census.view(db, c)


@router.get("/{uid}/review")
def review(uid: str, workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    try:
        return census.review(db, workspace_id, uid)
    except census.CensusError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{uid}/apply")
def apply(uid: str, workspace_id: str = Depends(require_permission("create")), identity=Depends(get_identity),
          db: Session = Depends(get_db)):
    try:
        out = census.apply(db, workspace_id, uid, identity, actor_of(identity))
    except census.CensusError as e:
        db.rollback()
        _fail(e)
    if not out["ok"]:
        raise HTTPException(status_code=409, detail=out)
    return out
