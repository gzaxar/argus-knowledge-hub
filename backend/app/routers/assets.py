import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import OidcIdentity, get_current_user_id, get_grants, get_identity, require_permission
from app.db import get_db
from app.ledger.cutover import assert_writable
from app.ledger import service as ledger_service
from app.ledger.engine import LedgerError
from app.ledger.identity import DuplicateIdentifier, assert_unique_at_creation
from app.models.asset import Asset, Relation
from app.models.attachment import Attachment
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.schemas.asset import (
    AssetCreate,
    AssetOut,
    AssetUpdate,
    BulkDeleteRequest,
    BulkDeleteResult,
    NextKeyOut,
    RelationCreate,
    RelationOut,
)
from app.services import asset_keys, versions
from app.services.attribute_validation import validate_attributes
from app.services.current_user_attrs import stamp_current_user_attributes
from app.services.relations import rebuild_asset_relations, rebuild_asset_relations_with_neighbors
from app.services.visibility import (asset_visible_in, hidden_fields, redacted_attributes, visible_assets_clause,
                                     visible_uids)

router = APIRouter(prefix="/v1/assets", tags=["assets"])


def _actor(identity) -> str:
    if isinstance(identity, OidcIdentity):
        return identity.user.email or identity.user.id
    return "api-token"


def _check_class(db: Session, type_name: str, attributes: dict, current: Optional[str]) -> None:
    """§5.5: Other Equipment always has a class, and only an active class can
    be given (I-CAT-1). A class it already has stays, even once deprecated."""
    from app.services import equipment_classes as ec
    if type_name != ec.OTHER:
        return
    if not attributes.get("equipment_class"):
        attributes["equipment_class"] = ec.UNCLASSIFIED
    if attributes["equipment_class"] != current:
        try:
            ec.assert_assignable(db, attributes["equipment_class"])
        except ec.ClassError as exc:
            raise HTTPException(status_code=422, detail={"error": str(exc), "invariant": "I-CAT-1"})


def _ledger_only(db: Session, workspace_id: str) -> bool:
    w = db.get(Workspace, workspace_id)
    return bool(w and w.ledger_only)


def _ledger_failed(db: Session, exc: LedgerError):
    db.rollback()
    code = getattr(exc, "code", None)
    raise HTTPException(status_code=409 if code else 422, detail={"error": str(exc), "invariant": code})

ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR", "/data/attachments")


def _with_subtypes(db: Session, schema_uid: str) -> list[str]:
    """A type and every type below it, as the web's type tree selects them."""
    children: dict[str, list[str]] = {}
    for uid, parent in db.execute(select(Schema.uid, Schema.parent_schema_uid)):
        if parent:
            children.setdefault(parent, []).append(uid)
    out, todo = [], [schema_uid]
    while todo:
        uid = todo.pop()
        if uid not in out:
            out.append(uid)
            todo.extend(children.get(uid, []))
    return out


_SORT = {"name": Asset.name, "key": Asset.key, "created": Asset.created_at, "updated": Asset.updated_at}


@router.get("", response_model=list[AssetOut])
def list_assets(
    response: Response,
    schema_uid: Optional[str] = None,
    include_subtypes: bool = Query(False, description="With schema_uid: also the records of every type below it."),
    q: Optional[str] = Query(None, description="Only records whose key, name, a label (a QR code, a barcode, a "
                                               "former key, an alias), serial, inventory number or MAC contains "
                                               "this, ignoring case."),
    sort: Optional[str] = Query(None, pattern="^(name|key|created|updated)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: Optional[int] = Query(None, ge=1, le=500,
                                 description="A page of at most this many, with the total in X-Total-Count. "
                                             "Without it, every record (and deleted ones are not left out)."),
    offset: int = Query(0, ge=0),
    workspace_id: str = Depends(require_permission("read")),
    grants=Depends(get_grants),
    db: Session = Depends(get_db),
):
    # This workspace's own objects, and any other workspace's that are flagged
    # global. Being of a global *type* is not enough (see services/visibility).
    # A restricted record is absent unless the viewer holds its class.
    stmt = select(Asset).where(visible_assets_clause(workspace_id, grants))
    if schema_uid:
        stmt = stmt.where(Asset.schema_uid.in_(_with_subtypes(db, schema_uid)) if include_subtypes
                          else Asset.schema_uid == schema_uid)
    if q and q.strip():
        from app.services.identifiers import text_clause
        stmt = stmt.where(text_clause(db, grants, q))
    if limit is None and not sort:
        return [asset_out(db, a) for a in db.scalars(stmt).all()]
    if limit is not None:
        # A page is for browsing: what was deleted is not part of it.
        stmt = stmt.where(Asset.deleted_at.is_(None))
        response.headers["X-Total-Count"] = str(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    column = _SORT[sort or "name"]
    stmt = stmt.order_by(column.desc().nulls_last() if order == "desc" else column.asc().nulls_last(), Asset.uid)
    if limit is not None:
        stmt = stmt.offset(offset).limit(limit)
    return [asset_out(db, a) for a in db.scalars(stmt).all()]


@router.get("/type-counts", response_model=dict[str, int])
def asset_type_counts(
    workspace_id: str = Depends(require_permission("read")),
    grants=Depends(get_grants),
    db: Session = Depends(get_db),
):
    """How many visible, not deleted records each type has (its own, not its subtypes'): what a type tree
    shows beside each type."""
    rows = db.execute(select(Asset.schema_uid, func.count()).where(
        visible_assets_clause(workspace_id, grants), Asset.deleted_at.is_(None)).group_by(Asset.schema_uid))
    return {uid: n for uid, n in rows if uid}


def _shown(v) -> str:
    if v is None or v == "" or v == []:
        return "—"
    text = ", ".join(map(str, v)) if isinstance(v, list) else str(v)
    return text if len(text) <= 80 else text[:77] + "…"


def _record_edit(db: Session, asset: Asset, changes: dict, before: dict, actor: str) -> None:
    """A person's edit, in the record's history beside what was imported and added by hand: which fields
    changed, from what to what. (The ledger keeps the full trail; this is the line a person reads.)"""
    import uuid
    from datetime import datetime, timezone
    from app.models.asset_subresources import AssetHistory
    names = {}
    schema = db.get(Schema, asset.schema_uid)
    for a in (schema.attributes if schema and isinstance(schema.attributes, list) else []):
        if isinstance(a, dict) and a.get("key"):
            names[a["key"]] = a.get("name") or a["key"]
    parts = []
    for k, v in changes.items():
        if k == "name":
            parts.append(f"Name: {_shown(before.get('name'))} → {_shown(v)}")
        elif k.startswith("attr:"):
            parts.append(f"{names.get(k[5:], k[5:])}: {_shown(before.get(k))} → {_shown(v)}")
    if not parts:
        return
    details = "; ".join(parts)
    db.add(AssetHistory(uid=str(uuid.uuid4()), asset_uid=asset.uid, type="edit", author=actor,
                        details=details if len(details) <= 2000 else details[:1999] + "…",
                        timestamp=datetime.now(timezone.utc)))
    from app.services import notify
    notify.asset_changed(db, asset.uid, details, actor)


def asset_out(db: Session, asset: Asset) -> AssetOut:
    """What the viewer may see of a record: no restricted field, and no
    restricted neighbour in its relation lists, not even by uid (I-ACL-1)."""
    out = AssetOut.model_validate(asset)
    return out.model_copy(update={
        "attributes": redacted_attributes(db, asset),
        "outbound_relations": visible_uids(db, out.outbound_relations),
        "inbound_relations": visible_uids(db, out.inbound_relations),
    })


@router.post("", response_model=AssetOut, status_code=201)
def create_asset(
    body: AssetCreate,
    identity=Depends(get_identity),
    workspace_id: str = Depends(require_permission("create")),
    current_user_id: Optional[str] = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    if db.get(Asset, body.uid) is not None:
        raise HTTPException(status_code=409, detail="Asset uid already exists")
    schema = db.get(Schema, body.schema_uid)
    # A type is usable here if this workspace owns it or it is shared. Without
    # this check a token could attach objects to another workspace's private
    # type (asset-model-revision §4.3).
    if schema is None or (schema.workspace_id != workspace_id and not schema.is_global):
        raise HTTPException(status_code=422, detail="Unknown object type for this workspace")
    _assert_writable(db, workspace_id)
    # A record's type follows its schema, as on update: the ledger and the
    # graph select records by it, so a free-typed one would hide them.
    type_name = schema.name
    _check_class(db, type_name, body.attributes, None)
    stamp_current_user_attributes(db, schema, body.attributes, current_user_id)
    validate_attributes(db, schema, body.attributes, workspace_id, Asset)
    _assert_unique(db, workspace_id, body.attributes, type_name=type_name)
    data = body.model_dump()
    data["key"] = (data.get("key") or "").strip()
    if not data["key"]:
        try:
            data["key"] = asset_keys.allocate(db, workspace_id, schema)
        except asset_keys.KeyPatternError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail=str(exc))
    elif db.scalar(select(Asset.uid).where(Asset.key == data["key"])) is not None:
        raise HTTPException(status_code=409, detail=f"The key {data['key']} is already taken")
    # Made in a global workspace, an object is global unless it says otherwise —
    # as its types and documents already are.
    workspace = db.get(Workspace, workspace_id)
    if "is_global" not in body.model_fields_set and workspace is not None and workspace.is_global:
        data["is_global"] = True
    # Through the fact ledger (§13 S5): the creator's statements, confirmed by them.
    try:
        asset = ledger_service.create_record(
            db, workspace_id, _actor(identity), uid=data["uid"], schema_uid=data["schema_uid"], key=data["key"],
            name=data["name"], type_name=type_name, attributes=data["attributes"],
            is_global=data.get("is_global", False), avatar_icon_uid=data.get("avatar_icon_uid"))
    except LedgerError as exc:
        _ledger_failed(db, exc)
    from app.services import notify
    notify.announce(db, workspace_id, "assets", "new_asset", f"New equipment: {asset.name} ({asset.key})",
                    current_user_id or _actor(identity), asset.uid, record=asset)
    db.commit()
    db.refresh(asset)
    return asset


def _get_owned_asset(uid: str, workspace_id: str, db: Session) -> Asset:
    """Strict same-workspace lookup — used by every write endpoint. A global
    asset owned by another workspace is visible (see _get_visible_asset) but
    still can't be edited except by its owning workspace."""
    asset = db.get(Asset, uid)
    if asset is None or asset.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Asset not found")
    _assert_writable(db, workspace_id)
    return asset


def _assert_writable(db: Session, workspace_id: str) -> None:
    """No dual write (§17.2): a scope being migrated is read-only here until
    its cutover exit is signed."""
    try:
        assert_writable(db, workspace_id, "objects")
    except LedgerError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc), "invariant": "I-SOR-1"})


def _assert_unique(db: Session, workspace_id: str, attributes: dict, exclude: Optional[str] = None,
                   type_name: Optional[str] = None) -> None:
    try:
        assert_unique_at_creation(db, workspace_id, attributes, exclude, type_name)
    except DuplicateIdentifier as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc), "invariant": exc.code,
                                                     "existing": exc.existing})


def _get_visible_asset(uid: str, workspace_id: str, db: Session, grants=None) -> Asset:
    asset = db.get(Asset, uid)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset_visible_in(asset, workspace_id, grants):
        return asset
    raise HTTPException(status_code=404, detail="Asset not found")


@router.get("/next-key", response_model=NextKeyOut)
def next_key(
    schema_uid: Optional[str] = None,
    workspace_id: str = Depends(require_permission("create")),
    db: Session = Depends(get_db),
):
    """The key a record of this type would get now, for the form to show.
    Nothing is reserved; the key is taken only when the record is created."""
    schema = db.get(Schema, schema_uid) if schema_uid else None
    return NextKeyOut(key=asset_keys.preview(db, workspace_id, schema),
                      pattern=asset_keys.pattern_for(db.get(Workspace, workspace_id)))


@router.get("/{uid}", response_model=AssetOut)
def get_asset(
    uid: str, response: Response, workspace_id: str = Depends(require_permission("read")),
    grants=Depends(get_grants), db: Session = Depends(get_db),
):
    asset = _get_visible_asset(uid, workspace_id, db, grants)
    # Keep the denormalized relation cache honest every time an object is
    # actually looked at, independent of whatever else may have changed it
    # (relations are also resynced at the point of change, but this catches
    # anything that slips through, e.g. cross-workspace visibility shifts).
    rebuild_asset_relations(db, uid)
    db.commit()
    db.refresh(asset)
    out = asset_out(db, asset)
    out.version = versions.asset_version(db, uid)
    response.headers["ETag"] = versions.etag(out.version)
    return out


@router.put("/{uid}", response_model=AssetOut)
def update_asset(
    uid: str,
    body: AssetUpdate,
    identity=Depends(get_identity),
    workspace_id: str = Depends(require_permission("modify")),
    current_user_id: Optional[str] = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    if_match: Optional[str] = Header(None, alias="If-Match",
                                     description="The version read (flutter-app-design §3.3)"),
):
    asset = _get_owned_asset(uid, workspace_id, db)
    patch = body.model_dump(exclude_unset=True)
    # Never a legitimate value for this not-null column: a client whose JSON encoder cannot omit an
    # unset field (the field app's generated client always writes every field, null where unset)
    # would otherwise send this on every edit and crash the write, not just leave it unchanged.
    if patch.get("is_global") is None:
        patch.pop("is_global", None)
    global_changed = "is_global" in patch and patch["is_global"] != asset.is_global
    if patch.get("attributes") is not None:
        # A field the editor cannot see is neither erased nor overwritten by
        # them: it was never in the form they submitted (I-ACL-1).
        hidden = hidden_fields(db, asset)
        patch["attributes"] = {**{k: v for k, v in patch["attributes"].items() if k not in hidden},
                               **{k: v for k, v in (asset.attributes or {}).items() if k in hidden}}
    # Facts (attributes, name) go through the fact ledger (§13 S5); display
    # and caching fields (avatar, relation caches, sharing) are set here.
    new_attrs = patch.pop("attributes", None)
    new_name = patch.pop("name", None)
    patch.pop("type", None)                # a record's type follows its schema, not a free edit
    for field, value in patch.items():
        setattr(asset, field, value)
    schema = db.get(Schema, asset.schema_uid) if asset.schema_uid else None
    changes: dict = {}
    if new_attrs is not None:
        _check_class(db, asset.type, new_attrs, (asset.attributes or {}).get("equipment_class"))
        stamp_current_user_attributes(db, schema, new_attrs, current_user_id)
        validate_attributes(db, schema, new_attrs, workspace_id, Asset, exclude_uid=uid)
        _assert_unique(db, workspace_id, new_attrs, exclude=uid, type_name=asset.type)
        current = asset.attributes or {}
        changes.update({f"attr:{k}": v for k, v in new_attrs.items() if current.get(k) != v})
        changes.update({f"attr:{k}": None for k in current if k not in new_attrs})
    if new_name is not None and new_name != asset.name:
        changes["name"] = new_name
    if changes:
        versions.check_asset(db, asset, if_match, changes, {"kind": "edit", "uid": uid, "changes": changes},
                             _actor(identity))
        before = {"name": asset.name, **{f"attr:{k}": v for k, v in (asset.attributes or {}).items()}}
        try:
            ledger_service.edit_values(db, workspace_id, _actor(identity), uid, changes)
        except LedgerError as exc:
            _ledger_failed(db, exc)
        _record_edit(db, asset, changes, before, _actor(identity))
    db.commit()
    if global_changed:
        # Cross-workspace visibility just changed — this asset's neighbors
        # may now (or no longer) be able to see it, so their cached relation
        # lists need to reflect that too.
        rebuild_asset_relations_with_neighbors(db, uid)
        db.commit()
    db.refresh(asset)
    out = asset_out(db, asset)
    out.version = versions.asset_version(db, uid)
    return out


@router.delete("/{uid}", status_code=204)
def delete_asset(
    uid: str, identity=Depends(get_identity), workspace_id: str = Depends(require_permission("delete")),
    db: Session = Depends(get_db), x_argus_client: Optional[str] = Header(None, alias="X-ARGUS-Client"),
):
    from app.services import field_policy
    field_policy.refuse_retirement(x_argus_client)
    asset = _get_owned_asset(uid, workspace_id, db)
    if _ledger_only(db, workspace_id):
        # A ledger-only workspace retires, never erases: the record keeps its history.
        try:
            ledger_service.retire_record(db, workspace_id, _actor(identity), uid, "deleted")
        except LedgerError as exc:
            _ledger_failed(db, exc)
    else:
        db.delete(asset)
    db.commit()


@router.post("/bulk-delete", response_model=BulkDeleteResult)
def bulk_delete_assets(
    body: BulkDeleteRequest,
    identity=Depends(get_identity),
    workspace_id: str = Depends(require_permission("delete")),
    db: Session = Depends(get_db),
):
    _assert_writable(db, workspace_id)
    from app.ledger.bulk import APPROVAL_THRESHOLD
    if len(body.uids) > APPROVAL_THRESHOLD:
        # Above the threshold a change needs a preview and a second person
        # (§19 item 7): retire the records with a bulk change instead.
        raise HTTPException(status_code=409, detail={
            "error": f"more than {APPROVAL_THRESHOLD} records: use a bulk change (POST /v1/bulk-changes with "
                     f"\"retire\": true), which is previewed, approved and can be undone"})
    deleted = 0
    missing: list[str] = []
    for uid in body.uids:
        asset = db.get(Asset, uid)
        if asset is None or asset.workspace_id != workspace_id:
            missing.append(uid)
            continue
        if _ledger_only(db, workspace_id):
            ledger_service.retire_record(db, workspace_id, _actor(identity), uid, "deleted")
        else:
            db.delete(asset)
        deleted += 1
    db.commit()
    return BulkDeleteResult(deleted=deleted, not_found=missing)


@router.post("/{uid}/avatar", response_model=AssetOut)
async def upload_asset_avatar(
    uid: str,
    file: UploadFile,
    workspace_id: str = Depends(require_permission("modify")),
    db: Session = Depends(get_db),
):
    """Upload a picture and make it this object's avatar. The file is stored
    as a normal attachment of the object, so replacing the avatar doesn't
    destroy the previous picture — it simply reappears among the
    attachments, where it can be deleted or promoted back."""
    asset = _get_owned_asset(uid, workspace_id, db)

    attachment_uid = str(uuid.uuid4())
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    storage_path = os.path.join(ATTACHMENTS_DIR, attachment_uid)
    contents = await file.read()
    with open(storage_path, "wb") as f:
        f.write(contents)

    db.add(Attachment(
        uid=attachment_uid,
        workspace_id=workspace_id,
        asset_uid=uid,
        filename=file.filename or attachment_uid,
        mime_type=file.content_type,
        file_size=len(contents),
        storage_path=storage_path,
    ))
    asset.avatar_icon_uid = attachment_uid
    db.commit()
    db.refresh(asset)
    return asset


@router.put("/{uid}/avatar/{attachment_uid}", response_model=AssetOut)
def set_asset_avatar_from_attachment(
    uid: str,
    attachment_uid: str,
    workspace_id: str = Depends(require_permission("modify")),
    db: Session = Depends(get_db),
):
    """Promote a picture already attached to this object to be its avatar —
    the common case for imported objects, whose pictures arrive as
    attachments."""
    asset = _get_owned_asset(uid, workspace_id, db)
    attachment = db.get(Attachment, attachment_uid)
    if attachment is None or attachment.asset_uid != uid:
        raise HTTPException(status_code=404, detail="Attachment not found on this object")
    asset.avatar_icon_uid = attachment_uid
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/{uid}/avatar", response_model=AssetOut)
def clear_asset_avatar(
    uid: str,
    workspace_id: str = Depends(require_permission("modify")),
    db: Session = Depends(get_db),
):
    """Clear the avatar. The picture itself stays as an attachment."""
    asset = _get_owned_asset(uid, workspace_id, db)
    asset.avatar_icon_uid = None
    db.commit()
    db.refresh(asset)
    return asset


relations_router = APIRouter(prefix="/v1/relations", tags=["relations"])


@relations_router.get("", response_model=list[RelationOut])
def list_relations(
    workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)
):
    return db.scalars(
        select(Relation).where(Relation.workspace_id == workspace_id)
    ).all()


@relations_router.post("", response_model=RelationOut, status_code=201)
def create_relation(
    body: RelationCreate,
    identity=Depends(get_identity),
    workspace_id: str = Depends(require_permission("create")),
    db: Session = Depends(get_db),
):
    # from_asset_uid must belong to the acting workspace (it's what this relation
    # is attached to); to_asset_uid may point at another workspace's asset only if
    # that asset is global.
    source = _get_owned_asset(body.from_asset_uid, workspace_id, db)
    target = _get_visible_asset(body.to_asset_uid, workspace_id, db)
    from app.packages import relations
    wrong = relations.check(db, body.relation_type, source.schema_uid, target.schema_uid)
    if wrong:
        raise HTTPException(status_code=422, detail={"error": wrong, "code": "relation_type"})

    # An asserted edge is a person's statement in the fact ledger (§13 S5).
    try:
        ledger_service.relate(db, workspace_id, _actor(identity), body.from_asset_uid, body.relation_type,
                              body.to_asset_uid, present=True)
    except LedgerError as exc:
        _ledger_failed(db, exc)
    db.commit()
    relation = db.scalar(select(Relation).where(
        Relation.from_asset_uid == body.from_asset_uid, Relation.to_asset_uid == body.to_asset_uid,
        Relation.relation_type == body.relation_type).order_by(Relation.id.desc()).limit(1))
    if relation is None:
        raise HTTPException(status_code=409, detail={"error": "the ledger did not project the relation"})
    rebuild_asset_relations(db, body.from_asset_uid)
    rebuild_asset_relations(db, body.to_asset_uid)
    db.commit()
    return relation


@relations_router.delete("/{relation_id}", status_code=204)
def delete_relation(
    relation_id: int,
    identity=Depends(get_identity),
    workspace_id: str = Depends(require_permission("delete")),
    db: Session = Depends(get_db),
):
    relation = db.get(Relation, relation_id)
    if relation is None or relation.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Relation not found")
    if relation.derivation not in (None, "ledger"):
        # Derived edges follow from other facts (I-PROJ-2): change the source,
        # the installation or the decision behind the edge instead.
        raise HTTPException(status_code=409, detail="This relation is derived by the fact ledger "
                                                    "and cannot be removed directly")
    from_uid, to_uid = relation.from_asset_uid, relation.to_asset_uid
    try:
        if relation.derivation == "ledger":
            # An asserted edge: the person states it no longer holds.
            ledger_service.relate(db, workspace_id, _actor(identity), from_uid, relation.relation_type, to_uid,
                                  present=False)
        else:
            ledger_service.remove_legacy_edge(db, workspace_id, _actor(identity), relation)
    except LedgerError as exc:
        _ledger_failed(db, exc)
    db.commit()
    rebuild_asset_relations(db, from_uid)
    rebuild_asset_relations(db, to_uid)
    db.commit()

