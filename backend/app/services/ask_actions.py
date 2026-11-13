"""Changes Ask ARGUS proposes, and their application once a person confirms them.

Ask's lookups only retrieve, and that stays so: the model cannot write. What it can do, when somebody asks it
to ("create the six screens and link their cameras"), is propose — create a record, change one, relate two
or unrelate them. A proposal is checked as it is made (the type exists, the record is there, the relation is
one the rules allow between those types), kept in the conversation, and shown under the answer. Nothing
changes until the person applies it, and then it goes through the same code as the forms: their
permissions, the same validation and key allocation, and the ledger, in their name.

A record proposed in the same conversation is referred to as `new:N` before it exists, so "a station composed
of this camera" can be proposed in one go with the station itself.
"""
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.ask_conversation import AskAction
from app.models.asset import Asset, Relation
from app.models.schema import Schema

# What each kind of change needs, as the forms would.
PERMISSION = {"create": "create", "update": "modify", "relate": "create", "unrelate": "delete", "ticket": "create",
              # Leaves ARGUS: a person who may approve in this workspace, signed in, never an API token.
              "pull_request": "approve"}
SKIPPED_ATTRIBUTES = ("argus_source", "argus_facility")

SYSTEM = (
    "\n\nYou may also propose changes, but only when the person asks for one: propose_create_record, "
    "propose_update_record, propose_relation, and propose_ticket to open a ticket. A proposal changes nothing: it is shown to the person, who "
    "applies or discards it. Never say a change was made; say it is proposed and waits for their confirmation. "
    "Look the records up first and use their keys — also as the value of an attribute that refers to a record "
    "(where a unit is: its Located in, the argus_location attribute, takes a Location's key). "
    "A record you propose to create is referred to as new:N "
    "(N is in the proposal's reply) until it exists, so you can relate it in the same answer (a relation only: an "
    "attribute takes a key once the record exists, and a text attribute takes the name). 'A composed of "
    "B' means B is a part of A; 'X part of Y' means X belongs to Y. If a proposal is refused, correct it from "
    "the reason given rather than repeating it."
)


def _relation_names() -> list[str]:
    """The relations the hub knows the meaning of (services/causal_model.py), less the deprecated ones."""
    from app.ledger import registry
    from app.services.causal_model import SEMANTICS
    return sorted((set(SEMANTICS) | set(registry.ENDPOINTS)) - registry.DEPRECATED)


def _relation_guide() -> str:
    from app.services.causal_model import SEMANTICS
    return "; ".join(f"{n}: {SEMANTICS[n].note}" for n in _relation_names() if n in SEMANTICS and SEMANTICS[n].note)


def tool_specs() -> list[dict]:
    record = "A record's key or uid, or new:N for one proposed earlier in this conversation."
    return [
        {"type": "function", "function": {
            "name": "propose_create_record",
            "description": "Propose creating an object (equipment, a screen station, a location…). Changes "
                           "nothing until the person confirms. Call list_types first to pick the type.",
            "parameters": {"type": "object", "properties": {
                "type": {"type": "string", "description": "The object type's name, as list_types gives it."},
                "name": {"type": "string"},
                "key": {"type": "string", "description": "Optional; left out, the workspace's pattern makes one."},
                "attributes": {"type": "object", "description": "Attribute key → value, keys of that type only."},
                "reason": {"type": "string", "description": "Why, from the records looked at."},
            }, "required": ["type", "name"]}}},
        {"type": "function", "function": {
            "name": "propose_update_record",
            "description": "Propose changing an existing object's name or attributes (only those given; null "
                           "clears one). Changes nothing until the person confirms.",
            "parameters": {"type": "object", "properties": {
                "record": {"type": "string", "description": record},
                "name": {"type": "string"},
                "attributes": {"type": "object"},
                "reason": {"type": "string"},
            }, "required": ["record"]}}},
        {"type": "function", "function": {
            "name": "propose_relation",
            "description": "Propose relating two objects (from —relation→ to), or with remove=true removing that "
                           "relation. Changes nothing until the person confirms. What each relation means, "
                           "from → to: " + _relation_guide(),
            "parameters": {"type": "object", "properties": {
                "from": {"type": "string", "description": record},
                "relation_type": {"type": "string", "enum": _relation_names()},
                "to": {"type": "string", "description": record},
                "remove": {"type": "boolean"},
                "reason": {"type": "string"},
            }, "required": ["from", "relation_type", "to"]}}},
        {"type": "function", "function": {
            "name": "propose_ticket",
            "description": "Propose opening a ticket — a fault, a request, a change, maintenance — on an object. "
                           "Changes nothing until the person confirms. The type is one of this workspace's ticket "
                           "types (an unknown one is refused with the list); a date the person gives as 'next "
                           "month' or 'tomorrow' is counted from today, given in your instructions.",
            "parameters": {"type": "object", "properties": {
                "title": {"type": "string"},
                "type": {"type": "string", "description": "A ticket type of this workspace, e.g. Change."},
                "object": {"type": "string", "description": "The object it is about: its key or uid."},
                "description": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "due_date": {"type": "string", "description": "YYYY-MM-DD, when it is wanted by."},
                "reason": {"type": "string"},
            }, "required": ["title"]}}},
    ] + _pull_request_specs()


def _pull_request_specs() -> list[dict]:
    """Offered only where an administrator installed the credential (app/ioc_engineer/pull_requests.py)."""
    from app.ioc_engineer import pull_requests
    if not pull_requests.enabled():
        return []
    return [{"type": "function", "function": {
        "name": "propose_ioc_pull_request",
        "description": "Propose a pull request with IOC files (a beamline IOC entry, an ibek-template and its "
                       "fixture, a driver's install.yml and ibek.support.yaml, a Dockerfile line) on one of: "
                       + ", ".join(pull_requests.repositories()) + ". Only when the person asks for a pull request. "
                       "Give each file's whole new content. It is checked now: every template, fixture and IOC "
                       "config in it must render and pass the ibek check, with the entity models of this and "
                       "earlier proposed pull requests counted as known; a refusal says what to fix. Nothing "
                       "leaves ARGUS until the person confirms; then ARGUS opens a draft pull request for review "
                       "and never merges. One pull request per repository: a new driver is one on "
                       "ibek-support-infn and one on ibek-templates.",
        "parameters": {"type": "object", "properties": {
            "repository": {"type": "string", "description": "owner/name, one of the allowed repositories"},
            "title": {"type": "string"},
            "description": {"type": "string", "description": "What it adds and why, for the reviewers"},
            "base": {"type": "string", "description": "Branch to merge into; default the repository's default"},
            "files": {"type": "array", "items": {"type": "object", "properties": {
                "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
            "reason": {"type": "string"},
        }, "required": ["repository", "title", "files"]}}}]


TOOL_NAMES = {"propose_create_record", "propose_update_record", "propose_relation", "propose_ioc_pull_request",
              "propose_ticket"}


class Refused(ValueError):
    """A proposal that cannot be made as it stands; the reason goes back to the model."""


def _types(db: Session, workspace_id: str) -> dict[str, Schema]:
    from app.intake.assist import _visible_types
    return {s.name.lower(): s for s in _visible_types(db, workspace_id, "objects")}


def _attribute_keys(db: Session, schema: Schema) -> set[str]:
    from app.services.attribute_validation import effective_attributes
    return {a.get("key") or a.get("name") for a in effective_attributes(db, schema)} - {None}


def _reference(db: Session, attr: dict, value, workspace_id: str):
    """A reference attribute's value as the record it names — its uid, its key, or its exact name among the
    records of the referenced type (and below) visible here — or why it names none."""
    from app.services.attribute_validation import _descendant_schema_uids, _is_reference_visible
    if value is None or value == "":
        return None
    if isinstance(value, list):
        return [_reference(db, attr, v, workspace_id) for v in value]
    label = f"{attr.get('name') or attr.get('key')} ({attr.get('key')})"
    ref = str(value).strip()
    allowed = None
    if attr.get("referenceSchemaUid"):
        allowed = {attr["referenceSchemaUid"]}
        if attr.get("includeChildren"):
            allowed |= _descendant_schema_uids(db, attr["referenceSchemaUid"])
    target = db.get(Asset, ref) or db.scalar(select(Asset).where(Asset.key == ref, Asset.deleted_at.is_(None)))
    if target is None and allowed:
        named = [a for a in db.scalars(select(Asset).where(Asset.name == ref, Asset.deleted_at.is_(None),
                                                           Asset.schema_uid.in_(allowed)))
                 if _is_reference_visible(db, a, workspace_id)]
        if len(named) == 1:
            target = named[0]
        elif len(named) > 1:
            raise Refused(f"{label} takes one record, and {len(named)} {attr.get('referenceType') or 'records'} are "
                          f"named {ref!r} ({', '.join(a.key for a in named[:5])}): give the key")
    if target is None:
        raise Refused(f"{label} takes a record, not text: {ref!r} names no "
                      f"{attr.get('referenceType') or 'record'} here — look it up and give its key")
    if allowed and target.schema_uid not in allowed:
        raise Refused(f"{label} takes a {attr.get('referenceType')} (or a kind of one); {target.key} is a "
                      f"{target.type or 'record'} of another kind")
    return target.uid


def _check_attributes(db: Session, schema: Schema, attributes, workspace_id: Optional[str] = None,
                      current: Optional[dict] = None, exclude_uid: Optional[str] = None) -> dict:
    """The attributes as the record would get them: a reference resolved to the record it names (by key, uid or
    exact name), and every value checked as the forms check it — so a proposal that cannot be applied is refused
    now, with the reason, rather than failing when the person applies it."""
    if attributes in (None, {}):
        return {}
    if not isinstance(attributes, dict):
        raise Refused("attributes must be an object of attribute key → value")
    from app.services.attribute_validation import check_attributes, effective_attributes
    defs = {a.get("key") or a.get("name"): a for a in effective_attributes(db, schema)}
    known = set(defs) - {None}
    unknown = sorted(k for k in attributes if k not in known)
    if unknown:
        usable = sorted(k for k in known if not k.startswith(SKIPPED_ATTRIBUTES))
        raise Refused(f"{schema.name} has no attribute {', '.join(unknown)}; its attributes are: {', '.join(usable)}")
    if workspace_id is None:
        return attributes
    out = dict(attributes)
    for k, v in attributes.items():
        label = defs[k].get("name") or k
        pending = isinstance(v, str) and re.fullmatch(r"\s*new:\d+\s*", v, re.IGNORECASE)
        if defs[k].get("type") == "reference":
            if pending:
                # A reference is stored as the record's uid, which a record still to be created does not have
                # (and a relation proposed instead would not fill the field: fields make relations, not back).
                raise Refused(f"{label} cannot take {v.strip()}, which is not created yet: leave it out, and once "
                              f"the person has created {v.strip()}, set {label} with propose_update_record and its key")
            out[k] = _reference(db, defs[k], v, workspace_id)
        elif pending:
            # In a text value new:N would be kept as the text "new:1" (a Product Model's vendor, then proposed to
            # the catalogue as a vendor called new:1).
            raise Refused(f"{label} is text: write the name itself, not {v.strip()}")
    whole = {kk: vv for kk, vv in {**(current or {}), **out}.items() if vv is not None}
    problems = check_attributes(db, schema, whole, workspace_id, Asset, exclude_uid=exclude_uid)
    if problems:
        raise Refused("; ".join(problems))
    return out


def _shown(db: Session, value) -> str:
    """A value for the person: a record by its key and name rather than its uid."""
    if isinstance(value, list):
        return ", ".join(_shown(db, v) for v in value)
    if isinstance(value, str) and len(value) == 36 and value.count("-") == 4:
        a = db.get(Asset, value)
        if a is not None:
            return f"{a.key} ({a.name})"
    return str(value)


class Proposer:
    """The write tools of one chat turn: each call checks and keeps one proposal."""

    def __init__(self, db: Session, workspace_id: str, conversation_id: str, turn_seq: int):
        self.db, self.workspace_id = db, workspace_id
        self.conversation_id, self.turn_seq = conversation_id, turn_seq

    # --- resolving what a proposal names ---------------------------------------------------------------

    def _new(self, ref: str) -> AskAction:
        try:
            number = int(ref.split(":", 1)[1])
        except (IndexError, ValueError):
            raise Refused(f"{ref} is not a proposed record (new:N)")
        action = self.db.scalar(select(AskAction).where(
            AskAction.conversation_id == self.conversation_id, AskAction.number == number,
            AskAction.kind == "create"))
        if action is None or action.status in ("discarded", "failed"):
            raise Refused(f"no record proposed in this conversation is new:{number}")
        return action

    def _existing(self, ref: str) -> Optional[Asset]:
        from app.services.visibility import asset_visible_in
        ref = (ref or "").strip()
        asset = self.db.get(Asset, ref) or self.db.scalar(select(Asset).where(Asset.key == ref))
        if asset is None or asset.deleted_at is not None or not asset_visible_in(asset, self.workspace_id):
            return None
        return asset

    def _endpoint(self, ref: str) -> tuple[Optional[Asset], Optional[AskAction], str]:
        """(asset, proposed creation, label) for a from/to."""
        ref = str(ref or "").strip()
        if ref.lower().startswith("new:"):
            action = self._new(ref)
            if action.status == "applied":
                asset = self.db.get(Asset, (action.result or {}).get("uid"))
                if asset is not None:
                    return asset, None, asset.key
            return None, action, f"new:{action.number} ({action.payload['name']})"
        asset = self._existing(ref)
        if asset is None:
            raise Refused(f"no record {ref!r} here: look it up and use its key")
        return asset, None, asset.key

    # --- the tools -----------------------------------------------------------------------------------------

    def __call__(self, name: str, arguments: dict) -> dict:
        handler = {"propose_create_record": self._create, "propose_update_record": self._update,
                   "propose_relation": self._relation, "propose_ioc_pull_request": self._pull_request,
                   "propose_ticket": self._ticket}[name]
        kind, payload, summary = handler(arguments or {})
        number = (self.db.scalar(select(AskAction.number).where(AskAction.conversation_id == self.conversation_id)
                                 .order_by(AskAction.number.desc()).limit(1)) or 0) + 1
        reason = str(arguments.get("reason") or "").strip()[:500]
        action = AskAction(id=str(uuid.uuid4()), conversation_id=self.conversation_id, turn_seq=self.turn_seq,
                           number=number, kind=kind, payload={**payload, **({"reason": reason} if reason else {})},
                           summary=summary, status="proposed")
        self.db.add(action)
        # Kept now: the chat's own save rolls back whatever is pending before it writes the answer.
        self.db.commit()
        out = {"proposed": True, "action": f"A{number}", "summary": summary,
               "status": "waiting for the person to confirm: nothing has been changed yet"}
        if kind == "create":
            out["ref"] = f"new:{number}"
        return {**out, "_action": view(action)}

    def _create(self, a: dict) -> tuple[str, dict, str]:
        types = _types(self.db, self.workspace_id)
        schema = types.get(str(a.get("type") or "").strip().lower())
        if schema is None:
            raise Refused(f"there is no object type {a.get('type')!r} here: call list_types and use one of its names")
        name = str(a.get("name") or "").strip()
        if not name:
            raise Refused("a record needs a name")
        key = str(a.get("key") or "").strip() or None
        if key and self.db.scalar(select(Asset.uid).where(Asset.key == key)) is not None:
            raise Refused(f"the key {key} is already taken")
        attributes = _check_attributes(self.db, schema, a.get("attributes"), self.workspace_id)
        payload = {"schema_uid": schema.uid, "type": schema.name, "name": name, "key": key, "attributes": attributes}
        details = "".join(f", {k} = {_shown(self.db, v)}" for k, v in attributes.items())
        return "create", payload, f"Create {schema.name} “{name}”" + (f" ({key})" if key else "") + details

    def _update(self, a: dict) -> tuple[str, dict, str]:
        ref = str(a.get("record") or "")
        if ref.lower().startswith("new:"):
            raise Refused("a record still to be created is changed by proposing it again with the right values")
        asset = self._existing(ref)
        if asset is None:
            raise Refused(f"no record {ref!r} here: look it up and use its key")
        if asset.workspace_id != self.workspace_id:
            raise Refused(f"{asset.key} belongs to workspace {asset.workspace_id}; it can only be changed there")
        schema = self.db.get(Schema, asset.schema_uid) if asset.schema_uid else None
        current = asset.attributes or {}
        attributes = (_check_attributes(self.db, schema, a.get("attributes"), self.workspace_id, current, asset.uid)
                      if schema else (a.get("attributes") or {}))
        attributes = {k: v for k, v in attributes.items() if current.get(k) != v}
        name = str(a.get("name") or "").strip() or None
        if name == asset.name:
            name = None
        if not attributes and not name:
            raise Refused(f"that changes nothing on {asset.key}")
        parts = ([f"name → {name}"] if name else []) + [
            f"{k} → {'(cleared)' if v is None else _shown(self.db, v)}" for k, v in attributes.items()]
        return "update", {"uid": asset.uid, "key": asset.key, "name": name, "attributes": attributes}, \
            f"Update {asset.key}: " + ", ".join(parts)

    def _ticket(self, a: dict) -> tuple[str, dict, str]:
        from datetime import date
        title = str(a.get("title") or "").strip()
        if not title:
            raise Refused("a ticket needs a title")
        kinds = {s.name.lower(): s for s in self.db.scalars(select(Schema).where(
            Schema.applies_to == "tickets", or_(Schema.workspace_id == self.workspace_id, Schema.is_global.is_(True))))}
        wanted = str(a.get("type") or "").strip().lower()
        schema = kinds.get(wanted) if wanted else None
        if wanted and schema is None:
            raise Refused(f"there is no ticket type {a.get('type')!r} here; the types are: "
                          + ", ".join(sorted(s.name for s in kinds.values())))
        asset = None
        if a.get("object"):
            asset = self._existing(str(a["object"]))
            if asset is None:
                raise Refused(f"no object {a['object']!r} here: look it up and use its key")
        priority = str(a.get("priority") or "").strip().lower() or None
        if priority and priority not in ("low", "medium", "high", "critical"):
            raise Refused("priority is one of low, medium, high, critical")
        due = str(a.get("due_date") or "").strip() or None
        if due:
            try:
                due = date.fromisoformat(due[:10]).isoformat()
            except ValueError:
                raise Refused("due_date is a date written YYYY-MM-DD")
        payload = {"title": title[:300], "schema_uid": schema.uid if schema else None,
                   "type": schema.name if schema else None, "asset_uid": asset.uid if asset else None,
                   "asset_key": asset.key if asset else None,
                   "description": str(a.get("description") or "").strip() or None, "priority": priority,
                   "due_date": due}
        summary = (f"Open {schema.name if schema else 'a ticket'} “{title}”"
                   + (f" on {asset.key}" if asset else "") + (f", {priority} priority" if priority else "")
                   + (f", wanted by {due}" if due else ""))
        return "ticket", payload, summary

    def _pull_request(self, a: dict) -> tuple[str, dict, str]:
        from app.ioc_engineer import pull_requests
        if not pull_requests.enabled():
            raise Refused("this installation does not open pull requests (no ARGUS_GITHUB_TOKEN)")
        title = str(a.get("title") or "").strip()
        if not title:
            raise Refused("a pull request needs a title")
        try:
            checked = pull_requests.check(a.get("repository"), a.get("files"),
                                          prior_models(self.db, self.conversation_id))
        except pull_requests.Refused as e:
            raise Refused(str(e))
        try:
            base = pull_requests.safe_branch(a.get("base"))
        except pull_requests.Refused as e:
            raise Refused(str(e))
        payload = {"repository": checked["repository"], "title": title[:200],
                   "description": str(a.get("description") or "").strip()[:5000],
                   "base": base, "files": checked["files"],
                   "checks": checked["checks"]}
        n = len(checked["files"])
        return "pull_request", payload, \
            f"Open a pull request on {checked['repository']}: “{title}” ({n} file{'s' if n != 1 else ''})"

    def _relation(self, a: dict) -> tuple[str, dict, str]:
        from app.ledger import registry
        relation = str(a.get("relation_type") or "").strip().lower()
        if relation not in _relation_names():
            raise Refused(f"{relation!r} is not a relation here; use one of: {', '.join(_relation_names())}")
        source, source_new, source_label = self._endpoint(a.get("from"))
        target, target_new, target_label = self._endpoint(a.get("to"))
        if source is not None and source.workspace_id != self.workspace_id:
            raise Refused(f"{source.key} belongs to workspace {source.workspace_id}: relate it from there")
        if source is not None and target is not None and source.uid == target.uid:
            raise Refused("a record cannot be related to itself")
        remove = bool(a.get("remove"))
        if remove:
            if source is None or target is None:
                raise Refused("only a relation that exists can be removed")
            exists = self.db.scalar(select(Relation.id).where(
                Relation.from_asset_uid == source.uid, Relation.to_asset_uid == target.uid,
                Relation.relation_type == relation))
            if exists is None:
                raise Refused(f"{source.key} —{relation}→ {target.key} is not a relation that exists")
        elif source is not None and target is not None:
            problems = registry.edge_violations(self.db, source, relation, target)
            if problems:
                raise Refused("; ".join(problems))
        payload = {"relation_type": relation,
                   "from": {"uid": source.uid} if source is not None else {"new": source_new.number},
                   "to": {"uid": target.uid} if target is not None else {"new": target_new.number}}
        verb = "Remove" if remove else "Relate"
        return ("unrelate" if remove else "relate"), payload, f"{verb} {source_label} —{relation}→ {target_label}"


# --- reading and applying ------------------------------------------------------------------------------------

def view(action: AskAction) -> dict:
    return {"id": action.id, "number": action.number, "turn_seq": action.turn_seq, "kind": action.kind,
            "summary": action.summary, "status": action.status, "result": action.result, "error": action.error,
            "reason": (action.payload or {}).get("reason")}


def of_conversation(db: Session, conversation_id: str) -> list[AskAction]:
    return list(db.scalars(select(AskAction).where(AskAction.conversation_id == conversation_id)
                           .order_by(AskAction.number)))


def context(db: Session, conversation_id: str) -> Optional[str]:
    """What became of the changes proposed so far, for the model's next turn."""
    lines = []
    for a in of_conversation(db, conversation_id):
        what = {"proposed": "waiting for confirmation", "applied": "applied", "failed": f"failed: {a.error}",
                "discarded": "discarded by the person"}[a.status]
        made = f" → {a.result.get('key')}" if a.status == "applied" and (a.result or {}).get("key") else ""
        lines.append(f"A{a.number} ({'new:' + str(a.number) + ', ' if a.kind == 'create' else ''}{a.summary}): "
                     f"{what}{made}")
    return ("Changes proposed earlier in this conversation:\n" + "\n".join(lines)) if lines else None


def prior_models(db: Session, conversation_id: str, before: Optional[int] = None) -> dict:
    """Entity models defined by pull requests proposed earlier in the conversation: a new driver's
    ibek.support.yaml (one repository) makes its types known to the template that uses them (another)."""
    from app.ioc_engineer import pull_requests
    models: dict = {}
    for a in of_conversation(db, conversation_id):
        if a.kind == "pull_request" and a.status in ("proposed", "applied") and (before is None or a.number < before):
            models.update(pull_requests._models_in((a.payload or {}).get("files") or {}))
    return models


def _detail(exc: HTTPException) -> str:
    d = exc.detail
    if isinstance(d, dict):
        return str(d.get("error") or d.get("detail") or json.dumps(d, default=str))
    return str(d)


def _resolve(db: Session, conversation_id: str, end: dict) -> str:
    if "uid" in end:
        return end["uid"]
    action = db.scalar(select(AskAction).where(AskAction.conversation_id == conversation_id,
                                               AskAction.number == end["new"]))
    if action is None or action.status != "applied":
        raise HTTPException(status_code=409, detail=f"it needs new:{end['new']}, which has not been created")
    return action.result["uid"]


def _permitted(db: Session, identity, workspace_id: str, kind: str) -> bool:
    from app.auth import OidcIdentity
    from app.services.permissions import resolve_permission
    if not isinstance(identity, OidcIdentity):
        # A token's scope was checked when it reached the workspace; but only a person opens a pull request.
        return kind != "pull_request"
    return resolve_permission(db, identity.user, workspace_id, PERMISSION[kind],
                              "tickets" if kind == "ticket" else "objects")


def _execute(db: Session, identity, workspace_id: str, action: AskAction) -> dict:
    from app.auth import get_current_user_id
    from app.routers import assets as forms
    from app.schemas.asset import AssetCreate, AssetUpdate, RelationCreate
    p = action.payload
    user_id = get_current_user_id(identity)
    if action.kind == "pull_request":
        from app.ioc_engineer import pull_requests
        actor = getattr(getattr(identity, "user", None), "email", None) or str(user_id)
        try:
            return pull_requests.open_pull_request(p, actor, prior_models(db, action.conversation_id, action.number))
        except pull_requests.Refused as e:
            raise HTTPException(status_code=422, detail=str(e))
    if action.kind == "ticket":
        from datetime import datetime as _dt
        from app.routers import issues
        from app.schemas.issue import IssueCreate
        issue = issues.create_issue(
            IssueCreate(uid=str(uuid.uuid4()), asset_uid=p.get("asset_uid"), schema_uid=p.get("schema_uid"),
                        title=p["title"], description=p.get("description"), priority=p.get("priority"),
                        due_date=_dt.fromisoformat(p["due_date"]) if p.get("due_date") else None,
                        created_by=str(user_id) if user_id else None),
            workspace_id=workspace_id, current_user_id=user_id, db=db, x_argus_client=None)
        return {"uid": issue.uid, "key": issue.key, "name": issue.title}
    if action.kind == "create":
        asset = forms.create_asset(
            AssetCreate(uid=str(uuid.uuid4()), schema_uid=p["schema_uid"], key=p.get("key"), name=p["name"],
                        attributes=dict(p.get("attributes") or {})),
            identity=identity, workspace_id=workspace_id, current_user_id=user_id, db=db)
        return {"uid": asset.uid, "key": asset.key, "name": asset.name}
    if action.kind == "update":
        asset = db.get(Asset, p["uid"])
        if asset is None:
            raise HTTPException(status_code=404, detail=f"{p['key']} no longer exists")
        merged = {k: v for k, v in {**(asset.attributes or {}), **(p.get("attributes") or {})}.items() if v is not None}
        body = AssetUpdate(**({"name": p["name"]} if p.get("name") else {}),
                           **({"attributes": merged} if p.get("attributes") else {}))
        out = forms.update_asset(p["uid"], body, identity=identity, workspace_id=workspace_id,
                                 current_user_id=user_id, db=db, if_match=None)
        return {"uid": out.uid, "key": out.key, "name": out.name}
    source = _resolve(db, action.conversation_id, p["from"])
    target = _resolve(db, action.conversation_id, p["to"])
    if action.kind == "relate":
        relation = forms.create_relation(RelationCreate(from_asset_uid=source, to_asset_uid=target,
                                                        relation_type=p["relation_type"]),
                                         identity=identity, workspace_id=workspace_id, db=db)
        return {"relation_id": relation.id}
    relation = db.scalar(select(Relation).where(Relation.from_asset_uid == source, Relation.to_asset_uid == target,
                                                Relation.relation_type == p["relation_type"]))
    if relation is None:
        raise HTTPException(status_code=404, detail="that relation no longer exists")
    forms.delete_relation(relation.id, identity=identity, workspace_id=workspace_id, db=db)
    return {"removed": True}


def apply(db: Session, identity, workspace_id: str, actor: str, conversation_id: str,
          ids: list[str]) -> list[dict]:
    """Apply the chosen proposals in the order they were made; each one stands or fails on its own (a relation
    to a record whose creation failed fails with it)."""
    now = datetime.now(timezone.utc)
    chosen = [a for a in of_conversation(db, conversation_id) if a.id in set(ids) and a.status == "proposed"]
    for action in chosen:
        try:
            if not _permitted(db, identity, workspace_id, action.kind):
                raise HTTPException(status_code=403, detail=f"you may not {PERMISSION[action.kind]} objects here")
            result = _execute(db, identity, workspace_id, action)
            action.status, action.result, action.error = "applied", result, None
        except HTTPException as exc:
            db.rollback()
            action = db.get(AskAction, action.id)
            action.status, action.error = "failed", _detail(exc)
        except Exception as exc:  # noqa: BLE001 — told to the person, never half-applied silently
            db.rollback()
            action = db.get(AskAction, action.id)
            action.status, action.error = "failed", f"{type(exc).__name__}: {exc}"
        action.decided_by, action.decided_at = actor, now
        db.commit()
    return [view(a) for a in of_conversation(db, conversation_id)]


def discard(db: Session, actor: str, conversation_id: str, ids: list[str]) -> list[dict]:
    now = datetime.now(timezone.utc)
    for action in of_conversation(db, conversation_id):
        if action.id in set(ids) and action.status == "proposed":
            action.status, action.decided_by, action.decided_at = "discarded", actor, now
    db.commit()
    return [view(a) for a in of_conversation(db, conversation_id)]
