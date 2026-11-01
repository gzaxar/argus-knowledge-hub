import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Identity, PatIdentity, get_identity, require_permission
from app.db import get_db
from app.models.asset import Asset
from app.models.schema import Schema
from app.models.transfer_job import TransferJob
from app.models.workspace import Workspace
from app.schemas.transfer import TransferJobOut, TransferRequest
from app.services.permissions import resolve_permission
from app.services.workspace_transfer import run_transfer

router = APIRouter(prefix="/v1/transfers", tags=["transfers"])


@router.get("", response_model=list[TransferJobOut])
def list_transfers(
    workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)
):
    stmt = (
        select(TransferJob)
        .where(TransferJob.workspace_id == workspace_id)
        .order_by(TransferJob.created_at.desc())
    )
    return db.scalars(stmt).all()


@router.get("/{uid}", response_model=TransferJobOut)
def get_transfer(
    uid: str, workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)
):
    job = db.get(TransferJob, uid)
    if job is None or job.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Transfer job not found")
    return job


def _resources_touched(db: Session, body: TransferRequest) -> set[str]:
    resources: set[str] = set()
    if body.asset_uids:
        resources.add("objects")
    if body.document_uids:
        resources.add("documents")
    if body.issue_uids:
        resources.add("tickets")
    for uid in body.type_uids:
        schema = db.get(Schema, uid)
        if schema is None:
            continue
        applies_to = schema.applies_to if schema.applies_to in ("objects", "tickets", "documents") else "objects"
        resources.add(applies_to)
    return resources


def _checked(db: Session, identity: Identity, body: TransferRequest, x_workspace_id: Optional[str]) -> str:
    """Everything a transfer must satisfy before it runs, or is previewed: the source workspace."""
    # A PAT is fixed to one workspace by design — it can't authorize a write
    # into a second one, so a transfer needs a real (OIDC) user.
    if isinstance(identity, PatIdentity):
        raise HTTPException(status_code=403, detail="API tokens can't transfer between workspaces")
    if not x_workspace_id:
        raise HTTPException(status_code=400, detail="Missing X-Workspace-Id header")
    workspace_id = x_workspace_id

    if body.target_workspace_id == workspace_id:
        raise HTTPException(status_code=422, detail="Source and target workspace must differ")
    target = db.get(Workspace, body.target_workspace_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target workspace not found")

    from app.catalogue.system import RECORD_TYPES, CatalogueProtected, refuse
    try:
        refuse(db, body.target_workspace_id, "a transfer's target: its models are made through its collections")
        if body.mode != "copy":
            # A record that does not belong in the catalogue (anything but a Vendor or a Product Model) may move
            # out of it; its types, Vendors and Product Models may not.
            strays = (not body.type_uids and not body.document_uids and not body.issue_uids and body.asset_uids
                      and all((a := db.get(Asset, u)) is not None and a.type not in RECORD_TYPES for u in body.asset_uids))
            if not strays:
                refuse(db, workspace_id, "moved out of: copy from it instead, or point units at its models")
    except CatalogueProtected as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc), "code": "catalogue_workspace"})

    resources = _resources_touched(db, body)
    if not resources:
        raise HTTPException(status_code=422, detail="Nothing selected to transfer")

    source_action = "read" if body.mode == "copy" else "modify"
    for resource in resources:
        if not resolve_permission(db, identity.user, workspace_id, source_action, resource):
            raise HTTPException(
                status_code=403, detail=f"Not permitted to {source_action} {resource} in the source workspace"
            )
        if not resolve_permission(db, identity.user, body.target_workspace_id, "create", resource):
            raise HTTPException(
                status_code=403, detail=f"Not permitted to create {resource} in the target workspace"
            )
    return workspace_id


@router.post("/preview")
def preview_transfer(
    body: TransferRequest,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
    x_workspace_id: Optional[str] = Header(default=None, alias="X-Workspace-Id"),
):
    """The reconciliation report of a transfer, before it runs: the records, their floors and plans (files
    present, fit kept), the placements carried or ended, the placements of other records in them, and every
    reference to the records — relations, reference attributes — with whether it still resolves afterwards,
    from the referencing record's workspace. Nothing is changed."""
    from app.services import indoor_transfer
    from app.services.workspace_transfer import _resolve_instances, _resolve_schema_set
    workspace_id = _checked(db, identity, body, x_workspace_id)
    assets = set(body.asset_uids)
    if body.include_instances and body.type_uids:
        schema_uids = _resolve_schema_set(db, workspace_id, body.type_uids, body.include_descendant_types)
        assets |= _resolve_instances(db, workspace_id, schema_uids)[0]
    report = indoor_transfer.preview(db, workspace_id, body.target_workspace_id, body.mode, assets)
    db.rollback()
    return report


@router.post("", response_model=TransferJobOut, status_code=201)
def create_transfer(
    body: TransferRequest,
    background_tasks: BackgroundTasks,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
    x_workspace_id: Optional[str] = Header(default=None, alias="X-Workspace-Id"),
):
    workspace_id = _checked(db, identity, body, x_workspace_id)

    job = TransferJob(
        uid=str(uuid.uuid4()), workspace_id=workspace_id, target_workspace_id=body.target_workspace_id,
        mode=body.mode,
    )
    db.add(job)
    db.commit()

    background_tasks.add_task(
        run_transfer, job.uid, workspace_id, body.target_workspace_id, body.mode,
        body.type_uids, body.include_instances, body.asset_uids, body.document_uids, body.issue_uids,
        body.include_descendant_types, body.force,
    )
    db.refresh(job)
    return job
