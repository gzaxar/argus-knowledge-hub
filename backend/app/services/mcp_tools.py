"""The hub's knowledge, as tools an assistant can call.

ARGUS can already search document text through RAGFlow and read logs
through Loki. What it cannot do is the question the project exists to
answer — "what broke this magnet before, and which procedure covers it" —
because that is a traversal and two structured lookups, and the answer is
in no single document.

These are read-only on purpose. An assistant that can change the
inventory is a different proposal needing a different conversation about
who is accountable for the change; retrieval is where the value is and
where the risk is not.
"""
import json
import re
from collections import Counter
from typing import Any, Callable, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.asset import Asset, Relation
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.models.issue import Issue, IssueComment
from app.models.llm_config import LLMConfig
from app.models.schema import Schema
from app.models.user import User
from app.models.workspace import Workspace
from app.services import causal_model
from app.services.knowledge_graph import graph_summary, traverse
from app.services.alarm_symptoms import root_cause_from_alarms as _root_cause_from_alarms
from app.services.root_cause import blast_radius as _blast_radius
from app.services.root_cause import impact_of as _impact_of
from app.services.root_cause import root_causes as _root_causes
from app.services.visibility import (can_see, live_assets_clause, redacted_attributes, restriction_clause,
                                     visible_assets_clause, visible_issues_clause)

# Enough to answer with, small enough not to bury the model.
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
DOCUMENT_CHARS = 6000


def _confidential_allowed(db: Session, workspace_id: str) -> bool:
    """Whether documents marked riservato may be returned here.

    The same switch that governs sending text to a model, because that is
    exactly what this does — the caller on the other end of an MCP tool is
    an assistant, not a person reading one page.
    """
    config = db.get(LLMConfig, workspace_id)
    return bool(config and config.allow_confidential)


def _asset_visible(db: Session, asset: Asset, workspace_id: str) -> bool:
    """The same rule as the REST API and the graph: this workspace's own
    objects, plus whatever is shared with it.

    An installation that keeps device models in a global workspace needs
    them here too, or "what model is this camera" is unanswerable in the
    tool built to answer it.
    """
    return (asset.workspace_id == workspace_id or bool(asset.is_global)) and can_see(asset)


def _document_visible(workspace_id: str):
    """This workspace's documentation, plus whatever is shared with it.

    A global workspace holding the procedures that cover every beamline is
    only worth having if the tools can read them from the beamline asking
    the question.
    """
    return or_(
        Document.workspace_id == workspace_id,
        and_(Document.is_global.is_(True), Document.confidentiality != "riservato"),
    )


def _asset_summary(asset: Asset) -> dict:
    out = {
        "uid": asset.uid,
        "key": asset.key,
        "name": asset.name,
        "type": asset.type,
    }
    if asset.record_status != "Active":       # said, so an answer never presents a retired record as current
        out["status"] = asset.record_status
    model = (asset.attributes or {}).get("beam_model")
    if model:                                 # where a beam element sits: one model is one line or ring
        out["model"] = model
    return out


def _issue_summary(issue: Issue, asset: Optional[Asset] = None) -> dict:
    attributes = issue.attributes or {}
    out = {
        "uid": issue.uid,
        "key": issue.key,
        "title": issue.title,
        "state": issue.state,
        "created": issue.created_at.date().isoformat() if issue.created_at else None,
        "source_key": attributes.get("argus_source_key"),
        "category": attributes.get("argus_category"),
        "impact": attributes.get("argus_impact"),
    }
    if asset is not None and can_see(asset):
        out["on"] = asset.key or asset.uid
    return out


def _document_summary(document: Document, type_name: Optional[str]) -> dict:
    return {
        "uid": document.uid,
        "code": document.code,
        "title": document.title,
        "type": type_name,
    }


# --- the tools ----------------------------------------------------------

def _singular(word: str) -> str:
    """'magnets' → 'magnet', 'supplies' → 'supply', 'boxes' → 'box': what a person types is a plural."""
    w = word.strip().lower()
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith(("ches", "shes", "xes", "sses")):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    return w


# Words a question is made of, not what it is about: "dipoles in the accumulator" asks about two things.
_NOT_SEARCHED = frozenset({"the", "and", "for", "with", "from", "all", "any", "nel", "nella", "dell", "della", "del",
                           "dei", "degli", "delle", "con", "per"})


def _search_words(needle: str) -> list[str]:
    """The words of a query that has several; none for a single word, which is matched as it is."""
    words = [w for w in re.split(r"\s+", needle) if len(w) > 2 and w not in _NOT_SEARCHED]
    return words if len(needle.split()) > 1 else []


def _types(db: Session, workspace_id: str) -> list[dict]:
    from app.services.type_catalogue import catalogue as type_catalogue
    return type_catalogue(db, workspace_id, classes=False)["types"]


def _with_subtypes(types: list[dict], names: set) -> set:
    """The named types and every type below them: a Vacuum Pump is an Ion Pump or a Turbo Pump."""
    return {t["name"] for t in types if names & set(t["path"])}


def _named(types: list[dict], word: str) -> set:
    """Types a word names: by type name or an alias, ignoring case and plurals."""
    w = _singular(word)
    return {t["name"] for t in types
            if w and (w == _singular(t["name"]) or w in t["name"].lower()
                      or any(w == _singular(a) for a in t.get("aliases") or []))}


def _first_sentence(text: Optional[str]) -> str:
    return (text or "").split(". ")[0].strip()[:160]


def _mentioning(types: list[dict], word: str) -> list[dict]:
    """Types whose description mentions the word ('A focusing magnet.'): suggestions only, because a
    description also mentions what a type is *not* ('powers a magnet')."""
    w = re.escape(_singular(word))
    return [{"name": t["name"], "description": _first_sentence(t["description"]),
             "records": t["records_with_subtypes"]}
            for t in types if re.search(rf"\b{w}(e?s)?\b", _first_sentence(t["description"]), re.I)]


# How to look equipment up and count it. Said to Ask ARGUS's model and to an MCP client's: the same records
# have to give the same answer whoever asks.
LOOKUP_GUIDE = (
    "Names here are codes: equipment is called things like FI4-B-CAM-VIS-001, and the "
    "word somebody uses ('camera', 'quadrupole') is usually the type rather than the "
    "name. If a search finds nothing, try the word as a type, or a shorter fragment, "
    "before concluding there is none.\n"
    "A kind of equipment is often several types, organised in a tree, and none of them may "
    "carry the word used in the question. When you are not sure which types a word means, "
    "call list_types (with the word, or with nothing to see every type), choose the types "
    "whose descriptions match, and search_objects with types=[...]. For a question about "
    "what there is or how many, give the total and the count per type from by_type, not "
    "just the objects listed. List at most 40 records; when there are more, say how many "
    "more there are rather than stopping part way.\n"
    "Count what was asked about. A magnet, its power supply and the control channel of that supply are three "
    "different records, and one supply may power several magnets (the relation `powers`): how many dipoles "
    "there are is the number of Dipole records, however few supplies feed them. A beam element's `model` says "
    "which line or ring it belongs to.\n"
)


def search_objects(db: Session, workspace_id: str, query: str = "",
                   type: Optional[str] = None, types: Optional[list] = None,
                   limit: int = DEFAULT_LIMIT, offset: int = 0, with_attributes: bool = False,
                   include_retired: bool = False) -> dict:
    """Equipment by name, key or type. A type includes its subtypes; a word that names a type matches
    the objects of that type and of the types below it. Returns the total and the count per type, so a
    question about how many there are is answered from all of them, not from the first page.

    `offset` and `with_attributes` are for a client listing every object of a type (ARGUS reading a
    beamline's Control Devices): page after page in a stable order, each object with the attributes
    get_object would give it, instead of one get_object call per object.

    Retired and merged records are left out unless `include_retired` asks for them: they no longer exist as far
    as a question about what is there goes."""
    needle = (query or "").strip().lower()
    catalogue = _types(db, workspace_id)
    asked = [x for x in ([type] if type else []) + list(types or []) if isinstance(x, str) and x.strip()]
    wanted: Optional[set] = None
    unknown = []
    if asked:
        wanted = set()
        for name in asked:
            named = _named(catalogue, name)
            if not named:
                unknown.append(name)
            wanted |= named
        wanted = _with_subtypes(catalogue, wanted)
        if not wanted:
            return {"total": 0, "objects": [], "unknown_types": unknown,
                    "hint": "No type has that name here. Call list_types to see the types, or search by text."}
    by_word = _with_subtypes(catalogue, _named(catalogue, needle)) if needle else set()
    # The rule the REST API and the graph apply: this workspace's objects and the ones flagged shared. An
    # object of a shared *type* is not itself shared — every beamline's pumps are of the catalogue's type.
    stmt = select(Asset).where(visible_assets_clause(workspace_id), Asset.deleted_at.is_(None))
    if not include_retired:
        stmt = stmt.where(live_assets_clause())
    if wanted is not None:
        stmt = stmt.where(Asset.type.in_(wanted))
    # The type counts as a match. Equipment here is named FI4-B-CAM-VIS-001,
    # so searching "camera" finds nothing by name — and an assistant asked
    # about cameras concludes there are none. So does a type above it: "vacuum pumps" are the ion,
    # turbo and primary pumps.
    single = _singular(needle)
    # A query of several words: each must match, by name, key or type ("accumulator dipole"), or the whole of it.
    words = [(w, _singular(w), _with_subtypes(catalogue, _named(catalogue, w))) for w in _search_words(needle)]

    def is_of_kind(a: Asset, word_single: str, named: set) -> bool:
        return word_single in (a.type or "").lower() or a.type in named

    def matches(a: Asset, word: str, word_single: str, named: set) -> bool:
        return word in (a.name or "").lower() or word in (a.key or "").lower() or is_of_kind(a, word_single, named)

    rows = [
        a for a in db.scalars(stmt)
        if not needle
        or matches(a, needle, single, by_word)
        or (words and all(matches(a, *w) for w in words))
    ]
    # This workspace's own first: the shared catalogue's records are there to be referenced, not to bury
    # the answer about this beamline. Then by key, so that pages of the same query never overlap or skip.
    rows.sort(key=lambda a: (a.workspace_id != workspace_id, a.key or "", a.uid))
    start = max(int(offset or 0), 0)
    page = rows[start: start + min(limit or DEFAULT_LIMIT, MAX_LIMIT)]
    out = {
        "total": len(rows),
        "by_type": dict(Counter(a.type for a in rows).most_common(40)),
        "objects": [{**_asset_summary(a), "attributes": redacted_attributes(db, a)} if with_attributes
                    else _asset_summary(a) for a in page],
    }
    if unknown:
        out["unknown_types"] = unknown
    by_type = sum(1 for a in rows if is_of_kind(a, single, by_word)
                  or any(is_of_kind(a, w[1], w[2]) for w in words))
    if needle and not by_type and wanted is None:
        # No object matched by its type, so what matched (if anything) matched by name only: the kind may
        # still be here under the names the catalogue uses ('magnet' → Quadrupole, "A focusing magnet"), and
        # a network called sparc-magnets is not the magnets. Offered, not assumed.
        suggestions = [t for t in _mentioning(catalogue, needle) if t["records"]]
        if suggestions:
            out["types_whose_description_mentions_it"] = suggestions
            out["hint"] = ("No type is called that, so these results match by name only. Check which of the "
                           "types listed are what was meant, then search again with types=[...].")
    return out


def list_types(db: Session, workspace_id: str, query: Optional[str] = None) -> dict:
    """The object types here, as a tree: what each is, in one line, and how many records it and the types
    below it hold. A kind of equipment is often several types: this is how to find which."""
    catalogue = _types(db, workspace_id)
    if query and query.strip():
        named = _named(catalogue, query)
        mentioned = {t["name"] for t in _mentioning(catalogue, query)}
        keep = _with_subtypes(catalogue, named | mentioned)
    else:
        keep = {t["name"] for t in catalogue if t["records_with_subtypes"]}
    rows = [t for t in catalogue if t["name"] in keep]
    return {
        "total": len(rows),
        "types": [{"name": t["name"], "path": " > ".join(t["path"]),
                   "description": _first_sentence(t["description"]), "abstract": t["abstract"],
                   "records": t["records_with_subtypes"]} for t in rows[:150]],
    }


def _by_former_key(db: Session, key: str) -> Optional[Asset]:
    """A record found by a key it had before (a beam element's btf:accumulator_pa/DHSA11)."""
    from app.models.asset_subresources import AssetLabel
    uid = db.scalar(select(AssetLabel.asset_uid).where(AssetLabel.type == "former_key", AssetLabel.value == key)
                    .limit(1))
    return db.get(Asset, uid) if uid else None


def get_object(db: Session, workspace_id: str, uid_or_key: str) -> dict:
    """One object: its attributes, and what it is physically connected to."""
    asset = db.scalar(select(Asset).where(Asset.uid == uid_or_key)) or db.scalar(
        select(Asset).where(Asset.key == uid_or_key)
    ) or _by_former_key(db, uid_or_key)
    if asset is None or not _asset_visible(db, asset, workspace_id):
        return {"found": False, "looked_for": uid_or_key}

    relations = []
    for relation in db.scalars(
        select(Relation).where(
            (Relation.from_asset_uid == asset.uid) | (Relation.to_asset_uid == asset.uid)
        )
    ):
        outgoing = relation.from_asset_uid == asset.uid
        other_uid = relation.to_asset_uid if outgoing else relation.from_asset_uid
        other = db.get(Asset, other_uid)
        relations.append({
            "relation": relation.relation_type,
            "direction": "to" if outgoing else "from",
            "object": (_asset_summary(other) if can_see(other) else {"restricted": True}) if other
            else {"uid": other_uid},
        })

    # Its history and its paperwork. "What has gone wrong with this before" and "which procedure covers it"
    # are the next questions about any object, and the answer is linked to it, not findable by its words.
    tickets = db.scalars(
        select(Issue).where(Issue.workspace_id == workspace_id, Issue.asset_uid == asset.uid,
                            visible_issues_clause(), Issue.deleted_at.is_(None))
        .order_by(Issue.created_at.desc()).limit(15)
    ).all()
    documents = []
    stmt = (select(Document, DocumentRelation.relation_type)
            .join(DocumentRelation, DocumentRelation.from_document_uid == Document.uid)
            .where(DocumentRelation.to_type == "asset", DocumentRelation.to_uid == asset.uid,
                   _document_visible(workspace_id)))
    if not _confidential_allowed(db, workspace_id):
        stmt = stmt.where(Document.confidentiality != "riservato")
    for document, relation_type in db.execute(stmt.limit(15)):
        documents.append({**_document_summary(document, None), "relation": relation_type})

    return {
        "found": True,
        **_asset_summary(asset),
        "attributes": redacted_attributes(db, asset),
        "relations": relations,
        "tickets": [_issue_summary(i) for i in tickets],
        "documents": documents,
    }


def _text_score(needle: str, *texts: str) -> int:
    """How well a free-text query matches some text: the whole query found scores highest, otherwise
    the number of its words found. A person reporting a fault writes "no Wi-Fi in the reading room
    east"; the ticket says "Reading hall east: no Wi-Fi". Matching the whole sentence finds nothing,
    and an assistant told nothing concludes there is no history."""
    haystack = " ".join(t for t in texts if t).lower()
    if not needle:
        return 1
    if needle in haystack:
        return 1000
    words = _search_words(needle)
    found = sum(1 for w in words if w in haystack or _singular(w) in haystack)
    # One word in five is chance; two of a short query, or a third of a long one, is a match.
    return found if words and found >= max(1, min(2, len(words)), -(-len(words) // 3)) else 0


# What a person or an assistant means by a state, against the states a ticket has.
_STATE_GROUPS = {
    "open": ("new", "in_progress", "pending"),
    "active": ("new", "in_progress", "pending"),
    "unresolved": ("new", "in_progress", "pending"),
    "done": ("resolved", "closed"),
    "finished": ("resolved", "closed"),
    "past": ("resolved", "closed"),
}


def _find_asset(db: Session, workspace_id: str, uid_or_key: str) -> Optional[Asset]:
    asset = db.scalar(select(Asset).where(Asset.uid == uid_or_key)) or db.scalar(
        select(Asset).where(Asset.key == uid_or_key)) or _by_former_key(db, uid_or_key)
    return asset if asset is not None and _asset_visible(db, asset, workspace_id) else None


def where_is(db: Session, workspace_id: str, uid_or_key: str, relative_to: Optional[str] = None) -> dict:
    """Where a record physically is: the places it is in, nearest first (its rack, the room, the floor, the
    building), and the floor plan it can be shown on — its own point, or the point of the nearest place in the
    chain that has one. With `relative_to` (other records), where each of them is too, and — on the same plan
    placed on the map — how far from the first and which way."""
    from app.services import indoor
    asset = _find_asset(db, workspace_id, uid_or_key)
    if asset is None:
        return {"found": False, "looked_for": uid_or_key}
    may = lambda a: _asset_visible(db, a, workspace_id)  # noqa: E731

    def chain_of(a: Asset) -> list:
        chain, seen, node = [], {a.uid}, a
        for _ in range(8):
            nxt = indoor._container_of(db, node)
            rec = db.get(Asset, nxt) if nxt and nxt not in seen else None
            if rec is None or rec.deleted_at is not None or not may(rec):
                break
            chain.append(_asset_summary(rec))
            seen.add(rec.uid)
            node = rec
        return chain

    def on_plan(s: Optional[dict]) -> Optional[dict]:
        if not s:
            return None
        return {"plan": s["plan"]["name"], "floor": s["level"]["name"] if s["level"] else None,
                "shown_at": (f"the point of {s['via']['key'] or s['via']['name']} (it has no point of its own)"
                             if s["via"] else "its own point")}

    first = indoor.spot(db, asset.uid, may)
    out = {"found": True, **_asset_summary(asset), "in": chain_of(asset), "floor_plan": on_plan(first)}
    shown = [asset.uid] if first else []
    others = []
    for ref in [r.strip() for r in (relative_to or "").split(",") if r.strip()][:10]:
        other = _find_asset(db, workspace_id, ref)
        if other is None:
            others.append({"found": False, "looked_for": ref})
            continue
        s = indoor.spot(db, other.uid, may)
        row = {**_asset_summary(other), "in": chain_of(other), "floor_plan": on_plan(s)}
        if first and s:
            rel = indoor.between(db, first, s)
            this, that = other.key or other.name, asset.key or asset.name
            row["from_it"] = (f"{this} is {rel['metres']} m {rel['direction']} of {that}" if rel and rel["direction"]
                              else f"{this} is {rel['metres']} m from {that}" if rel
                              else "on another floor plan" if s["plan"]["uid"] != first["plan"]["uid"]
                              else "same plan, not placed on the map: no distance")
            shown.append(other.uid)
        elif s:
            shown.append(other.uid)
        others.append(row)
    if others:
        out["relative_to"] = others
    if shown:
        out["show_on_plan"] = "/floor-plan?show=" + ",".join(shown)
    return out


def search_tickets(db: Session, workspace_id: str, query: str = "",
                   state: Optional[str] = None, limit: int = DEFAULT_LIMIT) -> dict:
    """Work: faults, maintenance, requests. A query of several words matches tickets with most of them,
    best first; `state` is a ticket state, or "open" (not yet resolved) or "done" (resolved or closed)."""
    needle = (query or "").strip().lower()
    stmt = select(Issue).where(Issue.workspace_id == workspace_id, visible_issues_clause(),
                               Issue.deleted_at.is_(None))
    if state:
        wanted = _STATE_GROUPS.get(state.strip().lower(), (state.strip().lower(),))
        stmt = stmt.where(Issue.state.in_(wanted))
    issues = list(db.scalars(stmt))
    on = {a.uid: a for a in db.scalars(select(Asset).where(
        Asset.uid.in_({i.asset_uid for i in issues if i.asset_uid})))} if needle else {}
    scored = []
    for i in issues:
        asset = on.get(i.asset_uid)
        score = _text_score(needle, i.title, i.description, i.key,
                            asset.key if asset else "", asset.name if asset else "")
        if score:
            scored.append((score, i))
    scored.sort(key=lambda s: (-s[0], -(s[1].created_at.timestamp() if s[1].created_at else 0)))
    rows = [i for _, i in scored]
    return {
        "total": len(rows),
        "tickets": [_issue_summary(i, on.get(i.asset_uid)) for i in rows[: min(limit, MAX_LIMIT)]],
    }


def get_ticket(db: Session, workspace_id: str, uid: str) -> dict:
    """One ticket, including the ARGUS fields: cause, cure, downtime."""
    issue = db.scalar(
        select(Issue).where(Issue.workspace_id == workspace_id, (Issue.uid == uid) | (Issue.key == uid),
                            visible_issues_clause())
    )
    if issue is None:
        return {"found": False, "looked_for": uid}
    attributes = issue.attributes or {}
    return {
        "found": True,
        **_issue_summary(issue),
        "description": issue.description,
        "labels": issue.labels or [],
        "root_cause": attributes.get("argus_root_cause"),
        "corrective_action": attributes.get("argus_corrective_action"),
        "system": attributes.get("argus_system"),
        "subsystem": attributes.get("argus_subsystem"),
        "downtime_minutes": attributes.get("argus_downtime_minutes"),
        # What was found while working on it: "LIB-03's LEDs are off", "it shows the factory address".
        # The description is the report; the comments are the diagnosis.
        "comments": [
            {"author": c.author, "at": c.created_at.isoformat(timespec="minutes") if c.created_at else None,
             "body": (c.body or "")[:1500]}
            for c in db.scalars(select(IssueComment).where(IssueComment.issue_uid == issue.uid)
                                .order_by(IssueComment.created_at).limit(20))
        ],
    }


def search_documents(db: Session, workspace_id: str, query: str = "",
                     type: Optional[str] = None, limit: int = DEFAULT_LIMIT) -> dict:
    """Documentation by title, code or type."""
    needle = (query or "").strip().lower()
    names = {s.uid: s.name for s in db.scalars(
        select(Schema).where(Schema.workspace_id == workspace_id)
    )}
    stmt = select(Document).where(_document_visible(workspace_id))
    if not _confidential_allowed(db, workspace_id):
        stmt = stmt.where(Document.confidentiality != "riservato")

    scored = []
    for document in db.scalars(stmt):
        type_name = names.get(document.document_type_uid or "")
        if type and (type_name or "").lower() != type.lower():
            continue
        if not needle:
            scored.append((0, 0, _document_summary(document, type_name)))
            continue
        title_score = _text_score(needle, document.title, document.code)
        # The body too. A documentation search that only reads titles
        # answers "nothing about vacuum" for a library full of it.
        revision = (
            db.get(DocumentRevision, document.current_revision_uid)
            if document.current_revision_uid else None
        )
        text = (revision.body_markdown or "") if revision else ""
        body_score = _text_score(needle, document.title, document.code, text)
        if not (title_score or body_score):
            continue
        row = {**_document_summary(document, type_name), "matched": "title" if title_score else "text"}
        if not title_score:
            lower = text.lower()
            at = [lower.find(w) for w in ([needle] + _search_words(needle)) if w in lower]
            where = at[0] if at else 0
            row["excerpt"] = " ".join(text[max(0, where - 80): where + 160].split())
        scored.append((title_score, body_score, row))
    # Title matches first: they are what somebody meant. Then the text that matches most of the query.
    scored.sort(key=lambda s: (-s[0], -s[1]))
    rows = [r for _, _, r in scored]
    return {"total": len(rows), "documents": rows[: min(limit, MAX_LIMIT)]}


def get_document(db: Session, workspace_id: str, uid_or_code: str) -> dict:
    """A document's current text, as Markdown."""
    document = db.scalar(
        select(Document).where(_document_visible(workspace_id), Document.uid == uid_or_code)
    ) or db.scalar(
        select(Document).where(_document_visible(workspace_id), Document.code == uid_or_code)
    )
    if document is None:
        return {"found": False, "looked_for": uid_or_code}
    if document.confidentiality == "riservato" and not _confidential_allowed(db, workspace_id):
        return {
            "found": False,
            "reason": "This document is confidential and this workspace does not allow "
                      "confidential text to be sent to an assistant.",
        }

    revision = (
        db.get(DocumentRevision, document.current_revision_uid)
        if document.current_revision_uid else None
    )
    body = (revision.body_markdown or "") if revision else ""
    names = {s.uid: s.name for s in db.scalars(
        select(Schema).where(Schema.workspace_id == workspace_id)
    )}
    return {
        "found": True,
        **_document_summary(document, names.get(document.document_type_uid or "")),
        "state": revision.state if revision else None,
        "body_markdown": body[:DOCUMENT_CHARS],
        "truncated": len(body) > DOCUMENT_CHARS,
    }


def graph_neighbours(db: Session, workspace_id: str, kind: str, uid: str,
                     depth: int = 1, kinds: Optional[str] = None,
                     max_nodes: int = 60) -> dict:
    """Everything within a few hops: the question RAG cannot answer."""
    # An assistant names a record by the key it read (NF-AP-LIB-01, IT-TCK-0022, NF-RB-005), not by the
    # internal uid: an empty graph for a record that exists reads as "connected to nothing".
    if kind == "asset" and db.get(Asset, uid) is None:
        found = db.scalar(select(Asset.uid).where(Asset.key == uid)) or getattr(_by_former_key(db, uid), "uid", None)
        uid = found or uid
    elif kind == "ticket" and db.get(Issue, uid) is None:
        uid = db.scalar(select(Issue.uid).where(Issue.workspace_id == workspace_id, Issue.key == uid)) or uid
    elif kind == "document" and db.get(Document, uid) is None:
        uid = db.scalar(select(Document.uid).where(_document_visible(workspace_id), Document.code == uid)) or uid
    graph = traverse(
        db, workspace_id, kind, uid, depth=max(1, min(depth, 4)),
        kinds=[k.strip() for k in kinds.split(",")] if kinds else None,
        max_nodes=max(1, min(max_nodes, 200)),
    )
    return {
        "nodes": [
            {"kind": n.kind, "uid": n.uid, "label": n.label, "sublabel": n.sublabel,
             "type": n.type_name, "state": n.state, "depth": n.depth}
            for n in graph.nodes
        ],
        "edges": [
            {"from": f"{e.from_kind}:{e.from_uid}", "to": f"{e.to_kind}:{e.to_uid}",
             "relation": e.relation, "via": e.via}
            for e in graph.edges
        ],
        "truncated": graph.truncated,
    }


def _line(path: list) -> str:
    """A path as one line an assistant can quote: `A --powers--> B --realized by--> C`."""
    if not path:
        return ""
    return path[0]["provider"] + "".join(f" --{h['relation']}--> {h['dependent']}" for h in path)


def _layer_list(layers: Optional[str]) -> Optional[list]:
    return [x.strip() for x in layers.split(",") if x.strip()] if layers else None


def impact_analysis(db: Session, workspace_id: str, uid_or_key: str, layers: Optional[str] = None,
                    max_depth: int = 6, limit: int = 40) -> dict:
    """This stopped: what does it take with it?"""
    result = _impact_of(db, workspace_id, uid_or_key, layers=_layer_list(layers),
                        max_depth=max(1, min(max_depth, 8)))
    if result is None:
        return {"found": False}
    limit = max(1, min(limit, MAX_LIMIT))
    return {
        "found": True, "origin": result["origin"]["key"], "count": result["count"],
        "by_type": result["by_type"], "by_loss": result["by_loss"],
        "affected": [
            {"key": a["key"], "type": a["type"], "loses": list(a["losses"]), "depth": a["depth"],
             "path": _line(a["path"]), "inferred": a["via_inference"]}
            for a in result["affected"][:limit]
        ],
        "shown": min(limit, result["count"]), "truncated": result["truncated"],
        "unclassified_relations": result["unclassified_relations"],
    }


def root_cause_analysis(db: Session, workspace_id: str, symptoms: str, healthy: Optional[str] = None,
                        layers: Optional[str] = None, control_symptoms: Optional[str] = None,
                        max_depth: int = 6, top: int = 5) -> dict:
    """These are misbehaving: what would explain them?"""
    listed = lambda text: [x.strip() for x in (text or "").split(",") if x.strip()]
    kinds = {s: causal_model.CONTROL for s in listed(control_symptoms)}
    result = _root_causes(
        db, workspace_id, listed(symptoms), healthy=listed(healthy), layers=_layer_list(layers),
        max_depth=max(1, min(max_depth, 8)), top=max(1, min(top, 15)), symptom_kind=kinds)
    return {
        "not_found": result["not_found"],
        "candidates": [
            {"key": c["key"], "type": c["type"], "fit": c["fit"], "parsimony": c["parsimony"],
             "explains": [{"symptom": e["key"], "loses": e["loss"], "path": _line(e["path"]),
                           "inferred": e["via_inference"]} for e in c["explains"]],
             "would_also_affect": c["would_also_affect"], "contradicted_by": c["contradicted_by"],
             "earlier_tickets": c["history"]}
            for c in result["candidates"]
        ],
        "fewest_causes": [
            {"causes": [{"key": x["key"], "explains": x["explains"]} for x in h["causes"]],
             "unexplained": h["unexplained"]}
            for h in result["hypotheses"]
        ],
    }


def root_cause_from_alarms(db: Session, workspace_id: str, alarms: list, layers: Optional[str] = None,
                           max_depth: int = 6, top: int = 5) -> dict:
    """A raw alarm feed in, a root-cause answer out. See `root_cause_analysis` for the fields on
    each candidate; this additionally reports which alarms could not be placed on an object."""
    result = _root_cause_from_alarms(db, workspace_id, alarms, layers=_layer_list(layers),
                                     max_depth=max(1, min(max_depth, 8)), top=max(1, min(top, 15)))
    if not result["candidates"]:
        return {"placed": result["placed"], "unresolved": result["unresolved"], "candidates": [],
                "fewest_causes": []}
    return {
        "placed": result["placed"], "unresolved": result["unresolved"],
        "candidates": [
            {"key": c["key"], "type": c["type"], "fit": c["fit"], "parsimony": c["parsimony"],
             "explains": [{"symptom": e["key"], "loses": e["loss"], "path": _line(e["path"]),
                           "inferred": e["via_inference"]} for e in c["explains"]],
             "would_also_affect": c["would_also_affect"], "contradicted_by": c["contradicted_by"],
             "earlier_tickets": c["history"]}
            for c in result["candidates"]
        ],
        "fewest_causes": [
            {"causes": [{"key": x["key"], "explains": x["explains"]} for x in h["causes"]],
             "unexplained": h["unexplained"]}
            for h in result["hypotheses"]
        ],
    }


def single_points_of_failure(db: Session, workspace_id: str, layers: Optional[str] = None,
                             top: int = 15) -> dict:
    """What would take the most with it."""
    result = _blast_radius(db, workspace_id, layers=_layer_list(layers), top=max(1, min(top, 50)))
    return {"assets": [
        {"key": a["key"], "type": a["type"], "loses_function": a["function"],
         "loses_readout": a["control"], "degrades": a["degradation"]}
        for a in result["assets"]
    ], "considered": result["considered"]}


def search_knowledge(db: Session, workspace_id: str, query: str, kinds: Optional[list] = None,
                     limit: int = 8) -> dict:
    """Passages of procedures, tickets and their comments, comments on equipment and attached files
    (datasheets, manuals), found by meaning as well as by words."""
    from app.services import knowledge_index
    from app.services.ai_config import resolve
    config, _from = resolve(db, workspace_id)
    if config is None or not config.embedding_model:
        return {"available": False, "reason": "No embedding model is configured for this workspace's AI endpoint."}
    from app.routers.ai import endpoint_for
    return knowledge_index.search(db, workspace_id, endpoint_for(config), query, kinds=kinds, limit=limit,
                                  confidential_ok=_confidential_allowed(db, workspace_id))


def knowledge_summary(db: Session, workspace_id: str) -> dict:
    """How much of a graph this workspace actually has."""
    return graph_summary(db, workspace_id)


# --- the catalogue ------------------------------------------------------

def search_help(db: Session, workspace_id: str, query: str, limit: int = 6) -> dict:
    """The user guide's sections that match a question (app/help): how to do things in ARGUS."""
    from app import help as guide
    hits = guide.search(query, max(1, min(int(limit or 6), 12)))
    return {"total": len(hits), "results": hits,
            "topics": [{"slug": t["slug"], "title": t["title"]} for t in guide.index()] if not hits else []}


def read_help(db: Session, workspace_id: str, topic: str) -> dict:
    """One topic of the user guide, whole."""
    from app import help as guide
    t = guide.topic(str(topic or "").strip())
    if t is None:
        return {"found": False, "topics": [{"slug": x["slug"], "title": x["title"]} for x in guide.index()]}
    return {"found": True, "slug": t.slug, "title": t.title, "body": t.body}


def workspace_access(db: Session, workspace_id: str, person: str = "") -> dict:
    """Who can get into this workspace and how. The whole list only to whoever manages access here; to anyone
    else, their own access and nothing about other people."""
    from app.services import who_has_access as wha
    viewer = wha.current_viewer()
    wanted = str(person or "").strip().lower()
    if viewer is not None and viewer.may_manage:
        out = wha.who_has_access(db, workspace_id)
        if wanted:
            out["people"] = [p for p in out["people"] if wanted in (p["email"] or "").lower()
                             or wanted in (p["name"] or "").lower()]
            out["filtered_by"] = person
        else:
            # The installation's administrators reach every workspace: named, not detailed, so the list stays
            # about this workspace.
            admins = [p for p in out["people"] if p["installation_administrator"] and len(p["routes"]) == 1]
            out["people"] = [p for p in out["people"] if p not in admins]
            out["installation_administrators_only"] = [p["email"] for p in admins]
        return out
    user = db.get(User, viewer.user_id) if viewer is not None and viewer.user_id else None
    if user is None:
        return {"allowed": False, "reason": "Only a signed-in person can ask about access, and only someone who "
                                            "manages access to this workspace can ask about other people."}
    own = wha.person_access(db, user, workspace_id)
    out = {"scope": "only your own access: who else has access is shown only to those who manage access here",
           "you": own or {"email": user.email, "rights": {}, "routes": []},
           "anyone_signed_in": wha.defaults(db.get(Workspace, workspace_id))}
    if wanted and wanted not in (user.email or "").lower() and wanted not in (user.name or "").lower():
        out["not_shown"] = f"Access of {person!r} is shown only to those who manage access to this workspace."
    return out


TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_objects",
        "description": "Search equipment (objects) by name, key or type. A type includes the types "
                       "below it. Returns the total, the count per type (by_type) and the first "
                       "objects (uid, key, name, type; a beam element also its model). Names are codes, so "
                       "'dipole' is usually a type: for what there is or how many, search by type and answer "
                       "from total and by_type, counting the records of that type and not the channel or "
                       "the supply that drives them.",
        "handler": search_objects,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to look for in the name, key or type. With "
                                                           "several words each must match: 'accumulator dipole'"},
                "type": {"type": "string", "description": "Restrict to one object type (and its subtypes)"},
                "types": {"type": "array", "items": {"type": "string"},
                          "description": "Restrict to several object types (and their subtypes)"},
                "limit": {"type": "integer", "description": f"Objects to return; default {DEFAULT_LIMIT}, "
                                                            f"at most {MAX_LIMIT}"},
                "offset": {"type": "integer", "description": "Objects to skip, to page through more than "
                                                             "one limit's worth; default 0"},
                "with_attributes": {"type": "boolean",
                                    "description": "Return each object's attributes too, as get_object "
                                                   "would; default false"},
                "include_retired": {"type": "boolean",
                                    "description": "Also return retired and merged records, each with its "
                                                   "status. Only for a question about what was removed or "
                                                   "what used to exist; default false"},
            },
        },
    },
    {
        "name": "list_types",
        "description": "The object types in this workspace as a tree, each with a one-line description "
                       "and how many records it holds. Use it to find which types a kind of equipment "
                       "is: 'magnets' are several types (Dipole, Quadrupole, Corrector…), none of them "
                       "called Magnet.",
        "handler": list_types,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "A word to look for in type names, aliases and descriptions; "
                                         "omit to list every type that has records"},
            },
        },
    },
    {
        "name": "get_object",
        "description": "One object by uid or key, with its attributes, the objects it "
                       "is physically connected to, the tickets about it (its fault history) and the "
                       "documents that describe it (runbooks, procedures).",
        "handler": get_object,
        "inputSchema": {
            "type": "object",
            "properties": {"uid_or_key": {"type": "string"}},
            "required": ["uid_or_key"],
        },
    },
    {
        "name": "where_is",
        "description": "Where an object physically is: the places it is in, nearest first (rack, room, floor, "
                       "building), and whether it can be shown on a floor plan — its own point or its rack's. "
                       "With relative_to (other objects, comma-separated keys), where they are too and how far "
                       "from the first and which way, said as '<other> is N m <direction> of <first>' — keep "
                       "that direction as it is, never turn it round. The page offers a 'Show on the floor plan' button for "
                       "them, so say it is there; say when a point is the rack's rather than the object's own.",
        "handler": where_is,
        "inputSchema": {
            "type": "object",
            "properties": {"uid_or_key": {"type": "string"},
                           "relative_to": {"type": "string",
                                           "description": "Other objects to place with respect to it, comma-separated"}},
            "required": ["uid_or_key"],
        },
    },
    {
        "name": "search_tickets",
        "description": "Search tickets — faults, maintenance, requests, changes — by text, best match "
                       "first, optionally filtered by state. Leave state out to include past, closed tickets: "
                       "they hold how the same fault was fixed before.",
        "handler": search_tickets,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "state": {"type": "string", "description": "new | in_progress | pending | resolved | closed, "
                          "or open (not yet resolved) or done (resolved or closed)"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "get_ticket",
        "description": "One ticket by uid or key (BTF-TCK-0042), including root cause, corrective action, "
                       "affected system and downtime where they are recorded, and its comments: what was "
                       "found while working on it.",
        "handler": get_ticket,
        "inputSchema": {
            "type": "object",
            "properties": {"uid": {"type": "string", "description": "The ticket's uid or its key"}},
            "required": ["uid"],
        },
    },
    {
        "name": "search_documents",
        "description": "Search documentation by title, code, document type "
                       "(Procedure, Runbook, Specification, Logbook Entry, …) or the "
                       "text of the document itself. Text matches come back with the "
                       "surrounding sentence.",
        "handler": search_documents,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "type": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "get_document",
        "description": "A document's current text as Markdown, by uid or code.",
        "handler": get_document,
        "inputSchema": {
            "type": "object",
            "properties": {"uid_or_code": {"type": "string"}},
            "required": ["uid_or_code"],
        },
    },
    {
        "name": "graph_neighbours",
        "description": "Everything connected to one record within a few hops, across "
                       "objects, tickets, documents and people. Use this for questions "
                       "like 'what broke this magnet before' or 'which procedure covers "
                       "this camera' — the answer spans records and is in no single "
                       "document. kind is one of asset, ticket, document, group, person.",
        "handler": graph_neighbours,
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "description": "asset | ticket | document | group | person"},
                "uid": {"type": "string", "description": "The record's uid or key"},
                "depth": {"type": "integer", "description": "1 to 4, default 1"},
                "kinds": {"type": "string", "description": "Comma-separated kinds to keep"},
                "max_nodes": {"type": "integer"},
            },
            "required": ["kind", "uid"],
        },
    },
    {
        "name": "impact_analysis",
        "description": "This object stopped: what does it take with it? Follows what depends on what "
                       "(power, cooling, control, timing, interlocks, composition) and says for each "
                       "affected object what it loses — its readout ('control') or its function — and "
                       "by which path. A lost IOC costs the readout of the pump behind it, not the "
                       "pump. Objects are given by key or uid. layers narrows the walk, e.g. "
                       "'power,cooling'.",
        "handler": impact_analysis,
        "inputSchema": {
            "type": "object",
            "properties": {
                "uid_or_key": {"type": "string"},
                "layers": {"type": "string", "description": "Comma-separated: control, power, cooling, "
                           "vacuum, timing, interlock, function, composition, membership, beam, environment"},
                "max_depth": {"type": "integer", "description": "1 to 8, default 6"},
                "limit": {"type": "integer"},
            },
            "required": ["uid_or_key"],
        },
    },
    {
        "name": "root_cause_analysis",
        "description": "These objects misbehave: what would explain them? Give the symptoms by key "
                       "(comma-separated), and if known which objects still work (healthy) and which "
                       "symptoms are only a lost readout (control_symptoms, e.g. a PV that "
                       "disconnected). Returns candidates ranked by how well they fit, each with the "
                       "path to every symptom, what it would also have broken, and earlier tickets "
                       "that named it, plus the fewest causes that explain everything. Paths through "
                       "inferred objects are marked. Rank is evidence to argue with, not a probability.",
        "handler": root_cause_analysis,
        "inputSchema": {
            "type": "object",
            "properties": {
                "symptoms": {"type": "string", "description": "Comma-separated object keys or uids"},
                "healthy": {"type": "string", "description": "Comma-separated objects known to work"},
                "control_symptoms": {"type": "string", "description": "Which symptoms are only a lost readout"},
                "layers": {"type": "string"},
                "max_depth": {"type": "integer"},
                "top": {"type": "integer"},
            },
            "required": ["symptoms"],
        },
    },
    {
        "name": "root_cause_from_alarms",
        "description": "The alarm-feed version of root_cause_analysis: give the PVs currently in "
                       "alarm (and, if known, the ones reporting OK) and this resolves each to an "
                       "object, reads whether it lost its readout or its function from the EPICS "
                       "severity (INVALID -> readout, MINOR/MAJOR -> function; OK is evidence the "
                       "object works), and ranks candidates the same way root_cause_analysis does. "
                       "A lost permit is never guessed from a severity — pass kind: 'permit' on "
                       "that alarm when you know one. Alarms are objects with pv (required), "
                       "severity, status and an optional kind override; what cannot be placed on "
                       "an object is reported under 'unresolved'.",
        "handler": root_cause_from_alarms,
        "inputSchema": {
            "type": "object",
            "properties": {
                "alarms": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "pv": {"type": "string"},
                            "severity": {"type": "string", "description": "OK, MINOR, MAJOR or INVALID"},
                            "status": {"type": "string"},
                            "kind": {"type": "string", "description": "control | function | permit"},
                        },
                        "required": ["pv"],
                    },
                },
                "layers": {"type": "string"},
                "max_depth": {"type": "integer"},
                "top": {"type": "integer"},
            },
            "required": ["alarms"],
        },
    },
    {
        "name": "single_points_of_failure",
        "description": "The objects whose failure would take the most with it: how many others lose "
                       "their function, their readout, or are degraded.",
        "handler": single_points_of_failure,
        "inputSchema": {
            "type": "object",
            "properties": {"layers": {"type": "string"}, "top": {"type": "integer"}},
        },
    },
    {
        "name": "search_knowledge",
        "description": "Search what is written: procedures and documents, tickets and their comments (what "
                       "went wrong and how it was fixed), comments on equipment, and the text of attached "
                       "files such as datasheets and manuals (with the page). Finds passages by meaning, "
                       "in any language, as well as by exact words. Use it for how-to, history and "
                       "'what does the manual say' questions; use search_objects for what equipment exists.",
        "handler": search_knowledge,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The question, or what the passage should say"},
                "kinds": {"type": "array", "items": {"type": "string",
                                                     "enum": ["document", "ticket", "ticket_comment",
                                                              "attachment", "asset_comment"]},
                          "description": "Restrict to these kinds of source"},
                "limit": {"type": "integer", "description": "Passages to return; default 8, at most 20"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "workspace_access",
        "description": "Who can get into this workspace and how: each person, what they may do (objects, tickets, "
                       "documents, managing access) and every route that gives it — administrator of the "
                       "installation, a role of their own, a group's role here, a group's role site-wide at the "
                       "site, area permissions, administering the site — plus what anyone signed in gets. Use it "
                       "for 'who can access/edit/approve here', 'why can X …', 'who manages access'. Someone who "
                       "does not manage access gets only their own access back: say so, do not guess the rest.",
        "handler": workspace_access,
        "inputSchema": {
            "type": "object",
            "properties": {"person": {"type": "string",
                                      "description": "Part of a name or e-mail, to ask about one person"}},
        },
    },
    {
        "name": "search_help",
        "description": "Search the ARGUS user guide: how to do things in ARGUS itself, step by step (sign in, "
                       "create a workspace, give roles, register equipment, import EPIK8s or Jira, review "
                       "proposals, write documents, configure AI, export and import between installations "
                       "with GitHub/GitLab, …). Use it for 'how do I…', 'where is…', 'what does … mean' "
                       "questions about the application, not about the machine's records.",
        "handler": search_help,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The question, in words"},
                "limit": {"type": "integer", "description": "Sections to return; default 6"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_help",
        "description": "Read one topic of the ARGUS user guide whole, by its slug (from search_help), to walk "
                       "the person through a procedure step by step.",
        "handler": read_help,
        "inputSchema": {
            "type": "object",
            "properties": {"topic": {"type": "string", "description": "The topic's slug, e.g. export-import"}},
            "required": ["topic"],
        },
    },
    {
        "name": "knowledge_summary",
        "description": "How many objects, tickets and documents this workspace holds, and "
                       "how many connections of each kind exist between them.",
        "handler": knowledge_summary,
        "inputSchema": {"type": "object", "properties": {}},
    },
]

# The IOC engineer (app/ioc_engineer): building containerised EPICS IOCs with ibek, from the catalogue of
# infn-epics-ioc's support modules and templates. Answers the same in every workspace: it is about the image.
from app.ioc_engineer import tools as ioc  # noqa: E402
from app.ioc_engineer.ibekize import ioc_ibekize_repo as ibekize_tool  # noqa: E402
from app.ioc_engineer.scaffold import ioc_scaffold_module as scaffold_module_tool  # noqa: E402

TOOLS += [
    {
        "name": "ioc_search",
        "description": "Search the EPICS IOC catalogue (infn-epics-ioc: ibek-support-infn drivers, upstream "
                       "ibek-support, ibek-templates and their example entries) by vendor, device, driver, "
                       "devtype or entity type. Start here for any question about building, configuring or "
                       "deploying a containerised IOC with ibek.",
        "handler": ioc.ioc_search,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "e.g. 'pfeiffer gauge', 'ocem', 'modbus', 'technosoft'"},
                "kind": {"type": "string", "enum": ["module", "entity_model", "template", "example"]},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "ioc_get_module",
        "description": "One support module: its driver's git repository and version (from install.yml), libs "
                       "and dbds, whether the infn-epics-ioc image compiles it (and in which Dockerfile), its "
                       "entity models with their required parameters, the templates that use it, and — when "
                       "indexed — the driver source's db templates with their macros and protocol files.",
        "handler": ioc.ioc_get_module,
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string",
                                    "description": "Folder (ocemPS), repository (OCEMPowerSupply) or ibek module (ocem)"}},
            "required": ["name"],
        },
    },
    {
        "name": "ioc_get_entity_model",
        "description": "One ibek entity model whole, by type (ocem.modbusps, asyn.AsynIP, epics.DbAlias): "
                       "parameters with types, defaults and descriptions, the st.cmd lines it adds, the "
                       "databases it loads with their macros, and whether the image can instantiate it.",
        "handler": ioc.ioc_get_entity_model,
        "inputSchema": {"type": "object", "properties": {"type": {"type": "string"}}, "required": ["type"]},
    },
    {
        "name": "ioc_get_template",
        "description": "One ibek-template by the value of `template:` (ocem, motor, agilent-vac…): its Jinja2 "
                       "source, the devtypes it branches on, the variables it reads from the beamline entry, "
                       "the entity types it emits and whether the image has them, and its examples.",
        "handler": ioc.ioc_get_template,
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"},
                           "include_source": {"type": "boolean", "description": "Default true"}},
            "required": ["name"],
        },
    },
    {
        "name": "ioc_get_example",
        "description": "A worked beamline IOC entry, by name or by template: an ibek-templates test fixture or a "
                       "config kept in infn-epics-ioc. The quickest start for a new entry of a known type.",
        "handler": ioc.ioc_get_example,
        "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    },
    {
        "name": "ioc_render",
        "description": "Render a beamline IOC entry (YAML: template, devtype, iocprefix, devices, ps:, motor:…; "
                       "a pasted epicsConfiguration.iocs block with one IOC works too) exactly as the IOC pod "
                       "does with jnjrender, then check the resulting ibek IOC YAML as `ibek runtime generate` "
                       "would: unknown or not-compiled entity types, missing, unknown or mistyped parameters, "
                       "dangling object references. Pass template_source to try a template being written.",
        "handler": ioc.ioc_render,
        "inputSchema": {
            "type": "object",
            "properties": {
                "values": {"type": "string", "description": "The IOC entry as YAML"},
                "template": {"type": "string", "description": "Override the entry's template:"},
                "template_source": {"type": "string", "description": "A Jinja2 template to render instead"},
                "beamline": {"type": "string", "description": "Apply this beamline's iocDefaults and injected "
                                                              "values first, as epik8s-chart does"},
            },
            "required": ["values"],
        },
    },
    {
        "name": "ioc_validate",
        "description": "Check an ibek IOC instance YAML (ioc_name, entities: [...]) against the entity models "
                       "and what the image compiles, without rendering a template.",
        "handler": ioc.ioc_validate,
        "inputSchema": {"type": "object", "properties": {"ioc_yaml": {"type": "string"}}, "required": ["ioc_yaml"]},
    },
    {
        "name": "ioc_scaffold_driver",
        "description": "Draft the files a new INFN driver needs, in the house style: <folder>.install.yml and "
                       "<folder>.ibek.support.yaml for ibek-support-infn, a template and a test fixture for "
                       "ibek-templates, the Dockerfile line, checked against each other by rendering the "
                       "fixture. Returns text to review and commit; it writes nothing.",
        "handler": ioc.ioc_scaffold_driver,
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "ibek-support-infn folder and ibek module name"},
                "repository": {"type": "string", "description": "The driver's git repository name"},
                "organization": {"type": "string", "description": "Default https://github.com/infn-epics/"},
                "version": {"type": "string", "description": "Tag or branch; default main"},
                "protocol": {"type": "string", "enum": ["stream", "modbus", "asyn"]},
                "group": {"type": "string", "enum": ioc.GROUPS},
                "devtype": {"type": "string"},
                "db_template": {"type": "string", "description": "The driver's db template file"},
                "proto_file": {"type": "string", "description": "StreamDevice protocol, relative to the repo"},
                "description": {"type": "string"},
                "default_port": {"type": "integer"},
            },
            "required": ["folder", "repository"],
        },
    },
    {
        "name": "ioc_list_beamline",
        "description": "The beamlines in the IOC catalogue (their deploy repositories), or one beamline's IOCs "
                       "as deployed: template, devtype, devgroup, iocprefix, how the pod starts them (template, "
                       "remote host, git config), disabled ones, and the count per template.",
        "handler": ioc.ioc_list_beamline,
        "inputSchema": {"type": "object", "properties": {
            "beamline": {"type": "string", "description": "e.g. eli, sparc, btf; omit to list the beamlines"},
            "template": {"type": "string"},
            "query": {"type": "string", "description": "A word in the name, prefix, devtype…"}}},
    },
    {
        "name": "ioc_get_beamline_ioc",
        "description": "One IOC of a beamline: its entry in values.yaml, the iocDefaults it inherits (and any "
                       "false/0/empty value the chart's merge ignores), the values the pod actually receives "
                       "(/tmp/iocconfig.yaml), and its render and check.",
        "handler": ioc.ioc_get_beamline_ioc,
        "inputSchema": {"type": "object", "properties": {
            "beamline": {"type": "string"}, "name": {"type": "string"},
            "render": {"type": "boolean", "description": "Default true"}}, "required": ["beamline", "name"]},
    },
    {
        "name": "ioc_check_beamline",
        "description": "Render and check every enabled, templated IOC of a beamline against the catalogue's image "
                       "and templates: which would fail at their next sync, and why. Use it before bumping the "
                       "image or changing a template the beamline uses.",
        "handler": ioc.ioc_check_beamline,
        "inputSchema": {"type": "object", "properties": {
            "beamline": {"type": "string"}, "template": {"type": "string", "description": "Only this template"}},
            "required": ["beamline"]},
    },
    {
        "name": "ioc_ibekize_repo",
        "description": "Read an existing EPICS IOC repository (a makeBaseApp tree: configure/RELEASE, *App/src/"
                       "Makefile, *App/Db templates and protocols, iocBoot/*/st.cmd) and draft what makes it an "
                       "ibek support module and an ibek-template: install.yml (git source, libs, dbds, protocol "
                       "files), ibek.support.yaml (a controller entity from st.cmd's port set-up, one entity per db "
                       "template it loads, a typed parameter per macro), the template and a fixture, rendered "
                       "against each other. Reports where each value came from, which parameters have no example "
                       "and which st.cmd lines were kept verbatim. Reads only: it writes nothing. url is an https "
                       "git URL on an allowed host, or the name of a module the catalogue already knows.",
        "handler": ibekize_tool,
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "https://host/owner/repo, or a catalogue module name"},
                "ref": {"type": "string", "description": "Branch or tag; default the repository's default"},
                "folder": {"type": "string", "description": "ibek-support-infn folder and ibek module name"},
                "group": {"type": "string", "enum": ioc.GROUPS},
                "devtype": {"type": "string"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "ioc_scaffold_module",
        "description": "Write a new EPICS support module for hardware that has none, from a description of the "
                       "device, in the house style of ppt-modulator: the makeBaseApp tree (configure/, Makefiles), "
                       "an asyn port driver in C++ (driver: asyn; it polls the readbacks and sends the setpoints) "
                       "or a StreamDevice protocol (driver: stream), one SNL state program per sequence (set, wait, "
                       "retry, timeout, abort), db templates with <name>_RB and <name>_SP records, the example "
                       "st.cmd and st-sim.cmd, a Python TCP simulator answering the same commands, and the ibek "
                       "files (install.yml, ibek.support.yaml, the template and a fixture, rendered against each "
                       "other). Returns text; it writes nothing and compiles nothing. Ask for the device's commands "
                       "and replies first; a description that cannot become a module comes back with every "
                       "problem and an example.",
        "handler": scaffold_module_tool,
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "object",
                    "description": "The device. name (repository, lower case), app (the <app>App prefix), "
                                   "description, group, devtype, driver (stream|asyn), transport (ip|serial), ip, "
                                   "port, tty, baud, terminator (CRLF|LF|CR|none), poll and timeout (s), prefix "
                                   "and device (the example's P and R), organization, version; parameters: "
                                   "[{name, type (float|int|bool|enum|string), read (a query), reply (default "
                                   "%f/%d/%s), write (one conversion, e.g. 'CURR %f'), ack, unit, prec, states, "
                                   "limits [lo, hi], sim (the simulator's start value)}]; sequences: [{name, "
                                   "description, retry_delay, steps: [{set, value, wait, equals|above|below, "
                                   "timeout, delay}]}]. A value or a condition may name one of a bool's or an "
                                   "enum's states.",
                },
            },
            "required": ["spec"],
        },
    },
    {
        "name": "ioc_guide",
        "description": "How infn-epics-ioc, ibek-support-infn, ibek-templates, epik8s-chart and the beamline "
                       "repositories fit together (the architecture document, by section), the workflow for "
                       "a new IOC or driver, and which commit the catalogue was read from.",
        "handler": ioc.ioc_guide,
        "inputSchema": {"type": "object", "properties": {
            "section": {"type": "string", "description": "A section title or a word in it; omit for all"}}},
    },
]

BY_NAME: dict[str, dict] = {tool["name"]: tool for tool in TOOLS}


def catalogue() -> list[dict]:
    """The tools as MCP describes them — without the Python handlers."""
    return [
        {k: v for k, v in tool.items() if k != "handler"}
        for tool in TOOLS
    ]


# The web page of each kind of record a result can name.
_PAGES = {"asset": "assets", "ticket": "tickets", "document": "documents"}
_NOT_PAGES = {"group", "person", "type"}


def _link_text(o: dict) -> str:
    """How a record is named in a link: its code or key with its title or name, as a reader knows it."""
    ident = o.get("code") or o.get("key") or o.get("source_key") or o.get("sublabel")
    name = o.get("title") or o.get("name") or o.get("label")
    parts = [str(ident)] if ident else []
    if name and name != ident:
        parts.append(str(name))
    # Brackets would end the link text early.
    return (" — ".join(parts) or str(o.get("uid"))).replace("[", "(").replace("]", ")")


def add_links(result: Any, workspace_id: str, base: str) -> Any:
    """Give every record in a result the address of its page in the web app, so an
    assistant outside ARGUS (LibreChat, Claude) can link what it cites. The same records
    the web's Ask page links: a code is a document, a source_key a ticket, a key an asset;
    a graph node says its kind. `?ws=` opens the page in the workspace that was asked."""
    from urllib.parse import quote

    def page(o: dict) -> Optional[str]:
        kind = o.get("kind")
        if kind in _PAGES:
            return _PAGES[kind]
        if kind in _NOT_PAGES:
            return None
        if "code" in o:
            return "documents"
        if "source_key" in o:                 # a ticket has a key now too, and always a source_key
            return "tickets"
        if "key" in o:
            return "assets"
        return None

    def walk(v: Any) -> None:
        if isinstance(v, list):
            for item in v:
                walk(item)
        elif isinstance(v, dict):
            uid = v.get("uid")
            where = page(v) if isinstance(uid, str) else None
            if where and "url" not in v:
                v["url"] = f"{base}/{where}/{quote(uid, safe='')}?ws={quote(workspace_id, safe='')}"
                # Ready to paste into an answer, so a model need not compose the link itself.
                v["link"] = f"[{_link_text(v)}]({v['url']})"
            for item in list(v.values()):
                walk(item)

    if base:
        walk(result)
    return result


def call(db: Session, workspace_id: str, name: str, arguments: dict, link_base: str = "") -> str:
    """Run one tool and return its result as text, which is what MCP carries.
    With `link_base` (the web app's address), records carry the URL of their page."""
    tool = BY_NAME.get(name)
    if tool is None:
        raise KeyError(name)
    handler: Callable = tool["handler"]
    allowed = {
        key: value
        for key, value in (arguments or {}).items()
        if key in tool["inputSchema"].get("properties", {})
    }
    result = add_links(handler(db, workspace_id, **allowed), workspace_id, link_base)
    return json.dumps(result, ensure_ascii=False, default=str, indent=2)
