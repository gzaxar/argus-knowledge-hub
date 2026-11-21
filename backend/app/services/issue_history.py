"""Recording what changes on a ticket.

Kept out of the router so the same entries are written however a change
arrives — an edit, a drag on the board, a close — rather than only on the
path someone remembered to instrument.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.issue import Issue, IssueHistory

# Changes worth a line in the history. Description and attributes are
# deliberately absent: a diff of prose or of a JSON blob is noise in a
# timeline, and the current value is always on the ticket.
TRACKED_FIELDS = ("title", "state", "priority", "assignee", "asset_uid", "schema_uid", "service_uid",
                  "assigned_group_uid")

FIELD_LABELS = {
    "title": "Title",
    "state": "Status",
    "priority": "Priority",
    "assignee": "Assignee",
    "asset_uid": "Linked object",
    "schema_uid": "Type",
    "service_uid": "Service",
    "assigned_group_uid": "Team",
}


def _text(value) -> Optional[str]:
    if value is None or value == "":
        return None
    return str(value)


def record_issue_changes(
    db: Session, issue: Issue, before: dict, author: Optional[str]
) -> int:
    """One entry per field that actually changed."""
    added = 0
    now = datetime.now(timezone.utc)
    for field in TRACKED_FIELDS:
        old = before.get(field)
        new = getattr(issue, field, None)
        if old == new:
            continue
        db.add(IssueHistory(
            uid=str(uuid.uuid4()),
            issue_uid=issue.uid,
            type="updated",
            author=author or "api",
            field=FIELD_LABELS.get(field, field),
            from_value=_text(old),
            to_value=_text(new),
            timestamp=now,
        ))
        added += 1
    return added


def record_issue_created(db: Session, issue: Issue, author: Optional[str]) -> None:
    db.add(IssueHistory(
        uid=str(uuid.uuid4()),
        issue_uid=issue.uid,
        type="created",
        author=author or "api",
        details="Ticket created",
        timestamp=datetime.now(timezone.utc),
    ))
