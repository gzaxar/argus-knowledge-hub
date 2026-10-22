"""Ratings of Ask ARGUS's answers, kept anonymously to improve it.

A person rates an answer up or down, and may say what was wrong. The rating is kept apart from them
(models/usage.py AskFeedback): the question, the answer, the workspace it was asked in, the model, the ARGUS
version, the client and the lookups it made (tool and arguments; their results are not copied), never who
asked or their conversation. Their own answer is marked as rated, so it is rated once.

An answer rated down also becomes an "Argus Knowledge" ticket in the installation's own feedback workspace
(ARGUS_FEEDBACK_WORKSPACE, default `argus-knowledge`), assigned to the person who looks after Ask ARGUS
(app setting `ask_feedback.assignee`, else ARGUS_FEEDBACK_ASSIGNEE, default andrea.michelotti@lnf.infn.it).
Nobody else is a member of that workspace: administrators see it, and the assignee.
"""
from __future__ import annotations

import os
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.membership import Membership
from app.models.usage import AskFeedback
from app.models.user import User
from app.models.workspace import Workspace

TICKET_TYPE = "Argus Knowledge"
DEFAULT_WORKSPACE = "argus-knowledge"
DEFAULT_ASSIGNEE = "andrea.michelotti@lnf.infn.it"
SETTING = "ask_feedback"
MAX_TEXT = 20000


def workspace_id() -> str:
    return (os.environ.get("ARGUS_FEEDBACK_WORKSPACE") or DEFAULT_WORKSPACE).strip()


def assignee_email(db: Session) -> Optional[str]:
    from app.models.app_setting import AppSetting
    row = db.get(AppSetting, SETTING)
    configured = (row.value or {}).get("assignee") if row is not None else None
    return (configured or os.environ.get("ARGUS_FEEDBACK_ASSIGNEE") or DEFAULT_ASSIGNEE).strip() or None


def _full_rights(db: Session, ws: str, user_id: str) -> None:
    if db.scalar(select(Membership).where(Membership.workspace_id == ws, Membership.user_id == user_id)):
        return
    db.add(Membership(workspace_id=ws, user_id=user_id, can_read=True, can_create=True, can_modify=True,
                      can_delete=False, can_read_tickets=True, can_create_tickets=True, can_modify_tickets=True,
                      can_delete_tickets=False, can_read_documents=True, can_create_documents=False,
                      can_modify_documents=False, can_delete_documents=False, can_approve_documents=False))
    db.flush()


def ensure_workspace(db: Session) -> tuple[str, str]:
    """The feedback workspace and its ticket type (made the first time): (workspace id, type uid)."""
    from app.routers.workspaces import make_workspace
    from app.services.ticket_types import ensure_ticket_types
    ws = workspace_id()
    workspace = db.get(Workspace, ws)
    if workspace is None:
        workspace = make_workspace(db, ws, "ARGUS Knowledge feedback")
        # Nobody by default: the answers rated carry what their askers could read.
        for flag in ("default_can_read", "default_can_create", "default_can_modify", "default_can_delete",
                     "default_can_read_tickets", "default_can_create_tickets", "default_can_modify_tickets",
                     "default_can_delete_tickets", "default_can_read_documents", "default_can_create_documents",
                     "default_can_modify_documents", "default_can_delete_documents",
                     "default_can_approve_documents"):
            if hasattr(workspace, flag):
                setattr(workspace, flag, False)
        db.flush()
    types = ensure_ticket_types(db, ws, {TICKET_TYPE})
    return ws, types[TICKET_TYPE]


def _quote(text: str) -> str:
    return "\n".join("> " + line for line in (text or "").splitlines()) or "> (empty)"


def _ticket_body(fb: AskFeedback) -> str:
    rows = [("Workspace", f"`{fb.workspace_id}`"), ("Model", fb.model or "—"), ("ARGUS", fb.argus_version or "—"),
            ("Client", fb.client or "—"), ("Ended", fb.stopped or "—"),
            ("Took", f"{fb.seconds:.1f} s" if fb.seconds is not None else "—"),
            ("Lookups", str(len(fb.tools or [])))]
    out = ["An Ask ARGUS answer was rated **not useful**. Who asked is not recorded.", ""]
    if fb.comment:
        out += ["## What was wrong", "", _quote(fb.comment), ""]
    out += ["## Question", "", _quote(fb.question), "", "## Answer", "", _quote(fb.answer), ""]
    if fb.error:
        out += ["## Error", "", f"```\n{fb.error}\n```", ""]
    out += ["## Context", "", "| | |", "|---|---|", *[f"| {k} | {v} |" for k, v in rows], ""]
    if fb.tools:
        out += ["## Lookups", ""]
        for i, t in enumerate(fb.tools, 1):
            args = ", ".join(f"{k}={v!r}" for k, v in (t.get("arguments") or {}).items())
            out.append(f"{i}. `{t.get('tool')}`({args})" + (f" — error: {t['error']}" if t.get("error") else ""))
        out.append("")
    return "\n".join(out)


def _open_ticket(db: Session, fb: AskFeedback) -> str:
    from app.models.issue import Issue
    from app.services import notify, workflows
    from app.services.issue_history import record_issue_created
    ws, type_uid = ensure_workspace(db)
    who = assignee_email(db)
    assignee = db.scalar(select(User).where(User.email == who)) if who else None
    if assignee is not None:
        _full_rights(db, ws, assignee.id)
    question = " ".join((fb.question or "").split())
    issue = Issue(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=type_uid,
                  title=f"Ask ARGUS: {question[:90] + ('…' if len(question) > 90 else '')}" if question
                  else "Ask ARGUS: an answer rated not useful",
                  description=_ticket_body(fb), assignee=assignee.id if assignee else None,
                  labels=["ask-argus", "feedback", f"ws:{fb.workspace_id}"],
                  attributes={"argus_feedback": fb.id, "argus_feedback_workspace": fb.workspace_id})
    wf = workflows.workflow_for(db, ws, type_uid)
    issue.state = wf["initial"]
    issue.attributes = {**issue.attributes, "argus_state_entered_at": workflows.now().isoformat()}
    db.add(issue)
    db.flush()
    record_issue_created(db, issue, None)
    notify.on_created(db, issue, None)
    return issue.uid


def record(db: Session, *, workspace_id: str, rating: str, comment: Optional[str], question: str, answer: str,
           steps: Optional[list], model: Optional[str], client: Optional[str], stopped: Optional[str] = None,
           error: Optional[str] = None, seconds: Optional[float] = None) -> AskFeedback:
    """The rating, kept without its author; a ticket for one rated down. The caller commits."""
    fb = AskFeedback(
        id=str(uuid.uuid4()), workspace_id=workspace_id, rating=rating,
        comment=(comment or "").strip()[:MAX_TEXT] or None, question=(question or "")[:MAX_TEXT],
        answer=(answer or "")[:MAX_TEXT], model=model, argus_version=os.environ.get("ARGUS_VERSION") or "dev",
        client=client,
        tools=[{"tool": s.get("tool"), "arguments": s.get("arguments"), "error": s.get("error"),
                "seconds": s.get("seconds")} for s in (steps or [])],
        stopped=stopped, error=error, seconds=seconds)
    db.add(fb)
    db.flush()
    if rating == "down":
        fb.ticket_uid = _open_ticket(db, fb)
    return fb
