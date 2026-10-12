"""Ticket workflows (asset-model-revision §19 item 3).

A ticket type names its workflow (`schema.metadata.workflow_uid`, inherited
down the type tree); otherwise the workspace's default workflow applies,
and without one the built-in workflow — the five states ARGUS always had,
with every move allowed — keeps existing tickets working unchanged.

A transition may require an assignee, a resolution or a comment. Moving
into a `done` state closes the ticket; leaving it reopens it. Every move is
recorded in the ticket's history and the time it entered its state is kept,
which is what escalation timers measure from.

Jira workflows are imported as they are (statuses with their category,
transitions by name), and **rehearsed**: every status change in the
migrated tickets' Jira history must map to a state and be an allowed
transition, or the rehearsal lists it.
"""
from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.issue import Issue, IssueComment, IssueHistory
from app.models.schema import Schema
from app.models.workflow import Workflow

CATEGORIES = ("open", "active", "waiting", "done")
REQUIREMENTS = ("assignee", "resolution", "comment")
JIRA_CATEGORY = {"new": "open", "indeterminate": "active", "done": "done"}


class WorkflowError(ValueError):
    code = "workflow"


def _builtin() -> dict:
    """The workflow of a type with none of its own: the core-facility package's default."""
    from app.packages import defaults
    return defaults.default_workflow()


BUILTIN = _builtin()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_") or "state"


def now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- definitions

def as_dict(wf: Optional[Workflow]) -> dict:
    if wf is None:
        return BUILTIN
    return {"uid": wf.uid, "name": wf.name, "initial": wf.initial, "is_default": wf.is_default,
            "states": wf.states, "transitions": wf.transitions, "source": wf.source, "version": wf.version}


def validate(definition: dict) -> None:
    states = definition.get("states") or []
    keys = [s.get("key") for s in states]
    problems = []
    if not states:
        problems.append("a workflow needs at least one state")
    if len(set(keys)) != len(keys) or not all(keys):
        problems.append("state keys must be present and unique")
    for s in states:
        if s.get("category") not in CATEGORIES:
            problems.append(f"state {s.get('key')}: category must be one of {', '.join(CATEGORIES)}")
        if s.get("sla_hours") is not None and float(s["sla_hours"]) <= 0:
            problems.append(f"state {s.get('key')}: sla_hours must be positive")
    if definition.get("initial") not in keys:
        problems.append("the initial state must be one of the states")
    for t in definition.get("transitions") or []:
        for end in ("from", "to"):
            v = t.get(end)
            if v != "*" and v not in keys:
                problems.append(f"transition {t.get('name')!r}: unknown {end} state {v!r}")
        unknown = set(t.get("requires") or []) - set(REQUIREMENTS)
        if unknown:
            problems.append(f"transition {t.get('name')!r}: unknown requirement(s) {sorted(unknown)}")
    if not any(s.get("category") == "done" for s in states):
        problems.append("a workflow needs a done state")
    if problems:
        raise WorkflowError("; ".join(problems))


def save(db: Session, workspace_id: str, definition: dict, uid: Optional[str] = None) -> Workflow:
    validate(definition)
    wf = db.get(Workflow, uid) if uid else None
    if wf is not None and wf.workspace_id != workspace_id:
        raise WorkflowError("no such workflow in this workspace")
    if wf is None:
        wf = Workflow(uid=uid or str(uuid.uuid4()), workspace_id=workspace_id, created_at=now(), version=0)
        db.add(wf)
    wf.name, wf.states, wf.transitions, wf.initial = (definition["name"], definition["states"],
                                                      definition.get("transitions") or [], definition["initial"])
    wf.source = definition.get("source")
    wf.version, wf.updated_at = (wf.version or 0) + 1, now()
    if definition.get("is_default"):
        for other in db.scalars(select(Workflow).where(Workflow.workspace_id == workspace_id,
                                                       Workflow.uid != wf.uid)):
            other.is_default = False
        wf.is_default = True
    db.flush()
    return wf


def bind(db: Session, workspace_id: str, schema_uid: str, workflow_uid: Optional[str]) -> None:
    """Give a ticket type its workflow (inherited by its subtypes)."""
    schema = db.get(Schema, schema_uid)
    if schema is None or schema.applies_to != "tickets" or schema.workspace_id != workspace_id:
        raise WorkflowError("not a ticket type of this workspace")
    if workflow_uid and (db.get(Workflow, workflow_uid) is None
                         or db.get(Workflow, workflow_uid).workspace_id != workspace_id):
        raise WorkflowError("no such workflow in this workspace")
    meta = dict(schema.metadata_json or {})
    if workflow_uid:
        meta["workflow_uid"] = workflow_uid
    else:
        meta.pop("workflow_uid", None)
    schema.metadata_json = meta
    flag_modified(schema, "metadata_json")
    db.flush()


def workflow_for(db: Session, workspace_id: str, schema_uid: Optional[str]) -> dict:
    seen, uid = set(), schema_uid
    while uid and uid not in seen:
        seen.add(uid)
        schema = db.get(Schema, uid)
        if schema is None:
            break
        wf_uid = (schema.metadata_json or {}).get("workflow_uid")
        if wf_uid and db.get(Workflow, wf_uid) is not None:
            return as_dict(db.get(Workflow, wf_uid))
        uid = schema.parent_schema_uid
    default = db.scalar(select(Workflow).where(Workflow.workspace_id == workspace_id, Workflow.is_default.is_(True)))
    return as_dict(default)


def state_of(wf: dict, key: str) -> Optional[dict]:
    return next((s for s in wf["states"] if s["key"] == key), None)


def transitions_from(wf: dict, state: str) -> list[dict]:
    out = []
    for t in wf["transitions"]:
        if t.get("from") not in ("*", state):
            continue
        targets = [s["key"] for s in wf["states"]] if t.get("to") == "*" else [t["to"]]
        for to in targets:
            if to != state:
                out.append({"to": to, "name": t.get("name") or state_of(wf, to)["name"],
                            "requires": list(t.get("requires") or []), "to_name": state_of(wf, to)["name"],
                            "category": state_of(wf, to)["category"]})
    seen, unique = set(), []
    for t in out:
        if t["to"] not in seen:
            seen.add(t["to"])
            unique.append(t)
    return unique


def check_move(wf: dict, current: str, target: str) -> dict:
    if state_of(wf, target) is None:
        raise WorkflowError(f"{target!r} is not a state of the {wf['name']} workflow")
    for t in transitions_from(wf, current):
        if t["to"] == target:
            return t
    allowed = ", ".join(t["to"] for t in transitions_from(wf, current)) or "none"
    raise WorkflowError(f"{current} → {target} is not allowed by the {wf['name']} workflow (allowed: {allowed})")


def apply_state(issue: Issue, wf: dict, target: str) -> None:
    """Set the state; a done state closes the ticket, leaving one reopens it."""
    issue.state = target
    # The built-in workflow keeps ARGUS's long-standing rule: only Closed closes.
    done = target == "closed" if wf.get("uid") is None else (state_of(wf, target) or {}).get("category") == "done"
    issue.closed_at = (issue.closed_at or now()) if done else None
    attrs = dict(issue.attributes or {})
    attrs["argus_state_entered_at"] = now().isoformat()
    issue.attributes = attrs
    flag_modified(issue, "attributes")


def transition(db: Session, issue: Issue, target: str, actor: Optional[str], *, comment: Optional[str] = None,
               resolution: Optional[str] = None, assignee: Optional[str] = None) -> dict:
    wf = workflow_for(db, issue.workspace_id, issue.schema_uid)
    step = check_move(wf, issue.state, target)
    if assignee:
        issue.assignee = assignee
    if resolution:
        attrs = dict(issue.attributes or {})
        attrs["argus_resolution"] = resolution
        issue.attributes = attrs
    missing = []
    if "assignee" in step["requires"] and not issue.assignee:
        missing.append("an assignee")
    resolved_as = (issue.attributes or {}).get("argus_resolution")
    if "resolution" in step["requires"] and (not resolved_as or resolved_as == "Unresolved"):
        missing.append("a resolution")
    if "comment" in step["requires"] and not (comment or "").strip():
        missing.append("a comment")
    if missing:
        raise WorkflowError(f"{step['name']} needs {', '.join(missing)}")
    before = issue.state
    apply_state(issue, wf, target)
    stamp = now()
    db.add(IssueHistory(uid=str(uuid.uuid4()), issue_uid=issue.uid, type="updated", author=actor or "api",
                        field="Status", from_value=before, to_value=target, details=step["name"], timestamp=stamp))
    if comment and comment.strip():
        db.add(IssueComment(uid=str(uuid.uuid4()), issue_uid=issue.uid, author=actor or "api", body=comment.strip()))
    db.flush()
    return {"from": before, "to": target, "transition": step["name"]}


# --------------------------------------------------------------------------- Jira

def from_jira(definition: dict) -> dict:
    """A Jira workflow export → an ARGUS workflow, plus the status map a
    migration uses. `definition`: {"name", "statuses": [{"name",
    "statusCategory": {"key": "new|indeterminate|done"}}], "transitions":
    [{"name", "from": [status names] or [], "to": status name}]}."""
    states, status_map = [], {}
    for s in definition.get("statuses") or []:
        key = slug(s["name"])
        category = JIRA_CATEGORY.get(((s.get("statusCategory") or {}).get("key") or "indeterminate"), "active")
        states.append({"key": key, "name": s["name"], "category": category})
        status_map[s["name"]] = key
    transitions = []
    for t in definition.get("transitions") or []:
        to = status_map.get(t["to"])
        sources = t.get("from") or ["*"]            # Jira: an empty "from" is a global transition
        for f in sources:
            transitions.append({"from": "*" if f == "*" else status_map.get(f, slug(f)), "to": to,
                                "name": t.get("name") or t["to"]})
    initial = status_map.get(definition.get("initial") or "") or (states[0]["key"] if states else None)
    return {"name": definition.get("name") or "Imported workflow", "states": states, "transitions": transitions,
            "initial": initial, "source": {"system": "jira", "name": definition.get("name"),
                                           "status_map": status_map}}


def rehearse(db: Session, wf_row: Workflow, workspace_id: str) -> dict:
    """Replay every status change in the migrated tickets' Jira history
    against the workflow (§19 item 3: every workflow rehearsed)."""
    wf = as_dict(wf_row)
    status_map = ((wf_row.source or {}).get("status_map")) or {s["name"]: s["key"] for s in wf["states"]}
    schema_uids = [s.uid for s in db.scalars(select(Schema).where(Schema.workspace_id == workspace_id,
                                                                  Schema.applies_to == "tickets"))
                   if workflow_for(db, workspace_id, s.uid).get("uid") == wf_row.uid]
    q = select(Issue).where(Issue.workspace_id == workspace_id, Issue.attributes["argus_source"].astext == "jira")
    tickets = [i for i in db.scalars(q) if i.schema_uid in schema_uids or (wf_row.is_default and not i.schema_uid)]
    unmapped: Counter = Counter()
    disallowed: dict = defaultdict(lambda: {"count": 0, "example": None})
    checked = 0
    for issue in tickets:
        for h in db.scalars(select(IssueHistory).where(IssueHistory.issue_uid == issue.uid,
                                                       IssueHistory.backend_id.isnot(None))
                            .order_by(IssueHistory.timestamp)):
            if (h.field or "").lower() != "status":
                continue
            checked += 1
            src, dst = status_map.get(h.from_value or ""), status_map.get(h.to_value or "")
            for name, key in ((h.from_value, src), (h.to_value, dst)):
                if key is None:
                    unmapped[name] += 1
            if src is None or dst is None:
                continue
            try:
                check_move(wf, src, dst)
            except WorkflowError:
                row = disallowed[(src, dst)]
                row["count"] += 1
                row["example"] = row["example"] or (issue.attributes or {}).get("argus_source_key")
        current = status_map.get((issue.attributes or {}).get("argus_source_status") or "")
        if (issue.attributes or {}).get("argus_source_status") and current is None:
            unmapped[(issue.attributes or {})["argus_source_status"]] += 1
    report = {"workflow": wf_row.uid, "tickets": len(tickets), "transitions_checked": checked,
              "unmapped_statuses": dict(unmapped),
              "disallowed": [{"from": k[0], "to": k[1], **v} for k, v in sorted(disallowed.items())]}
    report["ok"] = not unmapped and not disallowed and checked > 0
    return report
