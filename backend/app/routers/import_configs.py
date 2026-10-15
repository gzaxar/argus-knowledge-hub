import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_identity, require_permission
from app.db import get_db
from app.models.import_config import ImportConfig
from app.models.import_job import ImportJob
from app.schemas.import_config import ImportConfigCreate, ImportConfigOut, ImportConfigUpdate
from app.services.crypto import decrypt_secret, encrypt_secret
from app.services.git_import import run_git_import
from app.services.jira_import import run_jira_import
from app.services.jira_issue_import import run_jira_issue_import
from app.services.confluence_import import run_confluence_import
from app.services.epik8s_import import run_epik8s_import

# Sources that can read something without a credential.
PUBLIC_CAPABLE_SOURCES = {"git", "epik8s"}

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
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


@router.put("/{uid}", response_model=ImportConfigOut)
def update_config(
    uid: str,
    body: ImportConfigUpdate,
    workspace_id: str = Depends(require_permission("modify")),
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
    pat = decrypt_secret(config.encrypted_secret) if config.encrypted_secret else None
    if config.source == "epik8s" and config.params.get("it_workspace"):
        from app.routers.imports import check_it_workspace
        check_it_workspace(db, identity, config.params["it_workspace"])
    from app.routers.imports import actor_name

    job = ImportJob(uid=str(uuid.uuid4()), workspace_id=workspace_id, source=config.source)
    db.add(job)
    config.last_run_at = datetime.now(timezone.utc)
    config.last_import_job_uid = job.uid
    db.commit()
    db.refresh(config)

    if config.source == "jira":
        background_tasks.add_task(
            run_jira_import,
            job.uid,
            workspace_id,
            config.params["base_url"],
            pat,
            config.params["jira_schema_id"],
            config.merge_strategy,
        )
    elif config.source == "jira-issues":
        background_tasks.add_task(
            run_jira_issue_import,
            job.uid,
            workspace_id,
            config.params["base_url"],
            pat,
            config.params["jql"],
            config.merge_strategy,
            config.params.get("schema_uid"),
            config.params.get("link_assets", True),
        )
    elif config.source == "confluence":
        background_tasks.add_task(
            run_confluence_import,
            job.uid,
            workspace_id,
            config.params.get("base_url"),
            pat,
            config.params.get("space_key"),
            config.params.get("cql"),
            config.merge_strategy,
            config.params.get("link_assets", True),
            config.params.get("page_url"),
            config.params.get("include_children", True),
        )
    elif config.source == "epik8s":
        background_tasks.add_task(
            run_epik8s_import,
            job.uid,
            workspace_id,
            config.params["provider"],
            config.params["repo_url"],
            pat,
            config.params.get("branch", "main"),
            config.params.get("path", "deploy/values.yaml"),
            config.merge_strategy,
            config.params.get("create_missing_nodes", True),
            config.params.get("infer_elements", False),
            config.params.get("it_workspace"),
            config.params.get("infer_controllers", False),
            config.params.get("link_inventory", False),
            config.params.get("ai_unrecognised", False),
            actor_name(identity),
        )
    else:
        background_tasks.add_task(
            run_git_import,
            job.uid,
            workspace_id,
            config.params["provider"],
            config.params["repo_url"],
            pat,
            config.params.get("branch", "main"),
            config.merge_strategy,
        )

    return config
