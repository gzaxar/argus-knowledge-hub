"""Importing a GLPI snapshot: previewed in full, then applied through the fact ledger.

For each workspace the entity mapping sends items to:

* **Records** go in as one source stream (`glpi:<instance>@<workspace>`, parser `glpi`): each bound to its
  GLPI identity (glpi:<instance>:<itemtype>:<id>), so importing the same snapshot again changes nothing (the
  ledger skips identical content) and a changed one updates exactly what changed. References between them (a
  computer's location, a licence's product, a contract's suppliers) follow in a second stream once both ends
  exist. Positions with coordinates go through the GIS rules (an approved location is never overwritten).
* **Authority** is explicit (`authority.records`, `authority.tickets`):
    argus  (default) what ARGUS users edit wins: a GLPI change to a field edited here is reported as a conflict
           and the local value kept;
    glpi   GLPI is authoritative for what it maps: its changes apply, and a field edited here that GLPI then
           changes differently becomes a conflict for review in the ledger — never silently overwritten.
* **Nothing is retired because GLPI stopped listing it** (or moved it to its trash). The record stays,
  stated as before, and a review item (`retirement_candidate`) asks a person to retire it or keep it.
* **Tickets, problems and changes** become tickets of the IT kinds, linked to the records GLPI links them to;
  **documents** become attachments of those records and tickets, each once.

`plan` works all of this out without writing anything; `run` does it and returns the same report.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.glpi import mapping as m
from app.integrations.glpi import schema as glpi_schema
from app.integrations.glpi import source

PARSER = "glpi"
REFS_PARSER = "resolved"
RETIREMENT = "retirement_candidate"
ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR", "/data/attachments")
AUTHORITIES = ("argus", "glpi")


@dataclass
class Settings:
    """An import configuration's parameters (ImportConfig.params for source "glpi")."""
    base_url: str
    home_workspace: str
    prefix: str = "GLPI"
    entity_map: list = field(default_factory=list)
    authority: dict = field(default_factory=lambda: {"records": "argus", "tickets": "argus"})
    documents: bool = True
    tickets: bool = True
    schema_state: dict = field(default_factory=dict)    # {"approved": {...}} from schema.approve
    retired_refs: list = field(default_factory=list)    # decided: retired, no longer stated
    kept_refs: list = field(default_factory=list)       # decided: kept by ARGUS, no longer stated by GLPI

    @classmethod
    def of(cls, params: dict, home_workspace: str) -> "Settings":
        authority = {"records": "argus", "tickets": "argus", **(params.get("authority") or {})}
        for k, v in authority.items():
            if v not in AUTHORITIES:
                raise ValueError(f"authority.{k} must be one of {', '.join(AUTHORITIES)}")
        return cls(base_url=params["base_url"], home_workspace=home_workspace,
                   prefix=params.get("key_prefix") or "GLPI", entity_map=params.get("entity_map") or [],
                   authority=authority, documents=params.get("documents", True), tickets=params.get("tickets", True),
                   schema_state=params.get("schema") or {}, retired_refs=params.get("retired_refs") or [],
                   kept_refs=params.get("kept_refs") or [])

    @property
    def instance(self) -> str:
        return m.instance_id(self.base_url)


def stream_ids(instance: str, workspace_id: str) -> tuple[str, str]:
    return f"glpi:{instance}@{workspace_id}", f"glpi-refs:{instance}@{workspace_id}"


# --------------------------------------------------------------------------- building

@dataclass
class Built:
    records: dict = field(default_factory=dict)          # workspace -> {ref: Mapped}
    tickets: dict = field(default_factory=dict)          # workspace -> [ticket dict]
    documents: list = field(default_factory=list)        # [{id, name, filename, mime, sha1, links: [ref]}]
    outside: int = 0                                     # items of entities the map does not send anywhere
    awaiting_review: list = field(default_factory=list)  # custom itemtypes not yet approved
    unsupported: list = field(default_factory=list)
    trashed: set = field(default_factory=set)            # refs in GLPI's trash


def _people(db: Session, snapshot: dict) -> m.People:
    from app.models.group import Group
    from app.models.user import User
    # A login that names more than one ARGUS user names none: it stays a GLPI name rather than a guess.
    found: dict[str, set] = {}
    for u in db.scalars(select(User).where(User.active.is_(True))):
        for k in {u.username, u.email, (u.email or "").split("@")[0]}:
            if k:
                found.setdefault(k.lower(), set()).add(u.id)
    users = {k: next(iter(v)) for k, v in found.items() if len(v) == 1}
    named: dict[str, set] = {}
    for g in db.scalars(select(Group)):
        named.setdefault(g.name.lower(), set()).add(g.uid)
    groups = {k: next(iter(v)) for k, v in named.items() if len(v) == 1}
    return m.People(snapshot, users, groups)


def build(db: Session, settings: Settings, snapshot: dict) -> Built:
    out = Built()
    items = snapshot.get("items") or {}
    targets = m.entity_targets(snapshot, settings.entity_map)
    ctx = m.Context(instance=settings.instance, prefix=settings.prefix, people=_people(db, snapshot))
    approved = ((settings.schema_state or {}).get("approved") or {}).get("mapping") or {}
    for row in items.get("Software") or []:
        ctx.names[m.ref(ctx.instance, "Software", row["id"])] = row.get("name")
    by_ref: dict[str, m.Mapped] = {}

    def place(mapped: Optional[m.Mapped], workspace: Optional[str]) -> None:
        if mapped is None:
            return
        if mapped.deleted:
            out.trashed.add(mapped.ref)
            return
        if workspace is None:
            out.outside += 1
            return
        out.records.setdefault(workspace, {})[mapped.ref] = mapped
        by_ref[mapped.ref] = mapped

    order = list(m.EQUIPMENT) + ["Location", "Supplier", "Software", "SoftwareVersion", "SoftwareLicense", "Contract"]
    for itemtype in order:
        for row in items.get(itemtype) or []:
            mapped = m.map_item(snapshot, itemtype, row, ctx)
            if mapped is not None and itemtype in m.EQUIPMENT:
                ctx.owner_keys[mapped.ref] = mapped.key
            place(mapped, targets.get(mapped.entity) if mapped and mapped.entity is not None else settings.home_workspace)
    # GLPI's own types: only those a reviewed proposal mapped
    custom_itemtypes = [source.custom_itemtype(d) for d in (snapshot.get("custom") or {}).get("asset_definitions") or []]
    custom_itemtypes += [g.get("itemtype") for g in (snapshot.get("custom") or {}).get("generic_types") or [] if g.get("itemtype")]
    for itemtype in custom_itemtypes:
        rows = items.get(itemtype) or []
        if itemtype not in (approved.get("types") or {}):
            if rows:
                out.awaiting_review.append({"itemtype": itemtype, "records": len(rows)})
            continue
        for row in rows:
            mapped = _custom(snapshot, itemtype, row, ctx, approved)
            ctx.owner_keys[mapped.ref] = mapped.key
            place(mapped, targets.get(mapped.entity) if mapped.entity is not None else settings.home_workspace)
    # fields GLPI 10's fields plugin adds to standard items, as the approved mapping says
    for container, per_itemtype in ((snapshot.get("custom") or {}).get("plugin_values") or {}).items():
        for itemtype, rows in per_itemtype.items():
            wanted = ((approved.get("extensions") or {}).get(itemtype) or {}).get(container) or {}
            for row in rows:
                rec = by_ref.get(m.ref(ctx.instance, itemtype, row.get("items_id")))
                if rec is None:
                    continue
                for name, value in row.items():
                    if name in ("id", "items_id", "itemtype", "plugin_fields_containers_id", "entities_id", "links"):
                        continue
                    target = wanted.get(name.removeprefix("plugin_fields_").removesuffix("dropdowns_id")) or wanted.get(name)
                    if target and value not in (None, ""):
                        rec.attributes[target["key"]] = target["options"].get(str(value), value) if target["options"] else value
                    elif value not in (None, "", 0, "0"):
                        rec.unmapped[f"{container}.{name}"] = value
    # ports, after what they belong to
    for row in items.get("NetworkPort") or []:
        mapped = m.map_item(snapshot, "NetworkPort", row, ctx)
        if mapped is None:
            continue
        owner = by_ref.get(mapped.relations["port of"][0])
        if owner is None:
            if mapped.relations["port of"][0] in out.trashed:
                out.trashed.add(mapped.ref)          # its equipment is in GLPI's trash
            continue
        mapped.entity = owner.entity
        out.records[_workspace_of(out, owner.ref)][mapped.ref] = mapped
        by_ref[mapped.ref] = mapped
        if mapped.attributes.get("mac") and "mac" not in owner.attributes:
            owner.attributes["mac"] = mapped.attributes["mac"]
    for row in items.get("IPAddress") or []:
        owner = by_ref.get(m.ref(ctx.instance, row.get("mainitemtype") or "", row.get("mainitems_id")))
        if owner is None or not row.get("name"):
            continue
        if int(row.get("version") or 4) == 4 and "ip" not in owner.attributes:
            owner.attributes["ip"] = row["name"]
        else:
            owner.unmapped.setdefault("ip_addresses", []).append(row["name"])
    # links
    for row in items.get("Item_SoftwareVersion") or []:
        holder = by_ref.get(m.ref(ctx.instance, row.get("itemtype") or "", row.get("items_id")))
        version = m.ref(ctx.instance, "SoftwareVersion", row.get("softwareversions_id"))
        if holder is not None and version in by_ref:
            holder.relations.setdefault("has installed", []).append(version)
    for row in items.get("Contract_Item") or []:
        holder = by_ref.get(m.ref(ctx.instance, row.get("itemtype") or "", row.get("items_id")))
        contract = m.ref(ctx.instance, "Contract", row.get("contracts_id"))
        if holder is not None and contract in by_ref:
            holder.relations.setdefault("governed by", []).append(contract)
    for row in items.get("Contract_Supplier") or []:
        contract = by_ref.get(m.ref(ctx.instance, "Contract", row.get("contracts_id")))
        supplier = m.ref(ctx.instance, "Supplier", row.get("suppliers_id"))
        if contract is not None and supplier in by_ref:
            contract.references.setdefault("counterparty", [])
            contract.references["counterparty"].append(supplier)
    if settings.tickets:
        _tickets(snapshot, settings, ctx, targets, by_ref, out)
    if settings.documents:
        _documents(snapshot, ctx, by_ref, out)
    for f in (approved and (settings.schema_state.get("approved") or {}).get("proposal", {}).get("unsupported")) or []:
        out.unsupported.append(f)
    return out


def _workspace_of(built: Built, ref: str) -> str:
    return next(ws for ws, recs in built.records.items() if ref in recs)


def _custom(snapshot: dict, itemtype: str, row: dict, ctx: m.Context, approved: dict) -> m.Mapped:
    gid = str(row["id"])
    system = itemtype.rsplit("\\", 1)[-1].removesuffix("Asset") if itemtype.startswith("Glpi\\") else itemtype
    fields = (approved.get("fields") or {}).get(itemtype) or {}
    options = (approved.get("options") or {}).get(itemtype) or {}
    attrs = {"argus_source": "GLPI", "glpi_url": m.url(snapshot["instance"], itemtype, gid, system)}
    if row.get("date_mod"):
        attrs["argus_source_ref"] = str(row["date_mod"])
    mapped = m.Mapped(ref=m.ref(ctx.instance, itemtype, gid), itemtype=itemtype, glpi_id=gid,
                      entity=str(row["entities_id"]) if row.get("entities_id") is not None else None,
                      type=approved["types"][itemtype], key=f"{ctx.prefix}-{m._slug_abbr(system)}-{gid}",
                      name=str(row.get("name") or f"{system} {gid}"), attributes=attrs, unmapped={},
                      deleted=row.get("is_deleted") in (1, "1", True))
    used = {"name", "date_mod", "comment"}
    m._equipment(snapshot, itemtype, row, {"argus": mapped.type}, mapped, used, ctx)
    if m.text(row.get("comment")):
        attrs["description"] = m.text(row.get("comment"))
    for k, v in row.items():
        if k in fields:
            used.add(k)
            if v in (None, ""):
                continue
            opts = options.get(k) or {}
            if opts:
                v = [opts.get(str(x), x) for x in v] if isinstance(v, list) else opts.get(str(v), v)
            attrs[fields[k]] = v
    mapped.unmapped.update(m._rest(row, used, snapshot))
    return mapped


def _tickets(snapshot: dict, settings: Settings, ctx: m.Context, targets: dict, by_ref: dict, out: Built) -> None:
    items = snapshot.get("items") or {}
    links: dict[str, list] = {}
    for link_type, owner_type, column in (("Item_Ticket", "Ticket", "tickets_id"), ("Item_Problem", "Problem", "problems_id"),
                                          ("Change_Item", "Change", "changes_id")):
        for row in items.get(link_type) or []:
            target = m.ref(ctx.instance, row.get("itemtype") or "", row.get("items_id"))
            if target in by_ref:
                links.setdefault(m.ref(ctx.instance, owner_type, row.get(column)), []).append(target)
    for itemtype in ("Ticket", "Problem", "Change"):
        for row in items.get(itemtype) or []:
            t = m.ticket_fields(snapshot, itemtype, row, ctx)
            ws = targets.get(t["entity"]) if t["entity"] is not None else settings.home_workspace
            if ws is None:
                out.outside += 1
                continue
            t["links"] = sorted(set(links.get(t["ref"], [])))
            out.tickets.setdefault(ws, []).append(t)


def _documents(snapshot: dict, ctx: m.Context, by_ref: dict, out: Built) -> None:
    items = snapshot.get("items") or {}
    linked: dict[str, list] = {}
    for row in items.get("Document_Item") or []:
        linked.setdefault(str(row.get("documents_id")), []).append(
            m.ref(ctx.instance, row.get("itemtype") or "", row.get("items_id")))
    for row in items.get("Document") or []:
        if row.get("is_deleted") in (1, "1"):
            continue
        refs = linked.get(str(row["id"]), [])
        if not refs:
            continue
        out.documents.append({"id": str(row["id"]), "ref": m.ref(ctx.instance, "Document", row["id"]),
                              "name": row.get("name") or row.get("filename"), "filename": row.get("filename") or row.get("name"),
                              "mime": row.get("mime"), "sha1": row.get("sha1sum"), "links": refs,
                              "link_url": row.get("link")})


# --------------------------------------------------------------------------- the ledger side

def _previous(db: Session, stream_id: str) -> dict[str, dict]:
    """What the stream states now, by GLPI reference: the record as last imported."""
    from app.ledger.sources import _published_claims
    from app.models.ledger import LedgerStream
    if db.get(LedgerStream, stream_id) is None:
        return {}
    out: dict[str, dict] = {}
    for c in _published_claims(db, stream_id):
        rec = out.setdefault(c.source_ref, {"ref": c.source_ref, "attributes": {}, "relations": {}})
        if c.predicate == "exists" and isinstance(c.value, dict):
            rec.update({k: c.value.get(k) for k in ("type", "key", "name")})
        elif c.predicate.startswith("attr:"):
            rec["attributes"][c.predicate[5:]] = c.value
        elif c.predicate.startswith("rel:") and isinstance(c.value, dict):
            rec["relations"].setdefault(c.predicate[4:], []).append(c.value.get("ref"))
    return {k: v for k, v in out.items() if v.get("type")}


def _bound(db: Session, ref: str):
    from app.models.asset import Asset
    from app.models.ledger import IdentityBinding
    b = db.get(IdentityBinding, ref)
    return db.get(Asset, b.uid) if b is not None else None


def _diff(db: Session, rec: dict, previous: Optional[dict], authority: str) -> dict:
    """A record against ARGUS: create, update (which fields), unchanged; and conflicts with local edits."""
    asset = _bound(db, rec["ref"])
    if asset is None:
        return {"action": "create", "ref": rec["ref"], "key": rec["key"], "type": rec["type"], "name": rec["name"]}
    before = (previous or {}).get("attributes") or {}
    have = asset.attributes or {}
    changed, conflicts, kept = [], [], []
    for k, new in rec["attributes"].items():
        cur, prev = have.get(k), before.get(k)
        if cur == new:
            continue
        if prev is None or cur == prev:
            changed.append(k)
        elif prev == new:
            kept.append(k)                      # edited here, unchanged in GLPI: the local value stays
        else:
            # A person's confirmed value holds against any source; the ledger opens a review item either way.
            conflicts.append({"field": k, "argus": cur, "glpi": new, "previously": prev,
                              "outcome": "kept the ARGUS value" if authority == "argus"
                              else "kept the ARGUS value until reviewed"})
    if rec["name"] != asset.name and (previous or {}).get("name") in (None, asset.name):
        changed.append("name")
    if conflicts:
        from app.services.visibility import restricted_fields
        classes = restricted_fields(db, asset.schema_uid)
        for c in conflicts:
            if c["field"] in classes:
                c["restricted"] = classes[c["field"]]
    out = {"ref": rec["ref"], "uid": asset.uid, "key": asset.key, "type": rec["type"], "name": rec["name"],
           "action": "update" if changed else "unchanged", "fields": changed, "local_edits_kept": kept}
    if conflicts:
        out["conflicts"] = conflicts
    return out


def redact(report: dict, grants) -> dict:
    """The report as this viewer may see it: values of restricted fields (a licence key) left out."""
    for w in report.get("workspaces", {}).values():
        for c in w.get("conflicts", []):
            if c.get("restricted") and not grants.allows(c["restricted"]):
                c["argus"] = c["glpi"] = c["previously"] = "(restricted)"
    return report


def plan(db: Session, settings: Settings, snapshot: dict) -> dict:
    """Everything the import would do, per workspace, without writing anything."""
    from app.packages.importers import requires
    from app.packages.requirements import missing
    from app.services import asset_types
    built = build(db, settings, snapshot)
    status = glpi_schema.status(settings.schema_state, snapshot)
    report = {"instance": settings.instance, "version": source.version(snapshot), "schema_status": status,
              "outside_entity_map": built.outside, "awaiting_schema_review": built.awaiting_review,
              "unsupported": built.unsupported, "workspaces": {}}
    for ws in sorted(set(built.records) | set(built.tickets)):
        recs = built.records.get(ws, {})
        stream, _refs = stream_ids(settings.instance, ws)
        previous = _previous(db, stream)
        usable = asset_types.resolve_type_uids(db, ws)
        lacking = missing(db, ws, requires("glpi"))
        rows, no_type = [], []
        for rec in sorted(recs.values(), key=lambda r: r.ref):
            if rec.type not in usable:
                no_type.append({"ref": rec.ref, "type": rec.type})
                continue
            rows.append(_diff(db, rec.registry(), previous.get(rec.ref), settings.authority["records"]))
        gone = sorted(set(previous) - set(recs) - set(settings.retired_refs) - set(settings.kept_refs))
        candidates = [{"ref": r, "key": previous[r].get("key"), "name": previous[r].get("name"),
                       "reason": "in GLPI's trash" if r in built.trashed else "no longer listed by GLPI"}
                      for r in gone]
        tickets = [_ticket_diff(db, ws, t, settings.authority["tickets"]) for t in built.tickets.get(ws, [])]
        report["workspaces"][ws] = {
            "missing_packages": lacking,
            "creates": [r for r in rows if r["action"] == "create"],
            "updates": [r for r in rows if r["action"] == "update"],
            "unchanged": sum(1 for r in rows if r["action"] == "unchanged"),
            "conflicts": [{"ref": r["ref"], "key": r["key"], **c} for r in rows for c in r.get("conflicts", [])],
            "local_edits_kept": [{"ref": r["ref"], "key": r["key"], "fields": r["local_edits_kept"]}
                                 for r in rows if r.get("local_edits_kept")],
            "retirement_candidates": candidates,
            "types_missing": no_type,
            "locations": sum(1 for r in recs.values() if r.coordinates),
            "tickets": {"creates": sum(1 for t in tickets if t["action"] == "create"),
                        "updates": sum(1 for t in tickets if t["action"] == "update"),
                        "unchanged": sum(1 for t in tickets if t["action"] == "unchanged"),
                        "conflicts": [c for t in tickets for c in t.get("conflicts", [])]},
            "documents": sum(1 for d in built.documents if any(l in recs for l in d["links"])),
        }
    return report


# --------------------------------------------------------------------------- tickets

TICKET_FIELDS = ("title", "description", "state", "priority")


def _find_ticket(db: Session, workspace_id: str, source_key: str):
    from app.models.issue import Issue
    return db.scalar(select(Issue).where(Issue.workspace_id == workspace_id,
                                         Issue.attributes["argus_source_key"].astext == source_key))


def _ticket_diff(db: Session, workspace_id: str, t: dict, authority: str) -> dict:
    issue = _find_ticket(db, workspace_id, t["ref"])
    if issue is None:
        return {"action": "create", "ref": t["ref"]}
    last = (issue.attributes or {}).get("glpi_imported") or {}
    changed, conflicts = [], []
    for f in TICKET_FIELDS:
        cur, new, prev = getattr(issue, f), t[f], last.get(f)
        if cur == new:
            continue
        if prev is None or cur == prev:
            changed.append(f)
        elif prev != new:
            conflicts.append({"ref": t["ref"], "field": f, "argus": cur, "glpi": new,
                              "outcome": "kept the ARGUS value" if authority == "argus" else "applied the GLPI value"})
    status_changed = (issue.attributes or {}).get("argus_source_status") != t["attributes"].get("argus_source_status")
    return {"action": "update" if changed or status_changed else "unchanged", "ref": t["ref"], "fields": changed,
            "conflicts": conflicts, "issue": issue}


def _write_tickets(db: Session, workspace_id: str, settings: Settings, tickets: list, actor: str) -> dict:
    from app.models.asset_subresources import AssetTicket
    from app.models.issue import Issue
    from app.packages.install import kind_uid
    from app.models.schema import Schema
    counts = {"created": 0, "updated": 0, "unchanged": 0, "conflicts": 0}
    now = datetime.now(timezone.utc)
    for t in tickets:
        d = _ticket_diff(db, workspace_id, t, settings.authority["tickets"])
        imported = {f: t[f] for f in TICKET_FIELDS}
        if d["action"] == "create":
            schema_uid = kind_uid(workspace_id, "ticket_types", t["kind"])
            issue = Issue(uid=str(uuid.uuid4()), workspace_id=workspace_id, title=t["title"], description=t["description"],
                          state=t["state"], priority=t["priority"], labels=["glpi"], created_by=actor,
                          schema_uid=schema_uid if db.get(Schema, schema_uid) is not None else None,
                          attributes={**t["attributes"], **({"glpi_unmapped": json.dumps(t["unmapped"], sort_keys=True,
                                                                                        default=str)} if t["unmapped"] else {}),
                                      "glpi_imported": imported},
                          closed_at=now if t["state"] in ("closed", "resolved", "refused") else None)
            db.add(issue)
            counts["created"] += 1
        else:
            issue = d["issue"]
            attrs = dict(issue.attributes or {})
            for f in TICKET_FIELDS:
                if f in d["fields"] or (settings.authority["tickets"] == "glpi" and any(c["field"] == f for c in d["conflicts"])):
                    setattr(issue, f, t[f])
            attrs.update({k: v for k, v in t["attributes"].items()})
            attrs["glpi_imported"] = imported
            issue.attributes = attrs
            counts["updated" if d["action"] == "update" else "unchanged"] += 1
            counts["conflicts"] += len(d["conflicts"])
        db.flush()
        for target in t["links"]:
            asset = _bound(db, target)
            if asset is None:
                continue
            if issue.asset_uid is None:
                issue.asset_uid = asset.uid
            if db.scalar(select(AssetTicket.uid).where(AssetTicket.asset_uid == asset.uid,
                                                       AssetTicket.ticket_key == t["ref"])) is None:
                db.add(AssetTicket(uid=str(uuid.uuid4()), asset_uid=asset.uid, ticket_key=t["ref"], summary=t["title"],
                                   type=t["kind"], status=t["attributes"]["argus_source_status"], created=now, updated=now))
    db.flush()
    return counts


# --------------------------------------------------------------------------- running

def _content(records: list[dict]) -> bytes:
    return json.dumps({"records": sorted(records, key=lambda r: r["ref"])}, sort_keys=True, ensure_ascii=False,
                      default=str).encode()


def _authority_policy(db: Session, settings: Settings, streams: list[str], actor: str) -> None:
    """With GLPI authoritative, a rule per stream ranks its claims authoritative (protected inventory fields
    included, with the reason recorded); with ARGUS authoritative, the defaults already rank a person's edit
    above a source's statement. The active policy changes only when the rules do."""
    from app.ledger import engine
    from app.ledger.policy import DEFAULT_POLICY
    from app.models.ledger import LedgerPolicy
    current = db.scalar(select(LedgerPolicy).order_by(LedgerPolicy.activated_at.desc()).limit(1))
    body = json.loads(json.dumps(current.body if current else DEFAULT_POLICY))
    rules = [r for r in body.get("rules") or [] if not str(r.get("id", "")).startswith(
        tuple(f"glpi-authority:{s}" for s in streams))]
    if settings.authority["records"] == "glpi":
        for s in streams:
            rules.append({"id": f"glpi-authority:{s}", "match": {"source_instance": s}, "rank": "authoritative",
                          "allow_dominant": f"GLPI ({settings.instance}) is authoritative for the records it maps "
                                            f"into {s.split('@', 1)[1]}, by the import configuration"})
    admitted = set(((current.vocabulary or {}).get("streams") or []) if current else [])
    if rules != (body.get("rules") or []) or not set(streams) <= admitted:
        # A changed rule, or a stream the active policy does not know yet: its claims stay pending until
        # the policy is activated again with it in the vocabulary.
        body["rules"] = rules
        engine.activate_policy(db, body, actor=actor)


def run(db: Session, settings: Settings, snapshot: dict, actor: str, *, document_reader=None) -> dict:
    """Import the snapshot. Returns the plan it carried out, with what was done. The caller commits."""
    from app.ledger import engine
    from app.packages.importers import requires
    from app.packages.requirements import require
    from app.services import asset_types
    report = plan(db, settings, snapshot)
    built = build(db, settings, snapshot)
    observed = snapshot.get("read_at") or datetime.now(timezone.utc).isoformat()
    for ws, wreport in report["workspaces"].items():
        require(db, ws, *requires("glpi"))
        recs = built.records.get(ws, {})
        usable = asset_types.resolve_type_uids(db, ws)
        main, refs_stream = stream_ids(settings.instance, ws)
        previous = _previous(db, main)
        current = [r.registry() for r in recs.values() if r.type in usable]
        stated = {r["ref"] for r in current}
        carried = [previous[r] for r in previous if r not in stated and r not in settings.retired_refs
                   and r not in settings.kept_refs]
        records = current + [{k: v for k, v in c.items() if k in ("ref", "type", "key", "name", "attributes", "relations")}
                             for c in carried]
        types = sorted({r["type"] for r in records})
        engine.register_stream(db, main, ws, "glpi", may_create=types)
        stream = db.get(engine.LedgerStream, main)
        stream.may_create = sorted(set(stream.may_create or []) | set(types))
        engine.register_stream(db, refs_stream, ws, "glpi", may_create=[])
        _authority_policy(db, settings, [main, refs_stream], actor)
        content = _content(records)
        result = engine.ingest(db, main, revision=hashlib.sha256(content).hexdigest()[:16], content=content,
                               observed_at=observed, parser=PARSER, cause=f"GLPI import by {actor}")
        wreport["ledger"] = {k: result.get(k) for k in ("state", "appeared", "disappeared", "evidence_changed",
                                                        "parse_skipped")}
        wreport["references"] = _references(db, refs_stream, recs, observed, actor)
        wreport["retirement_candidates_open"] = _candidates(db, ws, [c["ref"] for c in wreport["retirement_candidates"]],
                                                            built.trashed, settings)
        rows = [{"key": r.key, "latitude": r.coordinates[0], "longitude": r.coordinates[1]}
                for r in recs.values() if r.coordinates and r.type in usable]
        if rows:
            from app.services.spatial import import_locations
            wreport["locations_result"] = import_locations(db, ws, rows, source_name=f"GLPI {settings.instance}",
                                                           actor=actor, dry_run=False)["counts"]
        wreport["tickets_result"] = _write_tickets(db, ws, settings, built.tickets.get(ws, []), actor)
        wreport["documents_result"] = _write_documents(db, ws, settings, snapshot, built, recs, document_reader, actor)
    db.flush()
    return report


def _references(db: Session, stream_id: str, recs: dict, observed, actor: str) -> dict:
    """The reference fields, now that both ends are ARGUS records: a second stream states them as ids."""
    from app.ledger import engine
    claims, unresolved = [], 0
    for rec in recs.values():
        for key, target in rec.references.items():
            targets = target if isinstance(target, list) else [target]
            uids = []
            for t in targets:
                a = _bound(db, t)
                if a is None:
                    unresolved += 1
                else:
                    uids.append(a.uid)
            if not uids:
                continue
            claims.append({"source_ref": rec.ref, "predicate": f"attr:{key}",
                           "value": uids if isinstance(target, list) else uids[0],
                           "rule_id": "glpi.reference/1", "evidence": {"refs": targets}})
    content = json.dumps(sorted(claims, key=lambda c: (c["source_ref"], c["predicate"])), sort_keys=True).encode()
    result = engine.ingest(db, stream_id, revision=hashlib.sha256(content).hexdigest()[:16], content=content,
                           observed_at=observed, parser=REFS_PARSER, cause=f"GLPI references by {actor}")
    return {"stated": len(claims), "unresolved": unresolved, "state": result.get("state")}


def _candidates(db: Session, workspace_id: str, refs: list[str], trashed: set, settings: Settings) -> int:
    """Open a review item for each record GLPI no longer lists; close those it lists again."""
    from app.models.ledger import Conflict, ConflictEvent
    now = datetime.now(timezone.utc)
    wanted = {}
    for r in refs:
        a = _bound(db, r)
        if a is not None and a.workspace_id == workspace_id:
            wanted[hashlib.sha256(f"{RETIREMENT}:{a.uid}".encode()).hexdigest()[:24]] = (a, r)
    existing = {c.conflict_id: c for c in db.scalars(select(Conflict).where(
        Conflict.workspace_id == workspace_id, Conflict.conflict_type == RETIREMENT,
        Conflict.detail["instance"].astext == settings.instance))}
    for cid, (a, r) in wanted.items():
        detail = {"source": r, "instance": settings.instance,
                  "reason": "in GLPI's trash" if r in trashed else "no longer listed by GLPI",
                  "decide": "retire it, or keep it as an ARGUS record (POST /v1/glpi/{config}/retirement-candidates)"}
        if cid in existing:
            existing[cid].detail = detail
            continue
        ev = ConflictEvent(conflict_id=cid, kind="opened", conflict_type=RETIREMENT, subject_uid=a.uid, detail=detail,
                           cause="glpi import", at=now)
        db.add(ev)
        db.flush()
        db.add(Conflict(conflict_id=cid, conflict_type=RETIREMENT, severity="non-blocking", workspace_id=workspace_id,
                        subject_uid=a.uid, detail=detail, opened_seq=ev.seq))
    for cid, row in existing.items():
        if cid not in wanted:
            db.add(ConflictEvent(conflict_id=cid, kind="resolved", conflict_type=RETIREMENT, subject_uid=row.subject_uid,
                                 detail=row.detail, cause="listed by GLPI again", at=now))
            db.delete(row)
    db.flush()
    return len(wanted)


def _write_documents(db: Session, workspace_id: str, settings: Settings, snapshot: dict, built: Built, recs: dict,
                     reader, actor: str) -> dict:
    """Each GLPI document once, as an attachment of every record and ticket here GLPI links it to."""
    from app.models.attachment import Attachment
    counts = {"attached": 0, "already": 0, "unreadable": 0}
    tickets = {t["ref"]: t for t in built.tickets.get(workspace_id, [])}
    for d in built.documents:
        here = [l for l in d["links"] if l in recs or l in tickets]
        for link in here:
            backend_id = f"{d['ref']}@{link}"
            if db.scalar(select(Attachment.uid).where(Attachment.workspace_id == workspace_id,
                                                      Attachment.backend_id == backend_id)) is not None:
                counts["already"] += 1
                continue
            data = source.file_bytes(snapshot, d["id"])
            if data is None and reader is not None:
                try:
                    data = reader(d["id"])
                except Exception:                             # noqa: BLE001 — reported, not fatal
                    data = None
            if data is None:
                counts["unreadable"] += 1
                continue
            asset = _bound(db, link) if link in recs else None
            issue = _find_ticket(db, workspace_id, link) if link in tickets else None
            if asset is None and issue is None:
                continue
            os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
            att_uid = str(uuid.uuid4())
            path = os.path.join(ATTACHMENTS_DIR, att_uid)
            with open(path, "wb") as f:
                f.write(data)
            db.add(Attachment(uid=att_uid, workspace_id=workspace_id, asset_uid=asset.uid if asset else None,
                              issue_uid=issue.uid if issue else None, filename=d["filename"] or d["name"],
                              mime_type=d["mime"], file_size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                              author=actor, storage_path=path, backend_id=backend_id,
                              backend_url=m.url(snapshot["instance"], "Document", d["id"])))
            counts["attached"] += 1
    db.flush()
    return counts


# --------------------------------------------------------------------------- retirement decisions

def decide_retirement(db: Session, workspace_id: str, settings: Settings, ref: str, decision: str, actor: str,
                      reason: Optional[str] = None) -> dict:
    """A person's decision on a record GLPI no longer lists: `retire` it (its history stays), or `keep` it as
    an ARGUS record that GLPI no longer states. Either way the import stops stating it."""
    from app.ledger import engine, service
    from app.models.ledger import Conflict, ConflictEvent
    asset = _bound(db, ref)
    if asset is None or asset.workspace_id != workspace_id:
        raise ValueError("no record of that GLPI reference in this workspace")
    if decision == "retire":
        service.retire_record(db, workspace_id, actor, asset.uid, reason or "no longer in GLPI")
    elif decision == "keep":
        engine.apply_decisions(db, workspace_id, actor, [service.confirm_value(asset.uid, "exists", "present")])
    else:
        raise ValueError("decide retire or keep")
    cid = hashlib.sha256(f"{RETIREMENT}:{asset.uid}".encode()).hexdigest()[:24]
    row = db.get(Conflict, cid)
    if row is not None:
        db.add(ConflictEvent(conflict_id=cid, kind="resolved", conflict_type=RETIREMENT, subject_uid=asset.uid,
                             detail={**(row.detail or {}), "decision": decision, "by": actor},
                             cause=f"{decision} by {actor}", at=datetime.now(timezone.utc)))
        db.delete(row)
    db.flush()
    return {"ref": ref, "uid": asset.uid, "decision": decision}
