"""Making a ticket, whoever asks: the ticket form (POST /v1/issues) and the service portal both come here, so a
portal request gets exactly the checks and bookkeeping of any other ticket — the migration guard, the occurrence
rule of an incident, the type's field validation, the workflow's first state, the key, the history, the equipment
link and the notifications."""
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.ledger.cutover import assert_writable
from app.ledger.engine import LedgerError
from app.ledger.tickets import OccurrenceRequired, derive_for_ticket, validate_occurrence
from app.models.issue import Issue
from app.models.schema import Schema
from app.services import notify, workflows
from app.services.asset_ticket_links import sync_subject_link
from app.services.attribute_validation import validate_attributes
from app.services.current_user_attrs import stamp_current_user_attributes
from app.services.issue_history import record_issue_created


def guard_ticket_write(db: Session, workspace_id: str, schema_uid: Optional[str], attributes: dict) -> None:
    """No dual write during a ticket domain's migration (§17.2), and an
    operational incident says when it happened (I-TKT-4)."""
    try:
        assert_writable(db, workspace_id, "tickets")
    except LedgerError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc), "invariant": "I-SOR-1"})
    try:
        validate_occurrence(db, schema_uid, attributes or {})
    except OccurrenceRequired as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc), "invariant": exc.code})


def create_ticket(db: Session, workspace_id: str, fields: dict, actor: Optional[str], *,
                  watch_reporter: bool = True) -> Issue:
    """A new ticket in `workspace_id`, flushed, not committed. `fields` are IssueCreate's.

    `watch_reporter=False` for a portal request: its requester hears about it through the portal's own,
    requester-safe notifications, never as a watcher who would be told about internal comments."""
    guard_ticket_write(db, workspace_id, fields.get("schema_uid"), fields.get("attributes") or {})
    schema = db.get(Schema, fields["schema_uid"]) if fields.get("schema_uid") else None
    fields["attributes"] = dict(fields.get("attributes") or {})
    stamp_current_user_attributes(db, schema, fields["attributes"], actor)
    validate_attributes(db, schema, fields["attributes"], workspace_id, Issue)
    issue = Issue(workspace_id=workspace_id, **fields)
    wf = workflows.workflow_for(db, workspace_id, issue.schema_uid)
    if workflows.state_of(wf, issue.state) is None:
        # A new ticket starts where its type's workflow starts.
        issue.state = wf["initial"]
    issue.attributes = {**(issue.attributes or {}), "argus_state_entered_at": workflows.now().isoformat()}
    db.add(issue)
    db.flush()
    record_issue_created(db, issue, actor)
    notify.on_created(db, issue, actor, watch_reporter=watch_reporter)
    notify.announce(db, issue.workspace_id, "tickets", "new_ticket", f"New ticket: {issue.title}", actor,
                    issue.uid, issue=issue)
    # A ticket raised on an object has to appear on that object, or the
    # link only exists in one direction.
    if issue.asset_uid:
        sync_subject_link(db, issue, None)
    derive_for_ticket(db, issue)
    return issue
