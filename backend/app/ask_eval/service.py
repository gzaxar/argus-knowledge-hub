"""Evaluation runs as ARGUS keeps them: the settings an administrator saves, a run started from Administration,
a report uploaded from a CI job, and the history per release.

A run started here does not touch this installation's data: it runs as a separate process (``python -m
app.ask_eval run``) against the evaluation's own database, ``ASK_EVAL_DATABASE_URL``, which the operator provides.
Without it, starting a run is refused. The process gets the model server's key in its environment only; the key is
read from the encrypted settings, never written anywhere else, and taken out of anything the process prints.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ask_eval import report as rpt
from app.ask_eval.runner import EvalConfig
from app.models.ask_eval import AskEvalRun, AskEvalSettings

KINDS = ("release", "benchmark", "configurations", "simulated")


class ServiceError(Exception):
    pass


def settings(db: Session) -> AskEvalSettings:
    row = db.get(AskEvalSettings, 1)
    if row is None:
        row = AskEvalSettings(id=1, models=[], approved_hosts=[])
        db.add(row)
        db.flush()
    return row


def settings_out(row: AskEvalSettings) -> dict:
    return {"base_url": row.base_url, "api_key_set": bool(row.encrypted_key), "models": row.models or [],
            "release_model": row.release_model, "embedding_model": row.embedding_model,
            "rerank_model": row.rerank_model, "judge_model": row.judge_model, "judge_base_url": row.judge_base_url,
            "judge_api_key_set": bool(row.encrypted_judge_key), "approved_hosts": row.approved_hosts or [],
            "repeats": row.repeats, "case_timeout_s": row.case_timeout_s,
            "max_output_tokens": row.max_output_tokens, "updated_by": row.updated_by,
            "updated_at": row.updated_at, "database_configured": bool(os.environ.get("ASK_EVAL_DATABASE_URL"))}


def save_settings(db: Session, values: dict, actor: str) -> AskEvalSettings:
    from app.services.crypto import encrypt_secret
    row = settings(db)
    for k in ("base_url", "models", "release_model", "embedding_model", "rerank_model", "judge_model",
              "judge_base_url", "approved_hosts", "repeats", "case_timeout_s", "max_output_tokens"):
        if k in values:
            setattr(row, k, values[k])
    if values.get("api_key"):
        row.encrypted_key = encrypt_secret(values["api_key"])
    if values.get("clear_api_key"):
        row.encrypted_key = None
    if values.get("judge_api_key"):
        row.encrypted_judge_key = encrypt_secret(values["judge_api_key"])
    if values.get("clear_judge_api_key"):
        row.encrypted_judge_key = None
    row.updated_by, row.updated_at = actor, datetime.now(timezone.utc)
    db.flush()
    return row


def config_env(row: AskEvalSettings, models: list[str], repeats: Optional[int]) -> dict:
    """The child process's ASK_EVAL_* environment from the saved settings (keys decrypted here, in memory)."""
    from app.services.crypto import decrypt_secret
    env = {"ASK_EVAL_API_BASE_URL": row.base_url or "", "ASK_EVAL_MODELS": ",".join(models),
           "ASK_EVAL_REPEATS": str(repeats or row.repeats or 1), "ASK_EVAL_CASE_TIMEOUT": str(row.case_timeout_s or 300),
           "ASK_EVAL_APPROVED_HOSTS": ",".join(row.approved_hosts or [])}
    for k, v in (("ASK_EVAL_EMBEDDING_MODEL", row.embedding_model), ("ASK_EVAL_RERANK_MODEL", row.rerank_model),
                 ("ASK_EVAL_JUDGE_MODEL", row.judge_model), ("ASK_EVAL_JUDGE_BASE_URL", row.judge_base_url),
                 ("ASK_EVAL_MAX_OUTPUT_TOKENS", str(row.max_output_tokens) if row.max_output_tokens else None)):
        if v:
            env[k] = v
    if row.encrypted_key:
        env["ASK_EVAL_API_KEY"] = decrypt_secret(row.encrypted_key)
    if row.encrypted_judge_key:
        env["ASK_EVAL_JUDGE_API_KEY"] = decrypt_secret(row.encrypted_judge_key)
    return env


# --------------------------------------------------------------------------- storing reports

def store(db: Session, report: dict, *, source: str, requested_by: Optional[str]) -> AskEvalRun:
    """A finished report, sealed: its SHA-256 over the canonical JSON, and the public version's. A run id is
    stored once; a second report under the same id is refused."""
    m = report.get("manifest") or {}
    if m.get("schema") != rpt.SCHEMA:
        raise ServiceError(f"not an Ask evaluation report ({rpt.SCHEMA})")
    run = db.get(AskEvalRun, m["run_id"])
    if run is not None and run.report_sha256:
        raise ServiceError(f"run {m['run_id']} has its report already: reports are never replaced")
    _, sha = rpt.seal(report)
    _, public_sha = rpt.seal(rpt.public(report))
    if run is None:
        run = AskEvalRun(id=m["run_id"], kind=m["kind"], release=m["release"], source=source,
                         requested_by=requested_by, created_at=datetime.now(timezone.utc))
        db.add(run)
    run.commit = (m.get("argus") or {}).get("commit")
    run.models = [row["model"] for row in report.get("table") or []]
    run.summary = report.get("table")
    run.status = "finished" if m.get("complete") else "incomplete"
    run.started_at = _time(m.get("started_at"))
    run.finished_at = _time(m.get("finished_at"))
    run.report, run.report_sha256, run.public_sha256 = report, sha, public_sha
    db.flush()
    return run


def _time(v: Optional[str]):
    try:
        return datetime.fromisoformat(v) if v else None
    except ValueError:
        return None


def run_out(run: AskEvalRun, full: bool = False) -> dict:
    out = {"id": run.id, "kind": run.kind, "release": run.release, "commit": run.commit, "status": run.status,
           "source": run.source, "requested_by": run.requested_by, "models": run.models, "progress": run.progress,
           "summary": run.summary, "report_sha256": run.report_sha256, "public_sha256": run.public_sha256,
           "error": run.error, "created_at": run.created_at, "started_at": run.started_at,
           "finished_at": run.finished_at}
    if full:
        out["report"] = run.report
    return out


def releases(db: Session, current: str) -> list[dict]:
    """Each release with its latest release-quality run and latest benchmark — or "not run". A release never shows
    another release's run."""
    runs = list(db.scalars(select(AskEvalRun).order_by(AskEvalRun.created_at.desc())))
    names = list(dict.fromkeys([current] + [r.release for r in runs]))
    out = []
    for name in names:
        mine = [r for r in runs if r.release == name]
        row = {"release": name, "current": name == current}
        for kind, key in (("release", "release_quality"), ("benchmark", "benchmark")):
            latest = next((r for r in mine if r.kind == kind), None)
            row[key] = run_out(latest) if latest else {"status": "not run"}
        row["runs"] = len(mine)
        out.append(row)
    return out


# --------------------------------------------------------------------------- starting a run here

_lock = threading.Lock()


def start(db: Session, *, kind: str, models: list[str], repeats: Optional[int], cases: Optional[list[str]],
          actor: str, release: str) -> AskEvalRun:
    """A run, started in the background against the evaluation database. One at a time."""
    if kind not in KINDS:
        raise ServiceError(f"kind is one of {', '.join(KINDS)}")
    scratch = os.environ.get("ASK_EVAL_DATABASE_URL")
    if not scratch:
        raise ServiceError("no evaluation database: set ASK_EVAL_DATABASE_URL (docs/ask-eval.md). A run never "
                           "uses this installation's own database.")
    if scratch == os.environ.get("DATABASE_URL"):
        raise ServiceError("ASK_EVAL_DATABASE_URL is this installation's own database: give the evaluation its own")
    row = settings(db)
    if kind != "simulated":
        if not row.base_url:
            raise ServiceError("set the model server first")
        if kind == "release":
            models = [row.release_model or (row.models or [None])[0]]
        allowed = set(row.models or []) | ({row.release_model} if row.release_model else set())
        unknown = [m for m in models if m not in allowed]
        if unknown or not models or None in models:
            raise ServiceError("models must be among the approved ones: " + ", ".join(sorted(allowed)))
        if kind == "benchmark" and len(models) < 2:
            raise ServiceError("a benchmark compares two models at least")
    busy = db.scalar(select(AskEvalRun).where(AskEvalRun.status.in_(("queued", "running")),
                                              AskEvalRun.source == "server"))
    if busy is not None:
        raise ServiceError(f"run {busy.id} is still going: one evaluation at a time")
    run = AskEvalRun(id=uuid.uuid4().hex[:10], kind=kind, release=release, source="server", requested_by=actor,
                     models=models if kind != "simulated" else ["standin:reference", "standin:careless"],
                     status="queued", progress={"done": 0, "total": None})
    db.add(run)
    db.commit()
    env = {**os.environ, "DATABASE_URL": scratch,
           **(config_env(row, models, repeats) if kind != "simulated" else {})}
    for k in ("ASK_EVAL_DATABASE_URL",):
        env.pop(k, None)
    threading.Thread(target=_child, args=(run.id, kind, cases, env), daemon=True,
                     name=f"ask-eval-{run.id}").start()
    return run


def _child(run_id: str, kind: str, cases: Optional[list[str]], env: dict) -> None:
    """The run's process; its progress and report copied into this installation's database."""
    from app.db import SessionLocal
    out = Path(tempfile.mkdtemp(prefix=f"ask-eval-{run_id}-"))
    progress = out / "progress.jsonl"
    cmd = [sys.executable, "-m", "app.ask_eval", "run", "--kind", kind, "--run-id", run_id, "--out", str(out),
           "--progress-file", str(progress), "--migrate"]
    if cases:
        cmd += ["--cases", ",".join(cases)]
    secrets = [v for k, v in env.items() if k.endswith("_API_KEY") and v]

    def scrub(text: str) -> str:
        for s in secrets:
            text = text.replace(s, "[key]")
        return text

    def update(**values):
        db = SessionLocal()
        try:
            run = db.get(AskEvalRun, run_id)
            for k, v in values.items():
                setattr(run, k, v)
            db.commit()
        finally:
            db.close()

    with _lock:
        update(status="running", started_at=datetime.now(timezone.utc))
        proc = subprocess.Popen(cmd, env=env, cwd=str(Path(__file__).resolve().parents[2]),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        tail: list[str] = []
        for line in proc.stdout:  # type: ignore[union-attr]
            tail = (tail + [scrub(line.rstrip())])[-40:]
            if progress.exists():
                try:
                    last = progress.read_text().strip().splitlines()[-1]
                    update(progress=json.loads(last))
                except (IndexError, ValueError, OSError):
                    pass
        code = proc.wait()
        report_file = out / "report.json"
        if code == 0 and report_file.exists():
            db = SessionLocal()
            try:
                store(db, json.loads(report_file.read_text()), source="server", requested_by=None)
                db.commit()
            except Exception as e:  # noqa: BLE001
                db.rollback()
                update(status="failed", error=scrub(f"the report could not be stored: {e}"),
                       finished_at=datetime.now(timezone.utc))
            finally:
                db.close()
        else:
            update(status="failed", error="\n".join(tail)[-4000:], finished_at=datetime.now(timezone.utc))
