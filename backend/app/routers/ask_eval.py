"""Administration › Ask evaluation: the model server, runs per release, a run's report and its drill-down, starting
a run, and uploading a CI job's report. Installation administrators only (docs/ask-eval.md)."""
from __future__ import annotations

import os
from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ask_eval import report as rpt
from app.ask_eval import service
from app.auth import OidcIdentity, get_identity
from app.db import get_db
from app.models.ask_eval import AskEvalRun

router = APIRouter(prefix="/v1/admin/ask-eval", tags=["ask-eval"])


def require_admin(identity=Depends(get_identity)) -> OidcIdentity:
    if not isinstance(identity, OidcIdentity) or not identity.user.is_admin:
        raise HTTPException(status_code=403, detail="The Ask evaluation is for installation administrators")
    return identity


def _actor(identity: OidcIdentity) -> str:
    return identity.user.email or identity.user.id


def _release() -> str:
    return os.environ.get("ARGUS_VERSION") or "dev"


class SettingsIn(BaseModel):
    base_url: Optional[str] = Field(default=None, max_length=500)
    api_key: Optional[str] = Field(default=None, max_length=2000)      # write-only
    clear_api_key: bool = False
    models: Optional[list[str]] = None
    release_model: Optional[str] = None
    embedding_model: Optional[str] = None
    rerank_model: Optional[str] = None
    judge_model: Optional[str] = None
    judge_base_url: Optional[str] = Field(default=None, max_length=500)
    judge_api_key: Optional[str] = Field(default=None, max_length=2000)
    clear_judge_api_key: bool = False
    approved_hosts: Optional[list[str]] = None
    repeats: Optional[int] = Field(default=None, ge=1, le=10)
    case_timeout_s: Optional[int] = Field(default=None, ge=10, le=3600)
    max_output_tokens: Optional[int] = Field(default=None, ge=64, le=65536)


@router.get("/settings")
def get_settings(_=Depends(require_admin), db: Session = Depends(get_db)):
    row = service.settings(db)
    db.commit()
    return service.settings_out(row)


@router.put("/settings")
def put_settings(body: SettingsIn, identity=Depends(require_admin), db: Session = Depends(get_db)):
    """Save the model server. The keys are encrypted and never returned; leave them out to keep the saved ones."""
    values = body.model_dump(exclude_unset=True)
    for k in ("base_url", "judge_base_url"):
        if values.get(k) and not str(values[k]).startswith(("https://", "http://")):
            raise HTTPException(status_code=422, detail=f"{k} is an http(s) URL")
    if "models" in values:
        values["models"] = [m.strip() for m in values["models"] or [] if m and m.strip()]
    row = service.save_settings(db, values, _actor(identity))
    db.commit()
    return service.settings_out(row)


@router.get("/releases")
def list_releases(_=Depends(require_admin), db: Session = Depends(get_db)):
    """Each release with its latest release-quality run and benchmark, or "not run"."""
    return {"current": _release(), "releases": service.releases(db, _release())}


@router.get("/runs")
def list_runs(release: Optional[str] = None, _=Depends(require_admin), db: Session = Depends(get_db)):
    q = select(AskEvalRun).order_by(AskEvalRun.created_at.desc()).limit(200)
    if release:
        q = q.where(AskEvalRun.release == release)
    return [service.run_out(r) for r in db.scalars(q)]


class StartIn(BaseModel):
    kind: Literal["release", "benchmark", "simulated"]
    models: list[str] = Field(default_factory=list)
    repeats: Optional[int] = Field(default=None, ge=1, le=10)
    cases: Optional[list[str]] = None


@router.post("/runs", status_code=202)
def start_run(body: StartIn, identity=Depends(require_admin), db: Session = Depends(get_db)):
    """Start a run in the background, against the evaluation's own database. Its progress is on the run."""
    try:
        run = service.start(db, kind=body.kind, models=body.models, repeats=body.repeats, cases=body.cases,
                            actor=_actor(identity), release=_release())
    except service.ServiceError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return service.run_out(run)


@router.post("/runs/upload", status_code=201)
def upload(report: dict = Body(...), identity=Depends(require_admin), db: Session = Depends(get_db)):
    """A report made elsewhere (a CI job that can reach the model server), stored sealed under its run id."""
    try:
        run = service.store(db, report, source="upload", requested_by=_actor(identity))
    except (service.ServiceError, KeyError, TypeError) as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    return service.run_out(run)


def _run(db: Session, run_id: str) -> AskEvalRun:
    run = db.get(AskEvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No such run")
    return run


@router.get("/runs/{run_id}")
def get_run(run_id: str, _=Depends(require_admin), db: Session = Depends(get_db)):
    """The run with its whole report: questions, answers, lookups and every grade with its reason."""
    return service.run_out(_run(db, run_id), full=True)


@router.get("/runs/{run_id}/report.{fmt}")
def download(run_id: str, fmt: Literal["json", "md", "html"], public: bool = False, _=Depends(require_admin),
             db: Session = Depends(get_db)):
    run = _run(db, run_id)
    if not run.report:
        raise HTTPException(status_code=409, detail=f"the run is {run.status}: no report yet")
    report = rpt.public(run.report) if public else run.report
    name = f"ask-eval-{run.release}-{run.id}{'-public' if public else ''}.{fmt}"
    headers = {"Content-Disposition": f'attachment; filename="{name}"',
               "X-Report-SHA256": (run.public_sha256 if public else run.report_sha256) or ""}
    if fmt == "json":
        text, _sha = rpt.seal(report)
        return PlainTextResponse(text, media_type="application/json", headers=headers)
    if fmt == "md":
        return PlainTextResponse(rpt.markdown(report), media_type="text/markdown", headers=headers)
    return HTMLResponse(rpt.html_page(report), headers={**headers, "Content-Security-Policy": "default-src 'none'; "
                                                                                              "style-src 'unsafe-inline'"})


@router.get("/feedback-drafts.yaml")
def feedback_drafts(since: Optional[str] = None, workspace: Optional[str] = None, _=Depends(require_admin),
                    db: Session = Depends(get_db)):
    """Every answer rated down, as draft evaluation cases to review (app/ask_eval/feedback_drafts.py). They come
    from real workspaces: a draft is rewritten onto a synthetic fixture before it becomes a case."""
    from datetime import datetime
    from app.ask_eval import feedback_drafts as fd
    try:
        when = datetime.fromisoformat(since) if since else None
    except ValueError:
        raise HTTPException(status_code=422, detail="since is a date, YYYY-MM-DD")
    text_, count = fd.export(db, since=when, workspace=workspace)
    return PlainTextResponse(text_, media_type="application/yaml", headers={
        "Content-Disposition": 'attachment; filename="ask-feedback-drafts.yaml"', "X-Drafts": str(count)})


@router.get("/dataset")
def dataset_summary(_=Depends(require_admin)):
    from app.ask_eval import dataset
    ds = dataset.load()
    return JSONResponse({"version": ds.version, "sha256": ds.sha256, "fixtures": ds.fixture_sha256,
                         "cases": [{"id": c.id, "language": c.language, "domain": c.domain, "severity": c.severity,
                                    "tags": c.tags, "role": c.role, "fixture": c.fixture} for c in ds.cases],
                         "labels": {"reviewed": sum(1 for lb in ds.human_labels if lb.get("status") == "reviewed"),
                                    "draft": sum(1 for lb in ds.human_labels if lb.get("status") != "reviewed")}})
