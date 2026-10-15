import uuid
from typing import Annotated, Union

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import PatIdentity, get_identity, require_permission
from app.db import get_db
from app.models.import_job import ImportJob
from app.schemas.import_job import (
    GitImportRequest,
    ImportJobOut,
    JiraImportRequest,
    JiraIssueImportRequest,
    ConfluenceImportRequest,
    Epik8sImportRequest,
)
from app.services.git_import import run_git_import
from app.services.jira_import import run_jira_import
from app.services.jira_issue_import import run_jira_issue_import
from app.services.confluence_import import run_confluence_import
from app.services.epik8s_import import run_epik8s_import

router = APIRouter(prefix="/v1/imports", tags=["imports"])

ImportRequest = Annotated[
    Union[
        JiraImportRequest, JiraIssueImportRequest, ConfluenceImportRequest,
        Epik8sImportRequest, GitImportRequest,
    ],
    Field(discriminator="source"),
]


@router.get("", response_model=list[ImportJobOut])
def list_imports(
    workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)
):
    stmt = (
        select(ImportJob)
        .where(ImportJob.workspace_id == workspace_id)
        .order_by(ImportJob.created_at.desc())
    )
    return db.scalars(stmt).all()


@router.get("/{uid}", response_model=ImportJobOut)
def get_import(
    uid: str, workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)
):
    job = db.get(ImportJob, uid)
    if job is None or job.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Import job not found")
    return job


def check_it_workspace(db: Session, identity, it_workspace: str) -> None:
    """An EPIK8s import that makes IT objects writes a second workspace: only a signed-in person allowed to
    create there may ask for it."""
    from app.models.workspace import Workspace
    from app.services.permissions import resolve_permission
    if isinstance(identity, PatIdentity):
        raise HTTPException(status_code=403, detail="An API token writes one workspace; making IT objects "
                                                    "in another needs a signed-in person")
    if db.get(Workspace, it_workspace) is None:
        raise HTTPException(status_code=404, detail=f"No workspace {it_workspace}")
    if not resolve_permission(db, identity.user, it_workspace, "create", "objects"):
        raise HTTPException(status_code=403, detail=f"You may not create objects in {it_workspace}")


def actor_name(identity) -> str:
    if isinstance(identity, PatIdentity):
        return f"robot:{identity.name}" if identity.name else "api-token"
    return identity.user.email


@router.post("", response_model=ImportJobOut, status_code=201)
def create_import(
    body: ImportRequest,
    background_tasks: BackgroundTasks,
    workspace_id: str = Depends(require_permission("create")),
    identity=Depends(get_identity),
    db: Session = Depends(get_db),
):
    if isinstance(body, Epik8sImportRequest) and body.it_workspace:
        check_it_workspace(db, identity, body.it_workspace)
    job = ImportJob(uid=str(uuid.uuid4()), workspace_id=workspace_id, source=body.source)
    db.add(job)
    db.commit()

    if isinstance(body, JiraImportRequest):
        background_tasks.add_task(
            run_jira_import,
            job.uid, workspace_id, body.base_url, body.pat, body.jira_schema_id, body.merge_strategy,
        )
    elif isinstance(body, JiraIssueImportRequest):
        background_tasks.add_task(
            run_jira_issue_import,
            job.uid, workspace_id, body.base_url, body.pat, body.jql, body.merge_strategy,
            body.schema_uid, body.link_assets,
        )
    elif isinstance(body, ConfluenceImportRequest):
        background_tasks.add_task(
            run_confluence_import,
            job.uid, workspace_id, body.base_url, body.pat, body.space_key, body.cql,
            body.merge_strategy, body.link_assets, body.page_url, body.include_children,
        )
    elif isinstance(body, Epik8sImportRequest):
        background_tasks.add_task(
            run_epik8s_import,
            job.uid, workspace_id, body.provider, body.repo_url, body.pat, body.branch,
            body.path, body.merge_strategy, body.create_missing_nodes, body.infer_elements,
            body.it_workspace, body.infer_controllers, body.link_inventory, body.ai_unrecognised,
            actor_name(identity),
        )
    else:
        background_tasks.add_task(
            run_git_import,
            job.uid, workspace_id, body.provider, body.repo_url, body.pat, body.branch, body.merge_strategy,
        )

    db.refresh(job)
    return job
