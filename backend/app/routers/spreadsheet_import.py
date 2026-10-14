"""Records from a CSV or Excel file (services/spreadsheet_import.py): analyse, preview, import.

The file is sent with every step and the plan comes back from the client: nothing is kept between the
steps but the import job.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import PatIdentity, get_grants, get_identity, require_permission
from app.db import get_db
from app.models.import_job import ImportJob
from app.routers.ledger import actor_of
from app.services import spreadsheet_import as svc

router = APIRouter(prefix="/v1/spreadsheet-imports", tags=["imports"])

PREVIEW_ROWS = 200


async def _table(file: UploadFile, sheet: Optional[str]) -> tuple[svc.Table, bytes]:
    content = await file.read()
    try:
        return svc.read_table(file.filename or "upload.csv", content, sheet or None), content
    except svc.SpreadsheetError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc), "code": "spreadsheet"})


def _json(text: Optional[str], what: str) -> Optional[dict]:
    if not text:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        raise HTTPException(status_code=422, detail={"error": f"The {what} is not valid JSON.", "code": "spreadsheet"})
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail={"error": f"The {what} must be an object.", "code": "spreadsheet"})
    return value


def _may(db: Session, identity, workspace_id: str, action: str) -> bool:
    from app.services.permissions import resolve_permission
    if isinstance(identity, PatIdentity):
        return identity.may(action, "objects")
    if identity.token is not None and not identity.token.may(action, "objects"):
        return False
    return resolve_permission(db, identity.user, workspace_id, action, "objects")


def _refused(db: Session, exc: Exception):
    db.rollback()
    raise HTTPException(status_code=422, detail={"error": str(exc), "code": "spreadsheet"})


@router.post("/analyse")
async def analyse(file: UploadFile = File(...), sheet: Optional[str] = Form(None), use_ai: bool = Form(True),
                  target: Optional[str] = Form(None, description="JSON: {mode: existing, schema_uid} or "
                                                                  "{mode: new, name, parent_uid}"),
                  identity=Depends(get_identity), workspace_id: str = Depends(require_permission("create")),
                  db: Session = Depends(get_db)):
    """The sheet's columns, the existing types that fit them best, and a plan: which type the rows become
    (an existing one, or a new one under a type of the workspace) and where each column goes. Rules first,
    the AI for the rest when the workspace has one and `use_ai`. Given a `target`, only the columns are
    proposed."""
    table, _ = await _table(file, sheet)
    try:
        out = svc.analyse(db, workspace_id, actor_of(identity), table, _json(target, "target"), use_ai)
    except svc.SpreadsheetError as exc:
        _refused(db, exc)
    db.commit()                                     # the AI's run, recorded for audit
    return out


@router.post("/preview")
async def preview(file: UploadFile = File(...), sheet: Optional[str] = Form(None), plan: str = Form(...),
                  identity=Depends(get_identity), workspace_id: str = Depends(require_permission("create")),
                  grants=Depends(get_grants), db: Session = Depends(get_db)):
    """What the import would do, row by row — created, updated, unchanged, or why not — checked as a record
    is on save. The first rows, and every row with a problem. Nothing is written."""
    table, _ = await _table(file, sheet)
    try:
        out = svc.plan_rows(db, workspace_id, table, _json(plan, "plan"),
                            may_update=_may(db, identity, workspace_id, "modify"), grants=grants)
    except svc.SpreadsheetError as exc:
        _refused(db, exc)
    db.rollback()
    rows = out.pop("rows")
    out["rows"] = rows[:PREVIEW_ROWS] + [r for r in rows[PREVIEW_ROWS:] if r["action"] == "error"][:500]
    out["total_rows"] = len(rows)
    return out


@router.post("/run", status_code=202)
async def run(background: BackgroundTasks, file: UploadFile = File(...), sheet: Optional[str] = Form(None),
              plan: str = Form(...), expect_digest: Optional[str] = Form(None),
              identity=Depends(get_identity), workspace_id: str = Depends(require_permission("create")),
              grants=Depends(get_grants), db: Session = Depends(get_db)):
    """The import: the new type or properties now, the rows in the background (an import job, read at
    `GET /v1/imports/{uid}`). `expect_digest` is the file's digest from the preview: another file is refused."""
    table, content = await _table(file, sheet)
    if expect_digest and expect_digest != table.digest:
        raise HTTPException(status_code=409, detail={"error": "The file is not the one previewed.",
                                                     "code": "spreadsheet"})
    the_plan = _json(plan, "plan")
    may_update = _may(db, identity, workspace_id, "modify")
    try:
        schema, added = svc.create_type(db, workspace_id, the_plan, table, grants)
    except svc.SpreadsheetError as exc:
        _refused(db, exc)
    job = ImportJob(uid=str(uuid.uuid4()), workspace_id=workspace_id, source="spreadsheet", status="pending",
                    progress=f"0 of {len(table.rows)} rows",
                    counts={"type": schema.name, "type_uid": schema.uid, "new_properties": added},
                    warnings=[], created_at=datetime.now(timezone.utc))
    db.add(job)
    db.commit()
    background.add_task(svc.run_job, job.uid, workspace_id, actor_of(identity), table.filename, content,
                        table.sheet, the_plan, schema.uid, may_update, grants)
    return {"job_uid": job.uid, "type_uid": schema.uid, "type": schema.name, "new_properties": added,
            "rows": len(table.rows)}
