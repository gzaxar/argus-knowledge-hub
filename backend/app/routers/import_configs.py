import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import OidcIdentity, get_identity, require_permission
from app.db import get_db
from app.models.import_config import ImportConfig
from app.schemas.import_config import ImportConfigCreate, ImportConfigOut, ImportConfigUpdate
from app.services import import_schedule
from app.services.crypto import encrypt_secret

# Sources that can read something without a credential.
PUBLIC_CAPABLE_SOURCES = {"git", "epik8s", "dokuwiki"}


def _schedule(config: ImportConfig, schedule, identity) -> None:
    """A schedule given with a saved import: it runs as the person who set it."""
    if schedule is None:
        return
    try:
        import_schedule.apply(config, schedule, identity.user.id if isinstance(identity, OidcIdentity) else None)
    except import_schedule.ScheduleError as e:
        raise HTTPException(status_code=422, detail=str(e))

router = APIRouter(prefix="/v1/import-configs", tags=["import-configs"])


@router.get("", response_model=list[ImportConfigOut])
def list_configs(
    workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)
):
    return db.scalars(
        select(ImportConfig).where(ImportConfig.workspace_id == workspace_id)
    ).all()


def _get_owned_config(uid: str, workspace_id: str, db: Session) -> ImportConfig:
    config = db.get(ImportConfig, uid)
    if config is None or config.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Import configuration not found")
    return config


@router.get("/{uid}", response_model=ImportConfigOut)
def get_config(
    uid: str, workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)
):
    return _get_owned_config(uid, workspace_id, db)


@router.post("", response_model=ImportConfigOut, status_code=201)
def create_config(
    body: ImportConfigCreate,
    workspace_id: str = Depends(require_permission("create")),
    identity=Depends(get_identity),
    db: Session = Depends(get_db),
):
    # Jira and Confluence have nothing to read without a credential. A
    # repository often does: these beamline configurations are public, and
    # requiring a token for them means inventing one to get past a form.
    if not body.config.pat and body.config.source not in PUBLIC_CAPABLE_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=f"A personal access token is required for a {body.config.source} import.",
        )
    params = body.config.model_dump(exclude={"pat", "source"})
    config = ImportConfig(
        uid=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name=body.name,
        source=body.config.source,
        merge_strategy=body.merge_strategy,
        params=params,
        encrypted_secret=encrypt_secret(body.config.pat) if body.config.pat else None,
    )
    _schedule(config, body.schedule, identity)
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


@router.put("/{uid}", response_model=ImportConfigOut)
def update_config(
    uid: str,
    body: ImportConfigUpdate,
    workspace_id: str = Depends(require_permission("modify")),
    identity=Depends(get_identity),
    db: Session = Depends(get_db),
):
    config = _get_owned_config(uid, workspace_id, db)
    if body.name is not None:
        config.name = body.name
    if body.merge_strategy is not None:
        config.merge_strategy = body.merge_strategy
    if body.config is not None:
        if body.config.source != config.source:
            raise HTTPException(status_code=422, detail="Cannot change an import config's source")
        params = body.config.model_dump(exclude={"pat", "source"})
        config.params = params
        if body.config.pat:
            config.encrypted_secret = encrypt_secret(body.config.pat)
    _schedule(config, body.schedule, identity)
    db.commit()
    db.refresh(config)
    return config


@router.delete("/{uid}", status_code=204)
def delete_config(
    uid: str, workspace_id: str = Depends(require_permission("delete")), db: Session = Depends(get_db)
):
    config = _get_owned_config(uid, workspace_id, db)
    db.delete(config)
    db.commit()


@router.post("/{uid}/run", response_model=ImportConfigOut, status_code=202)
def run_config(
    uid: str,
    background_tasks: BackgroundTasks,
    workspace_id: str = Depends(require_permission("create")),
    identity=Depends(get_identity),
    db: Session = Depends(get_db),
):
    config = _get_owned_config(uid, workspace_id, db)
    if import_schedule._busy(db, config, import_schedule.now()):
        raise HTTPException(status_code=409, detail="This import is running already")
    import_schedule.start_job(db, config, identity, background_tasks.add_task)
    db.refresh(config)
    return config
