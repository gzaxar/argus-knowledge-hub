"""The export and import state machines. Every transition is checked, audited and idempotent.

Export:  requested → analysing → awaiting_approval → approved → generating → verifying
         → ready_to_publish → publishing → published → expired | failed | revoked
Import:  created → fetching → quarantined → verifying → invalid | awaiting_mapping | dry_run_ready
         → awaiting_approval → approved → importing → rebuilding → reconciling → ready_to_finalize
         → finalized | failed | discarded

A transition to the state the subject is already in, by the same action, is a no-op and writes no
event (a retried request). Anything else not in the table is refused with 409 `invalid_transition`.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.portability import PortabilityEvent, PortabilityExport

EXPORT = {
    "requested": {"analysing", "revoked", "failed"},
    "analysing": {"awaiting_approval", "failed", "revoked"},
    "awaiting_approval": {"analysing", "approved", "revoked"},
    "approved": {"generating", "revoked"},
    "generating": {"verifying", "failed"},
    "verifying": {"ready_to_publish", "failed"},
    "ready_to_publish": {"publishing", "revoked", "expired"},
    "publishing": {"published", "failed", "ready_to_publish"},
    "published": {"revoked", "expired"},
    "failed": {"analysing", "revoked"},
    "expired": set(), "revoked": set(),
}
IMPORT = {
    "created": {"fetching", "quarantined", "discarded"},
    "fetching": {"quarantined", "invalid", "discarded"},
    "quarantined": {"verifying", "discarded"},
    "verifying": {"invalid", "awaiting_mapping", "dry_run_ready", "discarded"},
    "invalid": {"discarded"},
    "awaiting_mapping": {"dry_run_ready", "discarded"},
    "dry_run_ready": {"dry_run_ready", "awaiting_approval", "discarded"},
    "awaiting_approval": {"dry_run_ready", "approved", "discarded"},
    "approved": {"importing", "discarded"},
    "importing": {"rebuilding", "failed", "discarded"},
    "rebuilding": {"reconciling", "failed", "discarded"},
    "reconciling": {"ready_to_finalize", "failed", "discarded"},
    "ready_to_finalize": {"finalized", "discarded"},
    # From failed: resume loading, or (once it was reconciled, its staging kept) only reconcile again.
    "failed": {"importing", "reconciling", "discarded"},
    "finalized": set(), "discarded": set(),
}
TERMINAL_EXPORT = {"published", "expired", "revoked"}
TERMINAL_IMPORT = {"finalized", "discarded"}


class TransitionError(ValueError):
    def __init__(self, message: str, code: str = "invalid_transition", status: int = 409):
        super().__init__(message)
        self.code, self.status = code, status


def audit(db: Session, subject, action: str, actor: str, detail: Optional[dict] = None,
          from_state: Optional[str] = None, to_state: Optional[str] = None) -> None:
    kind = "export" if isinstance(subject, PortabilityExport) else "import"
    db.add(PortabilityEvent(subject_kind=kind, subject_id=subject.id, kind=action, from_state=from_state,
                            to_state=to_state, actor=actor, detail=detail))
    db.flush()


def move(db: Session, subject, to_state: str, actor: str, action: str, detail: Optional[dict] = None) -> bool:
    """Move `subject` to `to_state`. False when it was already there (nothing written)."""
    table = EXPORT if isinstance(subject, PortabilityExport) else IMPORT
    current = subject.state
    if current == to_state and to_state not in table.get(current, set()):
        return False
    if to_state not in table.get(current, set()):
        raise TransitionError(f"{action}: not possible from {current}")
    subject.state = to_state
    audit(db, subject, action, actor, detail, current, to_state)
    return True


def expect(subject, *states: str) -> None:
    if subject.state not in states:
        raise TransitionError(f"this needs state {' or '.join(states)}; it is {subject.state}")


def labels(manifest: Optional[dict], extra: Optional[dict] = None) -> dict:
    """What a person must see about an archive at a glance."""
    l = dict((manifest or {}).get("labels") or {})
    out = {"complete": l.get("complete", False), "selective": l.get("selective", False),
           "full": (manifest or {}).get("mode") == "full", "incremental": l.get("incremental", False),
           "signed": l.get("signed", False), "encrypted": l.get("encrypted", False),
           "artifact_complete": l.get("artifact_complete", False), "evidence_only": l.get("evidence_only", False),
           "uninspected_content": l.get("uninspected_content", False),
           "git_published": False, "verified": False, "restorable": False}
    out.update(extra or {})
    out["restorable"] = bool(out["verified"] and out["artifact_complete"] and out["signed"]
                             and not out["evidence_only"])
    return out
