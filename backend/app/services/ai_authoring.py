"""Drafting and reviewing a document, and filling in a ticket.

Three jobs, one principle: the model writes into a form, never into a
record. A draft lands in the editor where somebody edits it before
anything is saved; a review is a list of remarks, not a set of changes;
a ticket's fields arrive as values in the form somebody is already filling
in.

The ARGUS fields on a ticket are the reason this is worth doing at all.
argus_category, argus_impact, argus_detected_by and the cause-and-cure
fields are what the hub reasons over, and Jira never had them — so 524
imported tickets carry the answer only in their prose.
"""
import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.schema import Schema
from app.services.ai_suggestions import CODE_FENCE, THINK_BLOCK
from app.services.llm import Endpoint, complete
from app.services.ticket_types import (
    CATEGORY_OPTIONS,
    DETECTED_BY_OPTIONS,
    IMPACT_OPTIONS,
)

DRAFT_SYSTEM = (
    "You write technical documentation for a particle accelerator laboratory.\n"
    "Write in Markdown. Be concrete and brief: headings, numbered steps where the "
    "document is a sequence, a table where there are parameters and values.\n"
    "Write only what follows from what you are told. Where a number, a setpoint or a "
    "name is needed but unknown, write a bracketed placeholder like [pressure] rather "
    "than inventing a plausible value — a fabricated setpoint in a procedure is "
    "dangerous.\n"
    "Do not add a preamble or explain yourself. Output the document only."
)

REVIEW_SYSTEM = (
    "You review technical documentation for a particle accelerator laboratory, for "
    "whoever has to follow it under pressure.\n"
    "Answer with JSON only: a list of objects "
    '{"severity": "high|medium|low", "message": "<one sentence>"}.\n'
    "Report what is missing, ambiguous or unsafe: a step that cannot be followed "
    "without knowing something the document never says, a missing prerequisite, an "
    "absent safety warning where the work is hazardous, a value with no unit.\n"
    "Report at most eight things, the most serious first. If the document is sound, "
    "answer with an empty list."
)

TICKET_SYSTEM = (
    "You read fault reports from a particle accelerator laboratory and fill in the "
    "structured fields an operations database needs.\n"
    "Answer with JSON only, no prose and no fences:\n"
    '{"category": "<id or null>", "impact": "<id or null>", '
    '"detected_by": "<id or null>", '
    '"system": "<the system\'s name as people write it, e.g. Vacuum, or null>", '
    '"subsystem": "<a name, e.g. Turbo pump, or null>", '
    '"root_cause": "<one or two plain sentences, or null>", '
    '"corrective_action": "<one or two plain sentences, or null>"}\n'
    "Only category, impact and detected_by take ids; use exactly the ids given. The "
    "other four are written for a person to read — sentences and ordinary names, never "
    "identifiers like turbo_pump or replaced_fan.\n"
    "Leave a field null when the text does not say — a guessed root cause is worse than "
    "an empty one, because somebody will read it as a finding."
)


def _document_type_name(db: Session, type_uid: Optional[str]) -> Optional[str]:
    if not type_uid:
        return None
    schema = db.get(Schema, type_uid)
    return schema.name if schema else None


def _describe(options: list[dict]) -> str:
    return ", ".join(f'{o["id"]} ({o["value"]})' for o in options)


def _json_payload(reply: str):
    """Whatever JSON the model managed to put in its answer."""
    text = THINK_BLOCK.sub("", reply or "").strip()
    fenced = CODE_FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except ValueError:
                continue
    return None


def draft_document(
    db: Session,
    endpoint: Endpoint,
    title: str,
    type_uid: Optional[str],
    notes: Optional[str],
) -> str:
    """A first draft in Markdown, for the editor."""
    kind = _document_type_name(db, type_uid)
    user = f"Title: {title}\n"
    if kind:
        user += f"This is a {kind}.\n"
    if notes and notes.strip():
        user += f"\nWhat the author has said so far:\n{notes.strip()}\n"
    user += "\nWrite the document."

    reply = complete(endpoint, DRAFT_SYSTEM, user)
    body = THINK_BLOCK.sub("", reply or "").strip()
    fenced = CODE_FENCE.search(body)
    # A model asked for Markdown sometimes wraps the whole thing in a fence.
    if fenced and fenced.group(1).strip().startswith("#"):
        body = fenced.group(1).strip()
    return body


def review_document(
    db: Session,
    endpoint: Endpoint,
    title: str,
    type_uid: Optional[str],
    body_markdown: str,
) -> list[dict]:
    """Remarks about a draft. Never edits it."""
    kind = _document_type_name(db, type_uid)
    user = f"Title: {title}\n"
    if kind:
        user += f"Type: {kind}\n"
    user += f"\nDocument:\n{body_markdown[:12000]}"

    data = _json_payload(complete(endpoint, REVIEW_SYSTEM, user))
    findings = []
    for row in data if isinstance(data, list) else []:
        if not isinstance(row, dict):
            continue
        message = row.get("message")
        if not isinstance(message, str) or not message.strip():
            continue
        severity = row.get("severity")
        findings.append({
            "severity": severity if severity in ("high", "medium", "low") else "low",
            "message": message.strip(),
        })
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(findings, key=lambda f: order[f["severity"]])[:8]


def draft_ticket_fields(endpoint: Endpoint, title: str, description: str,
                        vocabulary: Optional[dict] = None) -> dict:
    """The structured fields a fault report implies, where it says them. `vocabulary` (category, impact,
    detected_by -> options) is the workspace's; the core's when not given."""
    vocabulary = vocabulary or {}
    categories = vocabulary.get("category") or CATEGORY_OPTIONS
    impacts = vocabulary.get("impact") or IMPACT_OPTIONS
    detections = vocabulary.get("detected_by") or DETECTED_BY_OPTIONS
    user = (
        f"Categories: {_describe(categories)}\n"
        f"Operational impact: {_describe(impacts)}\n"
        f"Detected by: {_describe(detections)}\n\n"
        f"Title: {title}\n\nReport:\n{(description or '')[:8000]}"
    )
    data = _json_payload(complete(endpoint, TICKET_SYSTEM, user))
    if not isinstance(data, dict):
        return {
            "category": None, "impact": None, "detected_by": None,
            "system": None, "subsystem": None,
            "root_cause": None, "corrective_action": None,
        }

    def pick(field: str, options: list[dict]) -> Optional[str]:
        value = data.get(field)
        ids = {o["id"] for o in options}
        return value if isinstance(value, str) and value in ids else None

    def text(field: str) -> Optional[str]:
        value = data.get(field)
        return value.strip() if isinstance(value, str) and value.strip() else None

    return {
        "category": pick("category", categories),
        "impact": pick("impact", impacts),
        "detected_by": pick("detected_by", detections),
        "system": text("system"),
        "subsystem": text("subsystem"),
        "root_cause": text("root_cause"),
        "corrective_action": text("corrective_action"),
    }
