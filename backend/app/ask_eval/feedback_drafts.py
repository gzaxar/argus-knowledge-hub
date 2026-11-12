"""Answers people rated down, exported as draft evaluation cases (docs/ask-eval.md › From feedback to cases).

Each rating down (services/ask_feedback.py, kept without who asked) becomes a draft in the shape of ``cases.yaml``:
the question, the answer that was rated down, the person's comment, the lookups it made, the model and the ARGUS
version — with the fields a reviewer must still write left as ``TODO``. Secrets are redacted on the way out.

A draft is NOT a case. The questions come from real workspaces: before one enters the dataset, a reviewer rewrites
it onto a synthetic fixture (never copying production records, names or values into the repository), writes the
required facts and forbidden claims, and removes the ``draft`` block. ``dataset.load`` never reads drafts.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.intake.secrets import redact
from app.models.usage import AskFeedback

# A few words enough to tell an Italian question from an English one.
_ITALIAN = re.compile(r"\b(il|lo|la|gli|le|di|del|della|che|non|come|quali|quale|dove|perché|cosa|sono|è|chi|"
                      r"quanti|quando|nel|nella|con|per)\b", re.I)
_TAGS = {"search_tickets": "tickets", "get_ticket": "tickets", "search_documents": "documents",
         "get_document": "documents", "search_knowledge": "documents", "graph_neighbours": "graph",
         "impact_analysis": "graph", "root_cause_analysis": "fault-analysis", "where_is": "location",
         "search_help": "help", "read_help": "help", "workspace_access": "permission",
         "search_objects": "assets", "get_object": "assets"}


def _clean(text: Optional[str], limit: int = 4000) -> str:
    out, _counts = redact(text or "")
    return out.strip()[:limit]


def _language(text: str) -> str:
    return "it" if len(_ITALIAN.findall(text or "")) >= 2 else "en"


def draft(fb: AskFeedback) -> dict:
    """One rating down as a draft case."""
    tools = fb.tools or []
    tags = sorted({_TAGS[t.get("tool")] for t in tools if t.get("tool") in _TAGS} | {"from-feedback"})
    return {
        "id": f"fb-{fb.id[:8]}",
        "language": _language(fb.question),
        "domain": "TODO: it | accelerator | core | help",
        "severity": "TODO: critical | high | medium | low",
        "tags": tags,
        "fixture": "TODO: a synthetic fixture with the records this needs — never production records",
        "role": "reader",
        "question": _clean(fb.question),
        "required_facts": [{"id": "TODO", "any": ["TODO: what a right answer must say, as a pattern"]}],
        "expected_sources": [],
        "forbidden_claims": [],
        "expect_insufficient": False,
        "draft": {
            "status": "draft",
            "from_feedback": fb.id,
            "rated_at": fb.created_at.isoformat() if fb.created_at else None,
            "workspace": fb.workspace_id,
            "argus_version": fb.argus_version,
            "model": fb.model,
            "client": fb.client,
            "comment": _clean(fb.comment, 2000) or None,
            "rated_down_answer": _clean(fb.answer),
            "lookups": [{"tool": t.get("tool"), "arguments": t.get("arguments"), **({"error": _clean(t["error"], 500)}
                                                                                   if t.get("error") else {})}
                        for t in tools][:30],
            "stopped": fb.stopped,
            "error": _clean(fb.error, 1000) or None,
            "review": ("Rewrite onto a synthetic fixture, write the required facts and forbidden claims from what was "
                       "wrong, then remove this draft block. Do not commit production names, keys or values."),
        },
    }


def export(db: Session, since: Optional[datetime] = None, workspace: Optional[str] = None) -> tuple[str, int]:
    """Every answer rated down (since a date, in a workspace), as a YAML file of draft cases; and how many."""
    q = select(AskFeedback).where(AskFeedback.rating == "down").order_by(AskFeedback.created_at)
    if since is not None:
        q = q.where(AskFeedback.created_at >= since)
    if workspace:
        q = q.where(AskFeedback.workspace_id == workspace)
    drafts = [draft(fb) for fb in db.scalars(q)]
    head = ("# Draft Ask ARGUS evaluation cases from answers rated down (docs/ask-eval.md › From feedback to cases).\n"
            f"# Exported {datetime.now(timezone.utc).isoformat(timespec='seconds')}: {len(drafts)} draft(s).\n"
            "# These come from real workspaces: they are NOT cases and must not be committed as they are. Rewrite\n"
            "# each onto a synthetic fixture, fill in the TODOs, remove its `draft` block, and add it to cases.yaml\n"
            "# through review.\n")
    body = yaml.safe_dump({"drafts": drafts}, allow_unicode=True, sort_keys=False, width=110)
    return head + body, len(drafts)
