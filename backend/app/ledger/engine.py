"""The fact ledger's engine (asset-model-revision §7, §8, §11).

Pipeline, as implemented for the S1 vertical slice:

    parse   ingest()          source bytes -> claims; events only on change
    infer   (inside parsers)  inferred claims carry method=inferred and a semantic rule id
    resolve run_resolvers()   source refs -> records; resolved claims (installation proposals)
    project project_subject() claims + decisions + policy -> attributes, edges, status, conflicts
    derive  derive_all()      realized-by and implemented-by edges, port attachment,
                              ticket attribution (connectivity.py, tickets.py)

Heads: every stream has a parsed head (what the source last said) and a
published head (what projection consumes). A revision is guarded against the
published head and publishing applies the net change (§11).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.ledger import temporal
from app.ledger.policy import (DEFAULT_POLICY, RANK_ORDER, ClaimContext, Policy, PolicyError, Vocabulary,
                               validate as validate_policy)
from app.models.asset import Asset, Relation
from app.models.asset_subresources import AssetTicket
from app.models.document import DocumentRelation
from app.models.issue import Issue
from app.models.ledger import (Claim, ClaimEvent, Conflict, ConflictEvent, Decision, FactState, IdentityBinding,
                               DeriveRequest, IdentityEvent, JobRun, LedgerPolicy, LedgerRuleset, LedgerStream,
                               RecordEvent, RevisionEvent, SourceRevision, StatusEvent, StreamHead)
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.ledger.writer import ledger_writer

PROJECTOR_VERSION = "projector/1"
DERIVER_VERSION = "deriver/1"
GUARD_SHARE = 0.10
GUARD_MIN = 10
INTERNAL_KINDS = {"person", "resolver", "system", "ai"}   # ai: the AI Intake, per workspace and operation (§23.8)

# Multi-valued predicates: each member is its own fact (§7.8). Relations are
# multi-valued unless the registry says one per source.
MULTI_ATTRS = {"attr:zones", "attr:networks", "attr:argus_keywords"}
SINGLE_RELATIONS = {"rel:installed at", "rel:installation of", "rel:assigned to"}
INSTALLATION = "Installation"
ACCESS_POINT = "Access Point"
INSTALLABLE = {"Equipment Position", "Motion Axis", "Mirror", "Dipole", "Quadrupole", "Sextupole",
               "Corrector", "Solenoid", "Accelerating Structure", "RF Gun", "Beam Position Monitor",
               # The beam model's positions (docs/beam-model.md): a lattice or optical position stays while the
               # unit installed at it changes. A drift has nothing installed at it.
               "Kicker", "Septum", "RF Cavity", "Beam Source", "Beam Dump", "Lens", "Beam Splitter",
               "Generic Beam Element", "Screen Station", "Generic Monitor", "Collimator", "Beam Stopper",
               "Undulator", "Beam Charge Monitor", "Beam Loss Monitor", "Faraday Cup", "Wire Scanner",
               # argus.beam-model/2: vacuum, material, optical and support components are positions too.
               "Vacuum Element", "Material Element", "Optical Element", "Support Element", "RF Deflector",
               "Spectrometer Station", "Beam Arrival Monitor", "Bunch Length Monitor", "Emittance Meter"}


class LedgerError(ValueError):
    """A request the ledger refuses; nothing it asked for was written."""


class InvariantError(LedgerError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def now() -> datetime:
    return datetime.now(timezone.utc)


def ulid() -> str:
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    n = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    out = []
    for _ in range(26):
        out.append(alphabet[n & 31])
        n >>= 5
    return "".join(reversed(out))


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def is_multi(predicate: str) -> bool:
    return predicate in MULTI_ATTRS or (predicate.startswith("rel:") and predicate not in SINGLE_RELATIONS)


# --------------------------------------------------------------------------- claims

@dataclass
class ParsedClaim:
    source_ref: str
    predicate: str
    value: object = None
    method: str = "stated"
    rule_id: Optional[str] = None
    member: Optional[str] = None
    polarity: str = "present"
    evidence: Optional[dict] = None
    confidence: Optional[float] = None
    derived_from: list = field(default_factory=list)

    def claim_id(self, stream_id: str) -> str:
        member = self.member
        if member is None and is_multi(self.predicate):
            member = self.value["ref"] if isinstance(self.value, dict) and "ref" in self.value else canonical(self.value)
            self.member = member
        payload = canonical([stream_id, self.source_ref, self.predicate, member, self.polarity,
                             self.value, self.method, self.rule_id])
        return hashlib.sha256(payload.encode()).hexdigest()[:32]


def fingerprint(stream_kind: str, claim: Claim, rule_id: Optional[str] = None) -> str:
    """What a rejection by fingerprint remembers: the conclusion, whichever
    revision states it. `rule_id` computes it as another rule would state it."""
    payload = canonical([stream_kind, rule_id or claim.rule_id, claim.source_ref, claim.predicate, claim.member,
                         claim.polarity, claim.value])
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


# --------------------------------------------------------------------------- streams and policy

def register_stream(db: Session, stream_id: str, workspace_id: str, kind: str, *,
                    facility: Optional[str] = None, may_create: Iterable[str] = ()) -> LedgerStream:
    stream = db.get(LedgerStream, stream_id)
    if stream is None:
        stream = LedgerStream(id=stream_id, workspace_id=workspace_id, kind=kind, facility=facility,
                              may_create=list(may_create), created_at=now())
        db.add(stream)
        db.add(StreamHead(stream_id=stream_id, parsed_number=0, published_number=0))
        db.flush()
    return stream


def person_stream(db: Session, workspace_id: str, user: str) -> LedgerStream:
    return register_stream(db, f"person:{user}@{workspace_id}", workspace_id, "person", may_create=["*"])


def current_vocabulary(db: Session) -> Vocabulary:
    from app.ledger.rules import RULES
    schemas = list(db.scalars(select(Schema)))
    by_uid = {s.uid: s for s in schemas}
    types: dict[str, tuple] = {}
    for s in schemas:
        lineage, seen, cur = [], set(), s
        while cur is not None and cur.uid not in seen:
            seen.add(cur.uid)
            lineage.append(cur.name)
            cur = by_uid.get(cur.parent_schema_uid) if cur.parent_schema_uid else None
        types.setdefault(s.name, tuple(lineage))
    streams = {s.id: s.kind for s in db.scalars(select(LedgerStream)) if s.kind not in INTERNAL_KINDS}
    return Vocabulary(
        types=types,
        workspaces=[w.id for w in db.scalars(select(Workspace))],
        facilities=sorted({s.facility for s in db.scalars(select(LedgerStream)) if s.facility}),
        domains=[],
        streams=streams,
        rules=sorted(RULES),
    )


def activate_policy(db: Session, body: Optional[dict] = None, actor: str = "system",
                    streams: Optional[set] = None) -> LedgerPolicy:
    """Validate a policy against the current vocabulary and make it active.
    Raises PolicyError (nothing written) when it is invalid. `streams`, when given, admits only those
    of the existing external streams rather than all of them."""
    body = body or DEFAULT_POLICY
    vocab = current_vocabulary(db)
    if streams is not None:
        import dataclasses
        vocab = dataclasses.replace(vocab, streams={k: v for k, v in vocab.streams.items() if k in streams})
    report = validate_policy(Policy(body, vocab.depths()), vocab)
    version = f"{body.get('policy_version', 'unversioned')}@{vocab.digest()}"
    previous = db.scalar(select(LedgerPolicy).order_by(LedgerPolicy.activated_at.desc()).limit(1))
    row = db.get(LedgerPolicy, version)
    if row is None:
        row = LedgerPolicy(version=version, body=body,
                           vocabulary={"streams": sorted(vocab.streams), "rules": vocab.rules},
                           report=report, activated_by=actor, activated_at=now())
        db.add(row)
        db.flush()
    else:
        row.activated_at = now()
    if previous is not None and previous.version != version:
        # Every status the new version changes is recorded with the policy as
        # its cause (§7.7). A changed body can move any rank; a grown
        # vocabulary only affects the claims of the streams it adds.
        _POLICY_CACHE.clear()
        if previous.body != body:
            subjects = set(db.scalars(select(IdentityBinding.uid))) | set(
                db.scalars(select(Decision.subject_uid).where(Decision.subject_uid.isnot(None))))
        else:
            added = set(row.vocabulary["streams"]) - set(previous.vocabulary.get("streams") or [])
            refs = set(db.scalars(select(Claim.source_ref).where(Claim.stream_id.in_(added)))) if added else set()
            subjects = {b.uid for b in db.scalars(select(IdentityBinding).where(IdentityBinding.source_ref.in_(refs)))}
        for uid in sorted(subjects):
            project_subject(db, uid, f"policy:{version}")
    return row


_POLICY_CACHE: dict = {}


def active_policy(db: Session) -> tuple[Policy, LedgerPolicy]:
    row = db.scalar(select(LedgerPolicy).order_by(LedgerPolicy.activated_at.desc()).limit(1))
    if row is None:
        row = activate_policy(db)
    from sqlalchemy import func
    key = (row.version, db.scalar(select(func.count()).select_from(Schema)))
    if key not in _POLICY_CACHE:
        _POLICY_CACHE.clear()
        _POLICY_CACHE[key] = Policy(row.body, current_vocabulary(db).depths())
    return _POLICY_CACHE[key], row


# --------------------------------------------------------------------------- rulesets (§7.9)

def active_ruleset(db: Session, workspace_id: str):
    from app.ledger.rules import DEFAULT_RULESET
    from app.ledger.sources import Ruleset
    rules, impl = dict(DEFAULT_RULESET), {}
    for scope in ("*", workspace_id):
        row = db.scalar(select(LedgerRuleset).where(LedgerRuleset.scope == scope)
                        .order_by(LedgerRuleset.seq.desc()).limit(1))
        if row is not None:
            rules.update(row.rules)
            impl.update(row.impl or {})
    return Ruleset(rules, impl)


def activate_ruleset(db: Session, scope: str, rules: dict, impl: Optional[dict] = None,
                     actor: str = "system") -> dict:
    """Switch rule ids or implementations for a workspace (or "*"), then run
    inference again over what every affected stream last published. Each
    stream's re-run is a revision like any other: guarded, and published as a
    net transition (§7.9 Guard)."""
    from app.ledger.rules import RULES
    impl = dict(impl or {})
    for family, rule_id in rules.items():
        if rule_id not in RULES or RULES[rule_id]["family"] != family:
            raise LedgerError(f"{rule_id!r} is not a rule of family {family!r}")
    for rule_id, version in impl.items():
        if rule_id not in RULES or version not in RULES[rule_id]["impl"]:
            raise LedgerError(f"{rule_id!r} has no implementation {version!r}")
    before = {ws: active_ruleset(db, ws) for ws in _ruleset_workspaces(db, scope)}
    db.add(LedgerRuleset(scope=scope, rules=rules, impl=impl, activated_by=actor, activated_at=now()))
    db.flush()
    results = {}
    for ws, old in before.items():
        new = active_ruleset(db, ws)
        _carry_rejections(db, ws, old, new, actor)
        for stream in db.scalars(select(LedgerStream).where(LedgerStream.workspace_id == ws,
                                                            LedgerStream.kind == "epik8s")):
            results[stream.id] = reinfer(db, stream.id, cause=f"ruleset by {actor}")
    return results


def _ruleset_workspaces(db: Session, scope: str) -> list[str]:
    q = select(LedgerStream.workspace_id).where(LedgerStream.kind == "epik8s").distinct()
    if scope != "*":
        q = q.where(LedgerStream.workspace_id == scope)
    return sorted(db.scalars(q))


def reinfer(db: Session, stream_id: str, cause: str) -> Optional[dict]:
    """Parse what the stream last published again, with the active rules."""
    head = db.get(StreamHead, stream_id)
    rev = db.get(SourceRevision, head.published_head) if head and head.published_head else None
    if rev is None or rev.content is None:
        return None
    parser = next(name for name, p in _parsers().items() if rev.parser_version.startswith(p.version))
    return ingest(db, stream_id, revision=rev.revision, content=rev.content, observed_at=rev.observed_at,
                  parser=parser, cause=cause)


def _parsers():
    from app.ledger.sources import PARSERS
    return PARSERS


def _carry_rejections(db: Session, workspace_id: str, old, new, actor: str) -> None:
    """A rejection names a conclusion under one rule id, so it does not carry
    to a new id — unless the new rule declares that it supersedes the old one
    and `carries_rejections` (§7.9). The carried rejection is a `policy`
    decision citing both ids."""
    from app.ledger.rules import RULES
    for family, rule_id in new.rules.items():
        previous = old.rules.get(family)
        spec = RULES[rule_id]
        if previous == rule_id or spec.get("supersedes") != previous or not spec.get("carries_rejections"):
            continue
        dctx = _decision_context(db, workspace_id)
        for d in db.scalars(select(Decision).where(Decision.workspace_id == workspace_id, Decision.kind == "reject")):
            t = d.target or {}
            if d.decision_id in dctx.ended or not t.get("fingerprint") or not t.get("claim_id"):
                continue
            claim = db.get(Claim, t["claim_id"])
            if claim is None or claim.rule_id != previous:
                continue
            stream = db.get(LedgerStream, claim.stream_id)
            _record_decision(db, "reject", "policy", workspace_id, subject_uid=d.subject_uid,
                             target={"fingerprint": fingerprint(stream.kind, claim, rule_id),
                                     "carried_from": d.decision_id, "rules": [previous, rule_id]},
                             reason=f"rejection carried from {previous} to {rule_id} ({actor})")


# --------------------------------------------------------------------------- presence

def _presence(db: Session, stream_id: str, upto: int) -> dict[str, dict]:
    """claim_id -> latest evidence, for claims present at revision number `upto`.

    Claim events are append-only, so the answer only moves when the stream
    gains an event: it is cached on the session against the stream's last
    seq. Projecting every subject of a large revision otherwise replays the
    whole stream once per subject."""
    last = db.scalar(select(func.max(ClaimEvent.seq)).where(ClaimEvent.stream_id == stream_id))
    cache = db.info.setdefault("ledger_presence", {})
    hit = cache.get((stream_id, upto))
    if hit is not None and hit[0] == last:
        return dict(hit[1])
    present: dict[str, dict] = {}
    rows = db.execute(select(ClaimEvent.claim_id, ClaimEvent.kind, ClaimEvent.evidence, ClaimEvent.seq)
                      .where(ClaimEvent.stream_id == stream_id, ClaimEvent.revision_number <= upto)
                      .order_by(ClaimEvent.seq))
    for claim_id, kind, evidence, seq in rows:
        if kind == "appeared":
            present[claim_id] = {"evidence": evidence, "seq": seq}
        elif kind == "disappeared":
            present.pop(claim_id, None)
        elif kind == "evidence_changed" and claim_id in present:
            present[claim_id] = {**present[claim_id], "evidence": evidence}
    cache[(stream_id, upto)] = (last, present)
    return dict(present)


def revision_state(db: Session, revision_id: str) -> str:
    ev = db.scalar(select(RevisionEvent).where(RevisionEvent.revision_id == revision_id)
                   .order_by(RevisionEvent.seq.desc()).limit(1))
    return ev.kind if ev else "unknown"


# --------------------------------------------------------------------------- parse

@ledger_writer
def ingest(db: Session, stream_id: str, *, revision: str, content: bytes, observed_at, parser: str,
           cause: str = "import") -> dict:
    """The parse stage for one source revision (§7.6, §11)."""
    from app.ledger.sources import PARSERS
    stream = db.get(LedgerStream, stream_id)
    if stream is None:
        raise LedgerError(f"unknown stream {stream_id}")
    observed = temporal.parse_instant(observed_at)
    head = db.get(StreamHead, stream_id)
    p = PARSERS[parser]
    ruleset = active_ruleset(db, stream.workspace_id)
    parser_version, impl_version = p.versions(ruleset)
    content_hash = hashlib.sha256(content).hexdigest()
    rev = SourceRevision(id=str(uuid.uuid4()), stream_id=stream_id, revision=revision, content_hash=content_hash,
                         parser_version=parser_version, impl_version=impl_version, content=content,
                         observed_at=observed, retrieved_at=now(),
                         parent_revision_id=head.parsed_head, number=head.parsed_number + 1)

    if stream.frozen_at is not None:
        rev.number = 0
        rev.ordering = "rejected"
        db.add(rev)
        db.add(RevisionEvent(revision_id=rev.id, stream_id=stream_id, kind="rejected", cause="frozen", at=now()))
        db.flush()
        return {"revision_id": rev.id, "state": "rejected", "reason": "stream frozen at cutover"}

    if head.parsed_head:
        parsed = db.get(SourceRevision, head.parsed_head)
        if parsed is not None and observed < parsed.observed_at:
            rev.number = 0
            rev.ordering = "historical"
            db.add(rev)
            db.add(RevisionEvent(revision_id=rev.id, stream_id=stream_id, kind="parsed", cause="historical", at=now()))
            db.flush()
            return {"revision_id": rev.id, "state": "historical"}

    prior = db.scalar(select(SourceRevision).where(
        SourceRevision.stream_id == stream_id, SourceRevision.content_hash == content_hash,
        SourceRevision.parser_version == parser_version, SourceRevision.impl_version == impl_version,
        SourceRevision.ordering == "head")
        .order_by(SourceRevision.number.desc()).limit(1))
    if prior is not None:
        # Identical bytes, same rules, same code: reuse the claim set it produced.
        rev.parse_skipped = True
        target = {cid: info for cid, info in _presence(db, stream_id, prior.number).items()}
        new_claims: dict[str, ParsedClaim] = {}
        db.add(JobRun(stage="parse", stage_version=parser_version, scope=stream_id, input_digest=content_hash,
                      status="skipped", counts={"impl_version": impl_version}, at=now()))
    else:
        parsed_claims = p.parse(content, stream, ruleset)
        new_claims = {}
        for c in parsed_claims:
            new_claims[c.claim_id(stream_id)] = c
        target = {cid: {"evidence": c.evidence} for cid, c in new_claims.items()}
        db.add(JobRun(stage="parse", stage_version=parser_version, scope=stream_id, input_digest=content_hash,
                      status="ran", counts={"claims": len(new_claims), "impl_version": impl_version}, at=now()))
    db.add(rev)
    db.flush()
    counts = _write_diff(db, stream_id, rev, new_claims, target, _presence(db, stream_id, head.parsed_number),
                         impl_version)
    head.parsed_head, head.parsed_number = rev.id, rev.number
    db.add(RevisionEvent(revision_id=rev.id, stream_id=stream_id, kind="parsed", cause=cause, at=now()))
    db.flush()
    state = _guard_and_publish(db, stream, rev)
    return {"revision_id": rev.id, "number": rev.number, "state": state, "parse_skipped": rev.parse_skipped,
            **counts}


def _write_diff(db: Session, stream_id: str, rev: SourceRevision, new_claims: dict, target: dict,
                previous: dict, impl_version: str) -> dict:
    appeared = disappeared = evidence_changed = 0
    for cid, c in new_claims.items():
        if db.get(Claim, cid) is None:
            db.add(Claim(claim_id=cid, stream_id=stream_id, source_ref=c.source_ref, predicate=c.predicate,
                         member=c.member, polarity=c.polarity, value=c.value, method=c.method,
                         rule_id=c.rule_id, derived_from=list(c.derived_from)))
    db.flush()
    for cid, info in target.items():
        if cid not in previous:
            confidence = new_claims[cid].confidence if cid in new_claims else None
            db.add(ClaimEvent(claim_id=cid, stream_id=stream_id, revision_id=rev.id, revision_number=rev.number,
                              kind="appeared", impl_version=impl_version, evidence=info.get("evidence"),
                              confidence=confidence, at=now()))
            appeared += 1
        elif info.get("evidence") is not None and info.get("evidence") != previous[cid].get("evidence"):
            db.add(ClaimEvent(claim_id=cid, stream_id=stream_id, revision_id=rev.id, revision_number=rev.number,
                              kind="evidence_changed", impl_version=impl_version, evidence=info.get("evidence"),
                              at=now()))
            evidence_changed += 1
    for cid in previous:
        if cid not in target:
            db.add(ClaimEvent(claim_id=cid, stream_id=stream_id, revision_id=rev.id, revision_number=rev.number,
                              kind="disappeared", impl_version=impl_version, at=now()))
            disappeared += 1
    db.flush()
    return {"appeared": appeared, "disappeared": disappeared, "evidence_changed": evidence_changed}


@ledger_writer
def add_manual_claims(db: Session, stream: LedgerStream, claims: list[ParsedClaim], cause: str) -> list[str]:
    """A person's statements: added to their stream without withdrawing the
    earlier ones (delta semantics), and published at once."""
    head = db.get(StreamHead, stream.id)
    rev = SourceRevision(id=str(uuid.uuid4()), stream_id=stream.id, revision=f"edit-{ulid()}",
                         content_hash=hashlib.sha256(canonical([c.__dict__ for c in claims]).encode()).hexdigest(),
                         parser_version="manual/1", observed_at=now(), retrieved_at=now(),
                         parent_revision_id=head.parsed_head, number=head.parsed_number + 1)
    db.add(rev)
    db.flush()
    previous = _presence(db, stream.id, head.parsed_number)
    new_claims = {c.claim_id(stream.id): c for c in claims}
    target = {**previous, **{cid: {"evidence": c.evidence} for cid, c in new_claims.items()}}
    # A person retracting their own statement is an absent claim, not a deletion.
    _write_diff(db, stream.id, rev, new_claims, target, previous, "manual/1")
    head.parsed_head = head.published_head = rev.id
    head.parsed_number = head.published_number = rev.number
    db.add(RevisionEvent(revision_id=rev.id, stream_id=stream.id, kind="published", cause=cause, at=now()))
    db.flush()
    for c in claims:
        _ensure_record(db, stream, c.source_ref, c if c.predicate == "exists" else None, cause)
    return list(new_claims)


# --------------------------------------------------------------------------- guard and publish

def _subjects(db: Session, claim_ids: Iterable[str]) -> dict[str, str]:
    out = {}
    for cid in claim_ids:
        c = db.get(Claim, cid)
        if c is not None and c.predicate == "exists" and c.polarity == "present":
            out[c.source_ref] = cid
    return out


def has_dependents(db: Session, uid: str) -> bool:
    """Tickets, documents or a Confirmed Installation (§11 guard)."""
    if db.scalar(select(Issue.uid).where(Issue.asset_uid == uid).limit(1)):
        return True
    if db.scalar(select(AssetTicket.uid).where(AssetTicket.asset_uid == uid).limit(1)):
        return True
    if db.scalar(select(DocumentRelation.id).where(DocumentRelation.to_type == "asset",
                                                   DocumentRelation.to_uid == uid).limit(1)):
        return True
    for rel in db.scalars(select(Relation).where(Relation.to_asset_uid == uid, Relation.derivation == "ledger",
                                                 Relation.relation_type.in_(("installed at", "installation of")))):
        inst = db.get(Asset, rel.from_asset_uid)
        if inst is not None and (inst.attributes or {}).get("installation_status") == "Confirmed":
            return True
    return False


def _guard(db: Session, stream: LedgerStream, published: dict, candidate: dict) -> list[str]:
    old, new = _subjects(db, published), _subjects(db, candidate)
    gone = set(old) - set(new)
    reasons = []
    if old and len(gone) > GUARD_SHARE * len(old) and len(gone) >= GUARD_MIN:
        reasons.append(f"{len(gone)} of {len(old)} subjects would disappear")
    for ref in sorted(gone):
        binding = db.get(IdentityBinding, ref)
        if binding is not None and has_dependents(db, binding.uid) and not _other_support(db, binding.uid, stream.id):
            reasons.append(f"{ref} would retire a record with tickets, documents or a confirmed installation")
    return reasons


def _other_support(db: Session, uid: str, except_stream: str) -> bool:
    for b in db.scalars(select(IdentityBinding).where(IdentityBinding.uid == uid)):
        for c in db.scalars(select(Claim).where(Claim.source_ref == b.source_ref, Claim.predicate == "exists",
                                                Claim.polarity == "present", Claim.stream_id != except_stream)):
            head = db.get(StreamHead, c.stream_id)
            if head and c.claim_id in _presence(db, c.stream_id, head.published_number):
                return True
    return bool(_active_decisions(db, uid, "exists", None))


def _guard_and_publish(db: Session, stream: LedgerStream, rev: SourceRevision) -> str:
    head = db.get(StreamHead, stream.id)
    reasons = _guard(db, stream, _presence(db, stream.id, head.published_number),
                     _presence(db, stream.id, rev.number))
    if reasons:
        db.add(RevisionEvent(revision_id=rev.id, stream_id=stream.id, kind="held", cause="guard",
                             detail={"reasons": reasons}, at=now()))
        db.flush()
        return "held"
    publish(db, stream, rev, cause="guard passed")
    return "published"


@ledger_writer
def publish(db: Session, stream: LedgerStream, rev: SourceRevision, *, cause: str, kind: str = "published") -> None:
    """Move the published head to `rev` and apply the net transition."""
    head = db.get(StreamHead, stream.id)
    before = _presence(db, stream.id, head.published_number)
    after = _presence(db, stream.id, rev.number)
    previous = db.get(SourceRevision, head.published_head) if head.published_head else None
    lo, hi = sorted((head.published_number, rev.number))
    for other in db.scalars(select(SourceRevision).where(SourceRevision.stream_id == stream.id,
                                                         SourceRevision.number > lo,
                                                         SourceRevision.number < hi)):
        if revision_state(db, other.id) == "held":
            db.add(RevisionEvent(revision_id=other.id, stream_id=stream.id, kind="superseded",
                                 cause=f"published {rev.id}", at=now()))
    head.published_head, head.published_number = rev.id, rev.number
    db.add(RevisionEvent(revision_id=rev.id, stream_id=stream.id, kind=kind, cause=cause, at=now()))
    db.flush()
    changed = set(before) ^ set(after)
    affected_refs = {db.get(Claim, cid).source_ref for cid in changed}
    for ref in affected_refs:
        # A claim about a record by its uid, made outside the ledger (an import writes its records directly):
        # bound to itself here, as one created through the ledger already is, so it is projected.
        if ref.startswith("uid:"):
            _ensure_record(db, stream, ref, None, f"revision:{rev.id}")
    for cid in after:
        c = db.get(Claim, cid)
        if c.predicate == "exists":
            _ensure_record(db, stream, c.source_ref, _as_parsed(c), f"revision:{rev.id}")
    from app.ledger import connectivity
    touched = connectivity.reconcile_access_points(db, stream, before, after,
                                                   previous.observed_at if previous else None, rev.observed_at,
                                                   f"revision:{rev.id}")
    subjects = {b.uid for ref in affected_refs if (b := db.get(IdentityBinding, ref)) is not None} | touched
    for uid in sorted(subjects):
        project_subject(db, uid, f"revision:{rev.id}")
    from app.ledger.identity import detect_candidates
    detect_candidates(db, subjects, f"revision:{rev.id}")
    if stream.kind != "resolver":
        run_resolvers(db, stream, changed)
    derive_all(db, _workspaces_of(db, subjects) | {stream.workspace_id})
    # A held later revision is re-evaluated against the new published head.
    for later in db.scalars(select(SourceRevision).where(SourceRevision.stream_id == stream.id,
                                                         SourceRevision.number > rev.number)
                            .order_by(SourceRevision.number)):
        if revision_state(db, later.id) == "held" and not _guard(
                db, stream, _presence(db, stream.id, rev.number), _presence(db, stream.id, later.number)):
            publish(db, stream, later, cause="guard passed after approval")
            break


def approve_revision(db: Session, revision_id: str, actor: str) -> None:
    rev = db.get(SourceRevision, revision_id)
    if rev is None or revision_state(db, revision_id) != "held":
        raise LedgerError("only a held revision can be approved")
    _record_decision(db, "approve_revision", actor, db.get(LedgerStream, rev.stream_id).workspace_id,
                     target={"revision_id": revision_id})
    publish(db, db.get(LedgerStream, rev.stream_id), rev, cause=f"approved by {actor}")


def reject_revision(db: Session, revision_id: str, actor: str) -> None:
    rev = db.get(SourceRevision, revision_id)
    if rev is None or revision_state(db, revision_id) != "held":
        raise LedgerError("only a held revision can be rejected")
    _record_decision(db, "reject_revision", actor, db.get(LedgerStream, rev.stream_id).workspace_id,
                     target={"revision_id": revision_id})
    db.add(RevisionEvent(revision_id=revision_id, stream_id=rev.stream_id, kind="rejected",
                         cause=f"rejected by {actor}", at=now()))
    db.flush()


def rewind(db: Session, stream_id: str, revision_id: str, actor: str) -> None:
    rev = db.get(SourceRevision, revision_id)
    if rev is None or rev.stream_id != stream_id or rev.ordering != "head":
        raise LedgerError("rewind needs a head-order revision of this stream")
    stream = db.get(LedgerStream, stream_id)
    _record_decision(db, "rewind", actor, stream.workspace_id, target={"revision_id": revision_id})
    publish(db, stream, rev, cause=f"rewind by {actor}", kind="rewound_to")


def freeze_stream(db: Session, stream_id: str, actor: str) -> None:
    """The cutover watermark (§17.3): the stream accepts no further revisions."""
    stream = db.get(LedgerStream, stream_id)
    stream.frozen_at = now()
    _record_decision(db, "freeze", actor, stream.workspace_id, target={"stream_id": stream_id})
    db.flush()


# --------------------------------------------------------------------------- identity

def _as_parsed(c: Claim) -> ParsedClaim:
    return ParsedClaim(c.source_ref, c.predicate, c.value, c.method, c.rule_id, c.member, c.polarity)


def ensure_type(db: Session, workspace_id: str, name: str) -> Schema:
    schema = db.scalar(select(Schema).where(Schema.name == name, Schema.workspace_id == workspace_id,
                                            Schema.applies_to == "objects"))
    if schema is None:
        schema = db.scalar(select(Schema).where(Schema.name == name, Schema.is_global.is_(True),
                                                Schema.applies_to == "objects"))
    if schema is None:
        schema = Schema(uid=f"{workspace_id}:ledger:{name.lower().replace(' ', '-')}", workspace_id=workspace_id,
                        name=name, applies_to="objects")
        db.add(schema)
        db.flush()
    return schema


def bind(db: Session, source_ref: str, uid: str, cause: str) -> None:
    existing = db.get(IdentityBinding, source_ref)
    if existing is not None and existing.uid == uid:
        return
    kind = "rebound" if existing is not None else "bound"
    if existing is None:
        db.add(IdentityBinding(source_ref=source_ref, uid=uid))
    else:
        existing.uid = uid
    db.add(IdentityEvent(source_ref=source_ref, uid=uid, kind=kind, cause=cause, at=now()))
    db.flush()


def resolve_ref(db: Session, source_ref: str) -> Optional[str]:
    if source_ref.startswith("uid:"):
        record = db.get(Asset, source_ref[4:])
        # A merged record is a tombstone: a reference to it means its survivor.
        seen = set()
        while record is not None and record.merged_into_uid and record.uid not in seen:
            seen.add(record.uid)
            record = db.get(Asset, record.merged_into_uid)
        return record.uid if record is not None else None
    b = db.get(IdentityBinding, source_ref)
    return b.uid if b else None


def _ensure_record(db: Session, stream: LedgerStream, source_ref: str, exists: Optional[ParsedClaim],
                   cause: str) -> Optional[str]:
    if source_ref.startswith("uid:"):
        uid = source_ref[4:]
        if db.get(IdentityBinding, source_ref) is None and db.get(Asset, uid) is not None:
            bind(db, source_ref, uid, "self")
        return uid
    b = db.get(IdentityBinding, source_ref)
    if b is not None:
        if exists is not None:
            # Bound by an immutable id: a re-keyed object is the same record (A34).
            from app.ledger.identity import maybe_rekey
            maybe_rekey(db, stream, b.uid, exists.value, cause)
        return b.uid
    if exists is None or not isinstance(exists.value, dict):
        return None
    type_name = exists.value.get("type")
    allowed = stream.may_create or []
    if type_name is None or ("*" not in allowed and type_name not in allowed):
        return None
    prefix = {INSTALLATION: "INS", ACCESS_POINT: "AP"}.get(type_name, "REC")
    key = exists.value.get("key") or f"{prefix}-{ulid()}"
    existing = db.scalar(select(Asset).where(Asset.key == key))
    if existing is not None:
        if existing.workspace_id != stream.workspace_id or existing.type != type_name:
            raise LedgerError(f"key {key!r} already belongs to another record")
        bind(db, source_ref, existing.uid, "adopted by key")
        return existing.uid
    schema = ensure_type(db, stream.workspace_id, type_name)
    uid = str(uuid.uuid4())
    db.add(Asset(uid=uid, workspace_id=stream.workspace_id, schema_uid=schema.uid, key=key,
                 name=exists.value.get("name") or key, type=type_name, attributes={},
                 record_status="Provisional"))
    db.flush()
    db.add(RecordEvent(uid=uid, kind="created", after={"key": key, "type": type_name}, cause=cause, at=now()))
    bind(db, source_ref, uid, cause)
    return uid


# --------------------------------------------------------------------------- decisions

DECISION_KINDS = {"accept", "reject", "confirm", "supersede", "retract", "revoke", "resolve_conflict"}


def _record_decision(db: Session, kind: str, actor: str, workspace_id: str, *, batch_id: Optional[str] = None,
                     **fields) -> Decision:
    d = Decision(decision_id=str(uuid.uuid4()), batch_id=batch_id or str(uuid.uuid4()), kind=kind, actor=actor,
                 workspace_id=workspace_id, at=now(), supersedes=fields.pop("supersedes", None) or [], **fields)
    db.add(d)
    db.flush()
    return d


def _ended(db: Session, workspace_id: str) -> set[str]:
    """Decision ids no longer in force: named by a later supersede, retract or
    revoke. Decisions only name decisions of their own workspace."""
    out: set[str] = set()
    ws = Decision.workspace_id == workspace_id
    for d in db.scalars(select(Decision).where(ws, Decision.kind.in_(("supersede", "retract", "revoke")))):
        out.update(d.supersedes or [])
        out.update((d.target or {}).get("decisions") or [])
    # A revoked supersede/retract no longer ends what it named.
    revoked = {x for d in db.scalars(select(Decision).where(ws, Decision.kind == "revoke"))
               for x in (d.target or {}).get("decisions") or []}
    for d in db.scalars(select(Decision).where(Decision.decision_id.in_(revoked),
                                               Decision.kind.in_(("supersede", "retract")))):
        for x in (d.supersedes or []) + ((d.target or {}).get("decisions") or []):
            out.discard(x)
    return out


def _active_decisions(db: Session, uid: str, predicate: str, member: Optional[str]) -> list[Decision]:
    record = db.get(Asset, uid)
    ended = _ended(db, record.workspace_id) if record else set()
    q = select(Decision).where(Decision.subject_uid == uid, Decision.predicate == predicate,
                               Decision.kind.in_(("confirm", "supersede"))).order_by(Decision.seq)
    return [d for d in db.scalars(q) if d.member == member and d.decision_id not in ended]


@ledger_writer
def apply_decisions(db: Session, workspace_id: str, actor: str, batch: list[dict], *,
                    defer_derive: bool = False) -> list[Decision]:
    """Apply a batch of decisions atomically (§7.4). The caller commits; on
    LedgerError it must roll back and may call record_rejected_batch().
    Projection is always synchronous (I-UX-1); with `defer_derive` the
    derive stage is queued and the records show `deriving` until it runs."""
    batch_id = str(uuid.uuid4())
    written: list[Decision] = []
    subjects: set[str] = set()
    for item in batch:
        kind = item.get("kind")
        if kind not in DECISION_KINDS:
            raise LedgerError(f"unknown decision kind {kind!r}")
        target = item.get("target") or {}
        subject = item.get("subject_uid")
        if kind in ("confirm", "supersede"):
            if not subject or not item.get("predicate"):
                raise LedgerError(f"{kind} needs subject_uid and predicate")
            record = db.get(Asset, subject)
            if record is None or record.workspace_id != workspace_id:
                raise LedgerError("the subject is not a record of this workspace")
            _check_installation_immutability(record, item["predicate"])
            from app.ledger.connectivity import check_assignment_decision
            check_assignment_decision(record, item["predicate"], db)
            from app.ledger.registry import enforce_decision
            enforce_decision(db, record, item)
            if kind == "supersede" and not item.get("supersedes"):
                raise LedgerError("supersede must name the confirmations it replaces")
        if kind in ("retract", "revoke") and not target.get("decisions"):
            raise LedgerError(f"{kind} must name decisions")
        for did in (item.get("supersedes") or []) + (target.get("decisions") or []):
            old = db.scalar(select(Decision).where(Decision.decision_id == did))
            if old is None or old.workspace_id != workspace_id:
                raise LedgerError(f"decision {did} is not in this workspace")
            if old.subject_uid:
                subjects.add(old.subject_uid)
        if kind in ("accept", "reject"):
            claim = db.get(Claim, target.get("claim_id")) if target.get("claim_id") else None
            if claim is None and not target.get("fingerprint"):
                raise LedgerError(f"{kind} needs a claim_id or a fingerprint")
            if claim is not None:
                stream = db.get(LedgerStream, claim.stream_id)
                if kind == "reject" and target.get("scope") == "fingerprint":
                    target = {**target, "fingerprint": fingerprint(stream.kind, claim)}
                uid = resolve_ref(db, claim.source_ref)
                subject = subject or uid
        d = _record_decision(db, kind, actor, workspace_id, batch_id=batch_id, subject_uid=subject,
                             predicate=item.get("predicate"), member=item.get("member"), value=item.get("value"),
                             target=target or None, supersedes=item.get("supersedes"), reason=item.get("reason"),
                             effective_at=item.get("effective_at"))
        written.append(d)
        if subject:
            subjects.add(subject)
    for uid in sorted(subjects):
        project_subject(db, uid, f"decision-batch:{batch_id}")
    validate_installations(db, subjects, strict=True)
    from app.ledger.identity import clear_merge_overlaps
    clear_merge_overlaps(db, subjects, f"decision-batch:{batch_id}")
    from app.ledger.connectivity import validate_access_points
    validate_access_points(db, subjects)
    workspaces = _workspaces_of(db, subjects) | {workspace_id}
    if defer_derive:
        request_derive(db, workspaces, f"decision-batch:{batch_id}")
    else:
        derive_all(db, workspaces)
    return written


def record_rejected_batch(db: Session, workspace_id: str, actor: str, batch: list[dict], reason: str) -> None:
    _record_decision(db, "batch_rejected", actor, workspace_id, value={"batch": batch}, reason=reason)


def _check_installation_immutability(record: Asset, predicate: str) -> None:
    if record.type == INSTALLATION and predicate in SINGLE_RELATIONS \
            and (record.attributes or {}).get("installation_status") == "Confirmed":
        raise InvariantError("I-INS-4", "a Confirmed Installation's asset and position cannot change; "
                                        "reject it and record a new one")


# --------------------------------------------------------------------------- projection

def _claims_for_subject(db: Session, uid: str) -> list[tuple[Claim, LedgerStream, bool, Optional[datetime], int]]:
    """Every claim ever made about the subject: (claim, stream, present_at_published_head,
    observed_at of its appearance, seq of its appearance)."""
    refs = [b.source_ref for b in db.scalars(select(IdentityBinding).where(IdentityBinding.uid == uid))]
    refs.append(f"uid:{uid}")
    out = []
    presence_cache: dict[str, dict] = {}
    for c in db.scalars(select(Claim).where(Claim.source_ref.in_(refs))):
        stream = db.get(LedgerStream, c.stream_id)
        if c.stream_id not in presence_cache:
            head = db.get(StreamHead, c.stream_id)
            presence_cache[c.stream_id] = _presence(db, c.stream_id, head.published_number if head else 0)
        present = presence_cache[c.stream_id].get(c.claim_id)
        seq = present["seq"] if present else 10 ** 12
        observed = None
        ev = db.scalar(select(ClaimEvent).where(ClaimEvent.claim_id == c.claim_id, ClaimEvent.kind == "appeared")
                       .order_by(ClaimEvent.seq.desc()).limit(1))
        if ev is not None:
            rev = db.get(SourceRevision, ev.revision_id)
            observed = rev.observed_at if rev else None
            if present:
                seq = present["seq"]
        out.append((c, stream, present is not None, observed, seq))
    return out


def _type_lineage(db: Session, record: Asset) -> tuple[str, ...]:
    names, seen, uid = [], set(), record.schema_uid
    while uid and uid not in seen:
        seen.add(uid)
        s = db.get(Schema, uid)
        if s is None:
            break
        names.append(s.name)
        uid = s.parent_schema_uid
    return tuple(names) or (record.type,)


def _claim_value(c: Claim):
    if c.predicate == "exists" or is_multi(c.predicate):
        return c.polarity
    return c.value


def _decision_value(d: Decision):
    return d.value


@dataclass
class _Outcome:
    effective: object
    has_effective: bool
    statuses: dict            # contributor -> (status, rank, effective)
    conflicts: list           # (type, severity, detail)


@dataclass
class _DecisionContext:
    ended: set
    rejected_claims: set
    rejected_prints: set
    accepted_claims: set


def _decision_context(db: Session, workspace_id: str) -> _DecisionContext:
    ended = _ended(db, workspace_id)
    ctx = _DecisionContext(ended, set(), set(), set())
    for d in db.scalars(select(Decision).where(Decision.workspace_id == workspace_id,
                                               Decision.kind.in_(("reject", "accept")))):
        if d.decision_id in ended:
            continue
        t = d.target or {}
        if d.kind == "reject":
            if t.get("fingerprint"):
                ctx.rejected_prints.add(t["fingerprint"])
            elif t.get("claim_id"):
                ctx.rejected_claims.add(t["claim_id"])
        elif t.get("claim_id"):
            ctx.accepted_claims.add(t["claim_id"])
    return ctx


def _project_key(db: Session, record: Asset, predicate: str, member: Optional[str], claims: list,
                 decisions: list[Decision], policy: Policy, policy_row: LedgerPolicy,
                 dctx: _DecisionContext, lineage: Optional[tuple] = None) -> _Outcome:
    ended = dctx.ended
    rejected_claims, rejected_prints, accepted_claims = dctx.rejected_claims, dctx.rejected_prints, \
        dctx.accepted_claims
    lineage = lineage or _type_lineage(db, record)
    vocab_streams = set(policy_row.vocabulary.get("streams") or [])
    vocab_rules = set(policy_row.vocabulary.get("rules") or [])

    statuses: dict = {}
    eligible = []   # (value, rank, observed, seq, contributor, method)
    # Within one stream, a newer statement about the same fact supersedes the
    # older one (§7.5 rule 5); for a person's stream this is how "add" then
    # "remove" of a set member works.
    newest: dict[str, int] = {}
    for c, stream, present, _o, seq in claims:
        if present:
            newest[stream.id] = max(newest.get(stream.id, -1), seq)
    for c, stream, present, observed, seq in claims:
        if present and seq < newest.get(stream.id, seq):
            statuses[f"claim:{c.claim_id}"] = ("superseded", None, False)
            continue
        contributor = f"claim:{c.claim_id}"
        ctx = ClaimContext(predicate, record.type, lineage, record.workspace_id, stream.facility,
                           (record.attributes or {}).get("argus_system"), stream.kind, stream.id, c.rule_id, c.method)
        effect = policy.select(ctx)
        if not present:
            statuses[contributor] = ("withdrawn", effect.rank, False)
            continue
        external = stream.kind not in INTERNAL_KINDS
        if external and (stream.id not in vocab_streams or (c.rule_id and c.rule_id not in vocab_rules)):
            statuses[contributor] = ("pending", effect.rank, False)
            continue
        if c.claim_id in rejected_claims or fingerprint(stream.kind, c) in rejected_prints:
            statuses[contributor] = ("rejected", effect.rank, False)
            continue
        if effect.rank == "ignored":
            statuses[contributor] = ("ignored", effect.rank, False)
            continue
        if not (effect.auto_accept or c.claim_id in accepted_claims):
            if not [d for d in decisions if d.decision_id not in ended]:
                statuses[contributor] = ("proposed", effect.rank, False)
                continue
            # A person has already decided this fact: the proposal is settled,
            # as agreeing (accepted) or not (outranked), below.
        eligible.append((_claim_value(c), effect.rank, observed, seq, contributor, c.method))
        statuses[contributor] = ("accepted", effect.rank, False)

    conflicts: list = []
    active = [d for d in decisions if d.decision_id not in ended]
    for d in decisions:
        if d.decision_id in ended:
            statuses[f"decision:{d.decision_id}"] = ("superseded", "confirmed", False)
    if active:
        values = []
        for d in active:
            if canonical(d.value) not in [canonical(v) for v in values]:
                values.append(d.value)
        eff = active[0].value
        if len(values) > 1:
            conflicts.append(("confirmed_vs_confirmed", "blocking",
                              {"values": values, "decisions": [d.decision_id for d in active]}))
        for d in active:
            statuses[f"decision:{d.decision_id}"] = ("confirmed", "confirmed", canonical(d.value) == canonical(eff))
        disagreeing = [v for (v, rank, *_rest, method) in eligible
                       if method != "manual" and rank in ("authoritative", "contributory")
                       and canonical(v) != canonical(eff)]
        if disagreeing:
            conflicts.append(("source_vs_confirmed", "non-blocking",
                              {"confirmed": eff, "sources": disagreeing}))
        for v, rank, _o, _s, contributor, _m in eligible:
            agrees = canonical(v) == canonical(eff)
            statuses[contributor] = ("accepted" if agrees else "outranked", rank, agrees)
        return _Outcome(eff, True, statuses, conflicts)

    if not eligible:
        return _Outcome(None, False, statuses, conflicts)
    best_rank = min(RANK_ORDER[r] for _v, r, *_ in eligible)
    top = [e for e in eligible if RANK_ORDER[e[1]] == best_rank]
    distinct = []
    for e in top:
        if canonical(e[0]) not in [canonical(x) for x in distinct]:
            distinct.append(e[0])
    if len(distinct) == 1:
        eff = distinct[0]
    elif top[0][1] == "authoritative":
        # The status quo holds: the value that appeared first.
        eff = min(top, key=lambda e: e[3])[0]
        conflicts.append(("authority_vs_authority", "blocking", {"values": distinct}))
    else:
        eff = max(top, key=lambda e: (e[2] or temporal.NEG_INF, e[3]))[0]
        conflicts.append(("contributory_disagreement", "non-blocking", {"values": distinct}))
    for v, rank, _o, _s, contributor, _m in eligible:
        wins = RANK_ORDER[rank] == best_rank and canonical(v) == canonical(eff)
        statuses[contributor] = ("accepted" if wins else "outranked", rank, wins)
    return _Outcome(eff, True, statuses, conflicts)


@ledger_writer
def project_subject(db: Session, uid: str, cause: str, *, emit: bool = True) -> None:
    """Recompute every fact of one record from the ledger and write the
    projection: attributes, ledger edges, record status, fact state, conflicts."""
    record = db.get(Asset, uid)
    if record is None:
        return
    policy, policy_row = active_policy(db)
    dctx = _decision_context(db, record.workspace_id)
    claims = _claims_for_subject(db, uid)
    keys: dict[tuple, list] = defaultdict(list)
    for entry in claims:
        c = entry[0]
        keys[(c.predicate, c.member)].append(entry)
    decisions_by_key: dict[tuple, list] = defaultdict(list)
    for d in db.scalars(select(Decision).where(Decision.subject_uid == uid,
                                               Decision.kind.in_(("confirm", "supersede")))
                        .order_by(Decision.seq)):
        decisions_by_key[(d.predicate, d.member)].append(d)
        keys.setdefault((d.predicate, d.member), [])

    old_states = {(f.predicate, f.member, f.contributor): f.status
                  for f in db.scalars(select(FactState).where(FactState.subject_uid == uid))}
    db.execute(delete(FactState).where(FactState.subject_uid == uid))
    attrs = dict(record.attributes or {})
    multi_members: dict[str, dict] = defaultdict(dict)
    desired_edges: set[tuple] = set()
    managed_attrs: set[str] = set()
    exists_outcome: Optional[_Outcome] = None
    new_conflicts: dict[str, tuple] = {}
    type_fact = None                    # None: no type statement; False: none in effect; else the type

    lineage = _type_lineage(db, record)
    for (predicate, member), entries in keys.items():
        outcome = _project_key(db, record, predicate, member, entries, decisions_by_key[(predicate, member)],
                               policy, policy_row, dctx, lineage)
        for contributor, (status, rank, effective) in outcome.statuses.items():
            db.add(FactState(subject_uid=uid, predicate=predicate, member=member, contributor=contributor,
                             status=status, rank=rank, effective=effective))
            before = old_states.get((predicate, member, contributor))
            if emit and before != status:
                db.add(StatusEvent(subject_uid=uid, predicate=predicate, member=member, contributor=contributor,
                                   from_status=before, to_status=status, cause=cause,
                                   projector_version=PROJECTOR_VERSION, at=now()))
        for ctype, severity, detail in outcome.conflicts:
            cid = hashlib.sha256(canonical([ctype, uid, predicate, member]).encode()).hexdigest()[:24]
            new_conflicts[cid] = (ctype, severity, predicate, member, detail)
        if predicate == "exists":
            exists_outcome = outcome
        elif predicate == "name":
            if outcome.has_effective and outcome.effective:
                record.name = outcome.effective
        elif predicate == "type":
            type_fact = outcome.effective if outcome.has_effective and outcome.effective else False
        elif predicate.startswith("attr:"):
            name = predicate[5:]
            managed_attrs.add(name)
            if is_multi(predicate):
                multi_members[name][member] = outcome.has_effective and outcome.effective == "present"
            elif outcome.has_effective and outcome.effective is not None:
                attrs[name] = outcome.effective
            else:
                attrs.pop(name, None)
        elif predicate.startswith("rel:"):
            rel = predicate[4:]
            if predicate in SINGLE_RELATIONS:
                if outcome.has_effective and isinstance(outcome.effective, dict):
                    target = resolve_ref(db, outcome.effective.get("ref", ""))
                    if target:
                        desired_edges.add((rel, target))
            elif outcome.has_effective and outcome.effective == "present" and member:
                target = resolve_ref(db, member)
                if target:
                    desired_edges.add((rel, target))
    for name, members in multi_members.items():
        present = sorted(m for m, on in members.items() if on)
        values = []
        for m in present:
            try:
                parsed = json.loads(m)
            except (TypeError, ValueError):
                parsed = m
            if isinstance(parsed, list):
                # A legacy claim from before callers decomposed a multi-value attribute into one
                # present/absent statement per member (service.py): its member is the whole list's own
                # hash, not one item's, so it would otherwise reassemble as a list containing that
                # whole list — e.g. ["beam", "optics"] read back as [["beam", "optics"]]. Unwrap it.
                values.extend(parsed)
            else:
                values.append(parsed)
        try:
            values = list(dict.fromkeys(values))  # de-duplicate: a legacy claim may repeat a member
                                                   # a newer, properly-decomposed claim already carries
        except TypeError:
            pass                                  # an unhashable member (shouldn't happen): keep as-is
        if values:
            attrs[name] = values
        else:
            attrs.pop(name, None)

    desired_edges |= reference_edges(db, uid, attrs)
    if type_fact is not None:
        _write_type(db, record, type_fact, cause, emit)
    _write_edges(db, uid, desired_edges)
    _write_record_status(db, record, exists_outcome, attrs, cause, new_conflicts)
    record.attributes = attrs
    db.flush()
    _write_conflicts(db, record, new_conflicts, cause, emit)


def reference_edges(db: Session, uid: str, attrs: dict) -> set[tuple]:
    """The edges a record's reference fields mean (asset_types.REFERENCE_RELATIONS): a Product Model reference
    is `instance of` it. Derived from the field, so they come and go with it."""
    from app.services.asset_types import REFERENCE_RELATIONS
    out = set()
    for name, verb in REFERENCE_RELATIONS.items():
        value = attrs.get(name)
        for target in (value if isinstance(value, list) else [value]):
            if isinstance(target, str) and target and target != uid and db.get(Asset, target) is not None:
                out.add((verb, target))
    return out


def _original_type(db: Session, record: Asset) -> dict:
    """The type the record had before a type statement last took effect: the
    `before` of the first event in the latest run of statement-driven retypes
    (a promotion in between starts a new run) — its name and, where recorded, its uid."""
    start = None
    for e in db.scalars(select(RecordEvent).where(RecordEvent.uid == record.uid, RecordEvent.kind == "retyped")
                        .order_by(RecordEvent.seq)):
        if (e.after or {}).get("by") == "type statement":
            start = start or e
        else:
            start = None
    before = (start.before or {}) if start is not None else {}
    return {"name": before.get("type", record.type), "schema_uid": before.get("schema_uid")}


def _type_target(db: Session, record: Asset, type_fact) -> tuple[str, Optional[str]]:
    """What a type statement names: a type's name, or (since type migrations) its identity —
    `{"name": …, "schema_uid": …}` — which is used as such, never looked up again by name."""
    if isinstance(type_fact, dict):
        uid = type_fact.get("schema_uid")
        schema = db.get(Schema, uid) if uid else None
        # The identity is used when it is the type named (a direct promotion can leave a record's name and
        # uid out of step: then the name, as before).
        if schema is not None and (not type_fact.get("name") or schema.name == type_fact["name"]):
            return schema.name, schema.uid
        return str(type_fact.get("name") or record.type), None
    return str(type_fact), None


def _write_type(db: Session, record: Asset, type_fact, cause: str, emit: bool) -> None:
    """A confirmed `type` statement retypes the record in place (same uid and
    key). With none in effect (revoked), it goes back to its original type."""
    wanted, wanted_uid = _type_target(db, record, type_fact or _original_type(db, record))
    if wanted == record.type and wanted_uid in (None, record.schema_uid):
        return
    before = {"type": record.type, "schema_uid": record.schema_uid}
    record.type = wanted
    record.schema_uid = wanted_uid or ensure_type(db, record.workspace_id, wanted).uid
    if emit:
        db.add(RecordEvent(uid=record.uid, kind="retyped", before=before,
                           after={"type": wanted, "schema_uid": record.schema_uid,
                                  "by": "type statement" if type_fact else "type statement revoked"},
                           cause=cause, at=now()))


def _write_edges(db: Session, uid: str, desired: set[tuple]) -> None:
    current = {(r.relation_type, r.to_asset_uid): r for r in db.scalars(
        select(Relation).where(Relation.from_asset_uid == uid, Relation.derivation == "ledger"))}
    record = db.get(Asset, uid)
    for key, row in current.items():
        if key not in desired:
            db.delete(row)
    for rel, target in desired - set(current):
        db.add(Relation(workspace_id=record.workspace_id, from_asset_uid=uid, to_asset_uid=target,
                        relation_type=rel, derivation="ledger", rule=PROJECTOR_VERSION))
    db.flush()


def _write_record_status(db: Session, record: Asset, outcome: Optional[_Outcome], attrs: dict, cause: str,
                         conflicts: dict) -> None:
    if outcome is None:
        return
    statuses = {s for s, _r, _e in outcome.statuses.values()}
    if outcome.has_effective and outcome.effective == "present":
        confirmed = any(k.startswith("decision:") and s == "confirmed" for k, (s, _r, _e) in outcome.statuses.items())
        new_status = "Active"
        if record.type == INSTALLATION:
            attrs["installation_status"] = "Confirmed" if confirmed else "Proposed"
    elif "proposed" in statuses or "pending" in statuses:
        new_status = "Provisional"
        if record.type == INSTALLATION:
            attrs["installation_status"] = "Proposed"
    else:
        new_status = "Retired"
        if record.type == INSTALLATION:
            attrs["installation_status"] = "Rejected" if "rejected" in statuses else "Withdrawn"
        if record.type in INSTALLABLE and _current_confirmed_installation(db, record.uid):
            # A position the hardware still occupies is flagged, not retired (I-RET-2).
            new_status = "Active"
            cid = hashlib.sha256(canonical(["retirement_blocked", record.uid]).encode()).hexdigest()[:24]
            conflicts[cid] = ("retirement_blocked", "non-blocking", "exists", None,
                              {"reason": "the source no longer states this position, "
                                         "but a Confirmed Installation is current"})
    if new_status != record.record_status:
        db.add(RecordEvent(uid=record.uid, kind="status", before=record.record_status, after=new_status,
                           cause=cause, at=now()))
        record.record_status = new_status


# Review items the validate and derive stages own; projection leaves them alone.
DERIVED_CONFLICTS = ("possible_overlap", "port_mapping_unresolved", "port_confirmation_required", "port_map_invalid",
                     "identity_candidate", "merge_installation_overlap",
                     "stale_command",      # opened by app.services.versions, closed by a person
                     "replacement_proposal", "outgoing_discrepancy",   # app.ledger.replacement
                     "retirement_candidate")                           # app.integrations.glpi


def _write_conflicts(db: Session, record: Asset, new: dict, cause: str, emit: bool) -> None:
    existing = {c.conflict_id: c for c in db.scalars(select(Conflict).where(
        Conflict.subject_uid == record.uid, Conflict.conflict_type.notin_(DERIVED_CONFLICTS)))}
    for cid, (ctype, severity, predicate, member, detail) in new.items():
        if cid in existing:
            existing[cid].detail = detail
            continue
        seq = 0
        if emit:
            ev = ConflictEvent(conflict_id=cid, kind="opened", conflict_type=ctype, subject_uid=record.uid,
                               predicate=predicate, member=member, detail=detail, cause=cause, at=now())
            db.add(ev)
            db.flush()
            seq = ev.seq
        db.add(Conflict(conflict_id=cid, conflict_type=ctype, severity=severity, workspace_id=record.workspace_id,
                        subject_uid=record.uid, predicate=predicate, member=member, detail=detail, opened_seq=seq))
    for cid, row in existing.items():
        if cid not in new:
            if emit:
                db.add(ConflictEvent(conflict_id=cid, kind="resolved", conflict_type=row.conflict_type,
                                     subject_uid=record.uid, predicate=row.predicate, member=row.member,
                                     detail=row.detail, cause=cause, at=now()))
            db.delete(row)
    db.flush()


# --------------------------------------------------------------------------- installations

def installation_view(db: Session, inst: Asset) -> dict:
    a = inst.attributes or {}
    position = equipment = None
    for r in db.scalars(select(Relation).where(Relation.from_asset_uid == inst.uid, Relation.derivation == "ledger")):
        if r.relation_type == "installed at":
            position = r.to_asset_uid
        elif r.relation_type == "installation of":
            equipment = r.to_asset_uid
    iv = temporal.interval(a.get("valid_from"), a.get("valid_until"))
    return {"uid": inst.uid, "key": inst.key, "position_uid": position, "asset_uid": equipment,
            "status": a.get("installation_status", "Proposed"), "valid_from": a.get("valid_from"),
            "valid_until": a.get("valid_until"), "interval": iv, "removal_reason": a.get("removal_reason"),
            "workspace_id": inst.workspace_id, "record_status": inst.record_status}


def installations(db: Session, *, position_uid: Optional[str] = None, asset_uid: Optional[str] = None,
                  status: Optional[str] = None) -> list[dict]:
    rel_type = "installed at" if position_uid else "installation of"
    target = position_uid or asset_uid
    q = select(Asset).where(Asset.type == INSTALLATION)
    if target:
        q = q.join(Relation, Relation.from_asset_uid == Asset.uid).where(
            Relation.relation_type == rel_type, Relation.to_asset_uid == target, Relation.derivation == "ledger")
    out = [installation_view(db, i) for i in db.scalars(q)]
    if status:
        out = [v for v in out if v["status"] == status]
    return sorted(out, key=lambda v: v["interval"].start.earliest)


def installations_at(db: Session, t, *, position_uid: Optional[str] = None,
                     asset_uid: Optional[str] = None) -> list[dict]:
    """What was installed at time t (valid time), with a certainty."""
    t = temporal.parse_instant(t)
    out = []
    for v in installations(db, position_uid=position_uid, asset_uid=asset_uid, status="Confirmed"):
        c = temporal.covers(v["interval"], t)
        if c != "none":
            out.append({**v, "certainty": c})
    return out


def _current_confirmed_installation(db: Session, position_uid: str) -> Optional[dict]:
    hits = installations_at(db, now(), position_uid=position_uid)
    return hits[0] if hits else None


def validate_installations(db: Session, subjects: Iterable[str], *, strict: bool) -> None:
    """I-INS-1/2/3/6 for every position and asset touched by these subjects."""
    positions, assets = set(), set()
    for uid in subjects:
        rec = db.get(Asset, uid)
        if rec is None:
            continue
        if rec.type == INSTALLATION:
            v = installation_view(db, rec)
            if v["position_uid"]:
                positions.add(v["position_uid"])
            if v["asset_uid"]:
                assets.add(v["asset_uid"])
        else:
            positions.add(uid)
            assets.add(uid)
    groups = [installations(db, position_uid=p, status="Confirmed") for p in positions] + \
             [installations(db, asset_uid=a, status="Confirmed") for a in assets]
    possible_pairs = set()
    touched = set()
    for group in groups:
        for v in group:
            touched.add(v["uid"])
            try:
                temporal.validate(v["interval"])
            except temporal.TemporalError as exc:
                raise InvariantError("I-INS-3", f"{v['key']}: {exc}")
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                kind = temporal.overlap(a["interval"], b["interval"])
                if kind == "definite":
                    same_pos = a["position_uid"] == b["position_uid"]
                    code = "I-INS-2" if same_pos else "I-INS-1"
                    raise InvariantError(code, f"{a['key']} and {b['key']} overlap "
                                               f"({'one unit per position' if same_pos else 'one place per unit'})")
                if kind == "possible":
                    possible_pairs.add(tuple(sorted((a["uid"], b["uid"]))))
    for uid in touched:
        rec = db.get(Asset, uid)
        mine = [p for p in possible_pairs if uid in p]
        wanted = {hashlib.sha256(canonical(["possible_overlap", uid, *p]).encode()).hexdigest()[:24]: p
                  for p in mine}
        existing = {c.conflict_id: c for c in db.scalars(select(Conflict).where(
            Conflict.subject_uid == uid, Conflict.conflict_type == "possible_overlap"))}
        for cid, pair in wanted.items():
            if cid not in existing:
                ev = ConflictEvent(conflict_id=cid, kind="opened", conflict_type="possible_overlap", subject_uid=uid,
                                   detail={"installations": list(pair)}, cause="validation", at=now())
                db.add(ev)
                db.flush()
                db.add(Conflict(conflict_id=cid, conflict_type="possible_overlap", severity="non-blocking",
                                workspace_id=rec.workspace_id, subject_uid=uid, detail={"installations": list(pair)},
                                opened_seq=ev.seq))
        for cid, row in existing.items():
            if cid not in wanted:
                db.add(ConflictEvent(conflict_id=cid, kind="resolved", conflict_type="possible_overlap",
                                     subject_uid=uid, detail=row.detail, cause="validation", at=now()))
                db.delete(row)
        attrs = dict(rec.attributes or {})
        if mine:
            attrs["temporal_uncertain"] = True
        else:
            attrs.pop("temporal_uncertain", None)
        rec.attributes = attrs
    db.flush()


def request_derive(db: Session, workspace_ids: Iterable[str], cause: str) -> DeriveRequest:
    """Queue a derive run (D10: derive is asynchronous for user edits)."""
    req = DeriveRequest(workspace_ids=sorted(set(workspace_ids)), cause=cause, status="pending", requested_at=now())
    db.add(req)
    db.flush()
    return req


def process_derive_requests(db: Session) -> int:
    """Run every pending derive request, oldest first; returns how many ran."""
    pending = list(db.scalars(select(DeriveRequest).where(DeriveRequest.status == "pending")
                              .order_by(DeriveRequest.id).with_for_update(skip_locked=True)))
    if not pending:
        return 0
    derive_all(db, {w for r in pending for w in r.workspace_ids})
    for r in pending:
        r.status, r.done_at = "done", now()
    db.flush()
    return len(pending)


def pending_derive(db: Session, workspace_id: str) -> Optional[dict]:
    """The processing state a record shows while derive is queued (I-UX-1)."""
    for r in db.scalars(select(DeriveRequest).where(DeriveRequest.status == "pending").order_by(DeriveRequest.id)):
        if workspace_id in (r.workspace_ids or []):
            return {"state": "deriving", "since": r.requested_at, "request": r.id}
    return None


@ledger_writer
def derive_all(db: Session, workspace_ids: Optional[Iterable[str]] = None) -> dict:
    """The derive stage: `realized by`, `implemented by`, `located in`, port
    attachment and ticket attribution."""
    from app.ledger import connectivity, tickets
    ids = None if workspace_ids is None else list(set(workspace_ids))
    out = derive_realized_by(db, ids)
    out.update(derive_located_in(db, ids))
    out.update(derive_in_work_package(db, ids))
    out.update(connectivity.derive_implemented_by(db, ids))
    from app.ledger.control_binding import derive_drives
    out.update(derive_drives(db, ids))
    out.update(connectivity.derive_ports(db, ids))
    out.update(tickets.derive_ticket_links(db, workspace_ids=ids))
    return out


def derive_realized_by(db: Session, workspace_ids: Optional[Iterable[str]] = None) -> dict:
    """Derived `realized by` edges: position -> the unit of its definitely
    Current, Confirmed Installation (I-PROJ-2). Installations live in their
    position's workspace, so a workspace is derived on its own."""
    wanted: set[tuple] = set()
    t = now()
    q = select(Asset).where(Asset.type == INSTALLATION)
    rq = select(Relation).where(Relation.derivation == "derived", Relation.relation_type == "realized by")
    if workspace_ids is not None:
        ids = list(set(workspace_ids))
        q = q.where(Asset.workspace_id.in_(ids))
        rq = rq.where(Relation.workspace_id.in_(ids))
    for v in [installation_view(db, i) for i in db.scalars(q)]:
        if v["status"] == "Confirmed" and v["position_uid"] and v["asset_uid"] \
                and temporal.covers(v["interval"], t) == "definite":
            wanted.add((v["position_uid"], v["asset_uid"]))
    current = {(r.from_asset_uid, r.to_asset_uid): r for r in db.scalars(rq)}
    for key, row in current.items():
        if key not in wanted:
            db.delete(row)
    for pos, unit in wanted - set(current):
        record = db.get(Asset, pos)
        db.add(Relation(workspace_id=record.workspace_id, from_asset_uid=pos, to_asset_uid=unit,
                        relation_type="realized by", derivation="derived", rule="realized-by/1"))
    db.flush()
    return {"realized_by": len(wanted)}


LOCATION_TYPES = {"Location", "Room", "Rack", "Building", "Area", "Storage"}


def derive_located_in(db: Session, workspace_ids: Optional[Iterable[str]] = None) -> dict:
    """`located in` (derived): a record whose `argus_location` names a
    Location record — by key or name, in its own workspace first — points
    at it. The value stays the fact; the edge follows it."""
    q = select(Asset).where(Asset.attributes["argus_location"].astext.isnot(None))
    rq = select(Relation).where(Relation.derivation == "derived", Relation.relation_type == "located in")
    if workspace_ids is not None:
        ids = list(set(workspace_ids))
        q = q.where(Asset.workspace_id.in_(ids))
        rq = rq.where(Relation.workspace_id.in_(ids))
    locations: dict[str, list[Asset]] = defaultdict(list)
    for loc in db.scalars(select(Asset).where(Asset.type.in_(LOCATION_TYPES), Asset.record_status != "Retired")):
        for label in {loc.key, loc.name}:
            if label:
                locations[label.strip().lower()].append(loc)
    wanted: dict[tuple, str] = {}
    for a in db.scalars(q):
        value = (a.attributes or {}).get("argus_location")
        hits = locations.get(str(value).strip().lower(), []) if isinstance(value, str) else []
        hits = sorted(hits, key=lambda loc: (loc.workspace_id != a.workspace_id, loc.key or ""))
        if hits and hits[0].uid != a.uid:
            wanted[(a.uid, hits[0].uid)] = a.workspace_id
    current = {(r.from_asset_uid, r.to_asset_uid): r for r in db.scalars(rq)}
    for key, row in current.items():
        if key not in wanted:
            db.delete(row)
    for (frm, to), ws in wanted.items():
        if (frm, to) not in current:
            db.add(Relation(workspace_id=ws, from_asset_uid=frm, to_asset_uid=to, relation_type="located in",
                            derivation="derived", rule="located-in/1"))
    db.flush()
    return {"located_in": len(wanted)}


def derive_in_work_package(db: Session, workspace_ids: Optional[Iterable[str]] = None) -> dict:
    """`in work package` (derived, §6.2): a record whose `work_package` names a
    Work Package record, by uid or key, points at it. The attribute is the
    fact; the edge follows it (it replaced the old `assigned to`)."""
    q = select(Asset).where(Asset.attributes["work_package"].astext.isnot(None))
    rq = select(Relation).where(Relation.derivation == "derived", Relation.relation_type == "in work package")
    if workspace_ids is not None:
        ids = list(set(workspace_ids))
        q = q.where(Asset.workspace_id.in_(ids))
        rq = rq.where(Relation.workspace_id.in_(ids))
    wanted: dict[tuple, str] = {}
    for a in db.scalars(q):
        value = (a.attributes or {}).get("work_package")
        if not isinstance(value, str):
            continue
        wp = db.get(Asset, value) or db.scalar(select(Asset).where(Asset.key == value))
        if wp is not None and wp.type == "Work Package" and wp.record_status != "Retired" and wp.uid != a.uid:
            wanted[(a.uid, wp.uid)] = a.workspace_id
    current = {(r.from_asset_uid, r.to_asset_uid): r for r in db.scalars(rq)}
    for key, row in current.items():
        if key not in wanted:
            db.delete(row)
    for (frm, to), ws in wanted.items():
        if (frm, to) not in current:
            db.add(Relation(workspace_id=ws, from_asset_uid=frm, to_asset_uid=to, relation_type="in work package",
                            derivation="derived", rule="in-work-package/1"))
    db.flush()
    return {"in_work_package": len(wanted)}


# --------------------------------------------------------------------------- resolve

def _workspaces_of(db: Session, uids: Iterable[str]) -> set[str]:
    return {a.workspace_id for uid in uids if (a := db.get(Asset, uid)) is not None}


def run_resolvers(db: Session, stream: LedgerStream, changed: set[str]) -> None:
    """Rerun the resolvers a publication can affect: the stream's own
    workspace, and — for an inventory — every workspace whose configuration
    points at one of the objects that changed."""
    from app.ledger.sources import resolve_installations, workspaces_referencing
    workspaces = {stream.workspace_id} if stream.kind == "epik8s" else set()
    if stream.kind == "insight":
        workspaces |= workspaces_referencing(db, [db.get(Claim, cid) for cid in changed])
    for ws in sorted(workspaces):
        resolve_installations(db, ws)


# --------------------------------------------------------------------------- rebuild

def snapshot(db: Session, workspace_id: str) -> dict:
    records = {a.uid: (a.record_status, canonical(a.attributes or {}))
               for a in db.scalars(select(Asset).where(Asset.workspace_id == workspace_id))}
    edges = sorted((r.from_asset_uid, r.relation_type, r.to_asset_uid, r.derivation)
                   for r in db.scalars(select(Relation).where(Relation.workspace_id == workspace_id,
                                                              Relation.derivation.isnot(None))))
    conflicts = sorted((c.conflict_id, c.conflict_type) for c in db.scalars(
        select(Conflict).where(Conflict.workspace_id == workspace_id)))
    return {"records": records, "edges": edges, "conflicts": conflicts}


@ledger_writer
def rebuild(db: Session, workspace_id: str) -> None:
    """Drop the projections of a workspace's ledger records and recompute them
    from audit data alone (A16). No events are written."""
    uids = [a.uid for a in db.scalars(select(Asset).where(Asset.workspace_id == workspace_id))
            if db.scalar(select(IdentityBinding).where(IdentityBinding.uid == a.uid).limit(1))
            or db.scalar(select(Decision).where(Decision.subject_uid == a.uid).limit(1))]
    for uid in uids:
        managed = {"installation_status", "temporal_uncertain"}
        refs = [b.source_ref for b in db.scalars(select(IdentityBinding).where(IdentityBinding.uid == uid))]
        for c in db.scalars(select(Claim).where(Claim.source_ref.in_(refs + [f"uid:{uid}"]))):
            if c.predicate.startswith("attr:"):
                managed.add(c.predicate[5:])
        for d in db.scalars(select(Decision).where(Decision.subject_uid == uid)):
            if d.predicate and d.predicate.startswith("attr:"):
                managed.add(d.predicate[5:])
        db.execute(delete(FactState).where(FactState.subject_uid == uid))
        db.execute(delete(Conflict).where(Conflict.subject_uid == uid))
        db.execute(delete(Relation).where(Relation.from_asset_uid == uid, Relation.derivation.isnot(None)))
        rec = db.get(Asset, uid)
        # Only what the ledger manages is cleared: an adopted legacy record
        # keeps the attributes nobody has claimed yet.
        rec.attributes = {k: v for k, v in (rec.attributes or {}).items() if k not in managed}
    db.flush()
    for _ in range(2):   # installations need their edges before their subjects' status
        for uid in uids:
            project_subject(db, uid, "rebuild", emit=False)
    validate_installations(db, uids, strict=False)
    from app.ledger.identity import detect_candidates
    detect_candidates(db, uids, "rebuild")
    derive_all(db, [workspace_id])
