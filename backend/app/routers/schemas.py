import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_permission
from app.db import get_db
from app.models.icon import Icon
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.schemas.schema import SchemaCreate, SchemaOut, SchemaUpdate
from app.services.relations import rebuild_relations_for_schemas

router = APIRouter(prefix="/v1/schemas", tags=["schemas"])

ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR", "/data/attachments")


@router.get("", response_model=list[SchemaOut])
def list_schemas(
    workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)
):
    from app.packages.origin import origins
    rows = db.scalars(
        select(Schema).where(
            or_(Schema.workspace_id == workspace_id, Schema.is_global.is_(True))
        )
    ).all()
    found = origins(db, rows)
    return [SchemaOut.model_validate(s).model_copy(update={"origin": found.get(s.uid)}) for s in rows]


@router.post("", response_model=SchemaOut, status_code=201)
def create_schema(
    body: SchemaCreate,
    workspace_id: str = Depends(require_permission("create")),
    db: Session = Depends(get_db),
):
    if db.get(Schema, body.uid) is not None:
        raise HTTPException(status_code=409, detail="Schema uid already exists")
    schema = Schema(workspace_id=workspace_id, **body.model_dump())
    # A globally-shared workspace shares every type in it, including ones
    # created after the flag was set — otherwise the workspace-level flag
    # silently decays as new types appear.
    workspace = db.get(Workspace, workspace_id)
    if workspace is not None and workspace.is_global:
        schema.is_global = True
    db.add(schema)
    db.commit()
    db.refresh(schema)
    return schema


def _get_owned_schema(uid: str, workspace_id: str, db: Session) -> Schema:
    """Strict same-workspace lookup — used by every write endpoint. A global
    schema owned by another workspace is visible (see _get_visible_schema) but
    still can't be edited except by its owning workspace."""
    schema = db.get(Schema, uid)
    if schema is None or schema.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Schema not found")
    return schema


def _get_visible_schema(uid: str, workspace_id: str, db: Session) -> Schema:
    schema = db.get(Schema, uid)
    if schema is None or (schema.workspace_id != workspace_id and not schema.is_global):
        raise HTTPException(status_code=404, detail="Schema not found")
    return schema


@router.get("/{uid}", response_model=SchemaOut)
def get_schema(
    uid: str, workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)
):
    from app.packages.origin import origins
    s = _get_visible_schema(uid, workspace_id, db)
    return SchemaOut.model_validate(s).model_copy(update={"origin": origins(db, [s]).get(s.uid)})


def _cascade_global_to_children(db: Session, schema: Schema) -> list[str]:
    """When a type becomes global, its whole subtree becomes global too —
    otherwise a child type's instances would stay invisible cross-workspace
    even though the parent type says "referenceable from anywhere"."""
    changed_uids = [schema.uid]
    stack = [schema.uid]
    while stack:
        parent_uid = stack.pop()
        children = db.scalars(select(Schema).where(Schema.parent_schema_uid == parent_uid)).all()
        for child in children:
            if not child.is_global:
                child.is_global = True
                changed_uids.append(child.uid)
            stack.append(child.uid)
    return changed_uids


@router.put("/{uid}", response_model=SchemaOut)
def update_schema(
    uid: str,
    body: SchemaUpdate,
    workspace_id: str = Depends(require_permission("modify")),
    db: Session = Depends(get_db),
):
    schema = _get_owned_schema(uid, workspace_id, db)
    patch = body.model_dump(exclude_unset=True)
    turning_global = patch.get("is_global") is True and not schema.is_global
    turning_non_global = patch.get("is_global") is False and schema.is_global
    for field, value in patch.items():
        setattr(schema, field, value)

    affected_schema_uids: list[str] = []
    if turning_global:
        affected_schema_uids = _cascade_global_to_children(db, schema)
    elif turning_non_global:
        affected_schema_uids = [schema.uid]

    db.commit()
    db.refresh(schema)

    if affected_schema_uids:
        rebuild_relations_for_schemas(db, affected_schema_uids)
        db.commit()

    return schema


@router.delete("/{uid}", status_code=204)
def delete_schema(
    uid: str, workspace_id: str = Depends(require_permission("delete")), db: Session = Depends(get_db)
):
    """Deleting a type cascades (at the DB level, via ON DELETE CASCADE) to its
    child types, and to every object/ticket of the type or any of its
    children — including ones owned by other workspaces if the type is
    global. A ticket merely *linked* to a deleted object keeps existing with
    that link cleared (asset_uid ON DELETE SET NULL)."""
    schema = _get_owned_schema(uid, workspace_id, db)
    db.delete(schema)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Could not delete this type — it is still referenced elsewhere",
        )


@router.post("/{uid}/icon", response_model=SchemaOut)
async def upload_schema_icon(
    uid: str,
    file: UploadFile,
    workspace_id: str = Depends(require_permission("modify")),
    db: Session = Depends(get_db),
):
    """Upload straight onto a type — the common case, and a shortcut for
    "upload to the library, then pick it" in one step. The uploaded picture
    joins the shared icon library same as anything uploaded there directly,
    so it can be reused by, or unlinked from, this type without losing it."""
    schema = _get_owned_schema(uid, workspace_id, db)

    icon_uid = str(uuid.uuid4())
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    storage_path = os.path.join(ATTACHMENTS_DIR, icon_uid)
    contents = await file.read()
    with open(storage_path, "wb") as f:
        f.write(contents)

    workspace = db.get(Workspace, workspace_id)
    db.add(Icon(
        uid=icon_uid,
        workspace_id=workspace_id,
        name=file.filename or icon_uid,
        filename=file.filename or icon_uid,
        mime_type=file.content_type,
        file_size=len(contents),
        storage_path=storage_path,
        is_global=bool(workspace is not None and workspace.is_global),
    ))
    schema.icon_uid = icon_uid
    db.commit()
    db.refresh(schema)
    return schema


@router.put("/{uid}/icon/{icon_uid}", response_model=SchemaOut)
def set_schema_icon_from_library(
    uid: str,
    icon_uid: str,
    workspace_id: str = Depends(require_permission("modify")),
    db: Session = Depends(get_db),
):
    """Point this type at a picture already in the shared icon library —
    reused as-is, not duplicated."""
    schema = _get_owned_schema(uid, workspace_id, db)
    icon = db.get(Icon, icon_uid)
    if icon is None or (icon.workspace_id != workspace_id and not icon.is_global):
        raise HTTPException(status_code=404, detail="Icon not found")
    schema.icon_uid = icon_uid
    db.commit()
    db.refresh(schema)
    return schema


@router.delete("/{uid}/icon", response_model=SchemaOut)
def clear_schema_icon(
    uid: str,
    workspace_id: str = Depends(require_permission("modify")),
    db: Session = Depends(get_db),
):
    """Unlink this type's icon — the picture itself stays in the library,
    since other types may still be using it."""
    schema = _get_owned_schema(uid, workspace_id, db)
    schema.icon_uid = None
    db.commit()
    db.refresh(schema)
    return schema
