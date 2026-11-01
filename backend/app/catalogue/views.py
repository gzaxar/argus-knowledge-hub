"""What the catalogue pages read (docs/catalogue-collections.md §5), and the decisions a person takes on one
field after an install: browse the Product Models, a model's values with where each comes from, and a field
made managed, kept local, or proposed back to Git.

A value's source is one of:
    collection   managed, and the record has the value the release stated
    edited       managed, but the record was changed here since: the next release would see a conflict, so a
                 person says which it is (local override, correction for Git, or back to the collection's)
    local        a local override: releases do not change it
    correction   kept here, and proposed back to Git
    record       the record's own (no entry, or a field the collection does not state)
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalogue.install import (CatalogueProblem, MODEL_FIELDS, NOT_STORED, VENDOR_FIELDS, _changes, _current,
                                   _same, entries)
from app.catalogue.loader import Collection, load_tree
from app.models.asset import Asset
from app.models.catalogue_entry import CatalogueEntry, CatalogueInstallation
from app.models.workspace import Workspace
from app.services.catalogue_mapping import catalogue_types

FIELD_LABELS = {"name": "Name", "vendor": "Vendor", "model_code": "Model code", "device_class": "Device class",
                "datasheet_url": "Datasheet", "firmware_version": "Firmware", "eol_date": "End of life",
                "typical_spares": "Typical spares", "description": "Description", "website": "Website"}


def _units_by_model(db: Session) -> dict[str, int]:
    pm = Asset.attributes["product_model"].astext
    return dict(db.execute(select(pm, func.count()).where(pm.isnot(None), Asset.deleted_at.is_(None))
                           .group_by(pm)).all())


LOCAL, UNSPECIFIED = "local", "unspecified"


def collection_domains(db: Session, workspace_id: str) -> dict[str, list[str]]:
    """collection -> the domains its latest installation here recorded (docs/system-catalogue.md C4); a
    collection installed before domains were kept says `unspecified`."""
    out: dict[str, list[str]] = {}
    for row in db.scalars(select(CatalogueInstallation).where(CatalogueInstallation.workspace_id == workspace_id)
                          .order_by(CatalogueInstallation.id)):
        out[row.collection_id] = list(row.domains or [UNSPECIFIED])
    return out


def domain_names() -> dict[str, str]:
    """A domain's name: its package's, `local` for models made here, `unspecified` for the rest."""
    from app.packages.loader import available
    return {**{pid: p.name for pid, p in available().items()}, LOCAL: "Made here (local)",
            UNSPECIFIED: "Collection without a domain", "catalogue": "Every domain"}


def browse(db: Session, workspace_id: str, *, q: Optional[str] = None, device_class: Optional[str] = None,
           vendor: Optional[str] = None, status: Optional[str] = None, collection: Optional[str] = None,
           domain: Optional[str] = None, limit: int = 500) -> dict:
    """The catalogue's Product Models, with their catalogue id and collection or `local`, their domains, the
    facets, and the navigator's tree: domain › device class › vendor, counted, over the models the search,
    status and collection leave (a model of several domains counts in each)."""
    model_schema, _ = catalogue_types(db, workspace_id)
    rows = list(db.scalars(select(Asset).where(
        Asset.schema_uid == model_schema.uid, Asset.workspace_id == workspace_id, Asset.deleted_at.is_(None),
        Asset.record_status.notin_(("Merged",))).order_by(Asset.name)))
    by_record = {e.record_uid: e for e in entries(db, workspace_id).values()}
    units = _units_by_model(db)
    domains_of = collection_domains(db, workspace_id)
    out, facets = [], {"device_class": {}, "vendor": {}, "collection": {}, "status": {}, "domain": {}}
    tree: dict = {}
    needle = (q or "").strip().lower()
    for r in rows:
        a = r.attributes or {}
        e = by_record.get(r.uid)
        st = "retired" if (e and e.status == "retired") or r.record_status == "Retired" else (
            "catalogue" if e else "local")
        item = {"uid": r.uid, "key": r.key, "name": r.name, "vendor": a.get("vendor"),
                "vendor_ref": a.get("vendor_ref"), "model_code": a.get("model_code"),
                "device_class": a.get("device_class"), "catalogue_id": e.catalogue_id if e else None,
                "collection": e.collection_id if e else None, "version": e.collection_version if e else None,
                "status": st, "review": bool(e and (e.conflicts or e.corrections)), "units": units.get(r.uid, 0),
                "domains": domains_of.get(e.collection_id, [UNSPECIFIED]) if e else [LOCAL]}
        if needle and not any(needle in str(item.get(k) or "").lower()
                              for k in ("name", "key", "model_code", "vendor", "catalogue_id")):
            continue
        for facet in ("device_class", "vendor", "collection", "status"):
            value = item[facet] or "—"
            facets[facet][value] = facets[facet].get(value, 0) + 1
        if status and status != "all" and item["status"] != status or collection and item["collection"] != collection:
            continue
        for d in item["domains"]:
            facets["domain"][d] = facets["domain"].get(d, 0) + 1
            node = tree.setdefault(d, {"count": 0, "classes": {}})
            node["count"] += 1
            cls = node["classes"].setdefault(item["device_class"] or "—", {"count": 0, "vendors": {}})
            cls["count"] += 1
            v = item["vendor"] or "—"
            cls["vendors"][v] = cls["vendors"].get(v, 0) + 1
        if domain and domain not in item["domains"]:
            continue
        if device_class and item["device_class"] != device_class:
            continue
        if vendor and item["vendor"] != vendor:
            continue
        if status and status != "all" and item["status"] != status:
            continue
        if collection and item["collection"] != collection:
            continue
        out.append(item)
    names = domain_names()
    navigator = [{"domain": d, "name": names.get(d, d), "count": n["count"],
                  "classes": [{"device_class": c, "count": cn["count"],
                               "vendors": [{"vendor": v, "count": vn} for v, vn in sorted(cn["vendors"].items())]}
                              for c, cn in sorted(n["classes"].items())]}
                 for d, n in sorted(tree.items(), key=lambda kv: (kv[0] in (LOCAL, UNSPECIFIED), names.get(kv[0], kv[0])))]
    return {"workspace_id": workspace_id, "total": len(out), "models": out[:limit], "facets": facets,
            "navigator": navigator, "domain_names": names}


def _entry_in_tree(tree: dict[str, Collection], catalogue_id: str, collection_id: str):
    c = tree.get(collection_id)
    if c is None:
        return None, None
    for e in c.entries():
        if e.id == catalogue_id:
            return c, e
    return c, None


def _source(e: Optional[CatalogueEntry], f: str, current: Any) -> str:
    if e is None or f not in (e.stated or {}):
        return "record"
    if f in (e.corrections or {}):
        return "correction"
    if f in (e.managed_fields or []):
        return "collection" if _same(current, e.stated[f]) else "edited"
    return "local"


def provenance(db: Session, uid: str, readable: set[str], tree: Optional[dict[str, Collection]] = None) -> dict:
    """A catalogue record: each value with its source, what the collection states that the type cannot hold
    yet, the units of it per workspace (by name only where the reader may read), and the releases."""
    record = db.get(Asset, uid)
    if record is None or record.deleted_at is not None:
        raise LookupError("no such record")
    e = db.scalar(select(CatalogueEntry).where(CatalogueEntry.record_uid == uid))
    kind = e.kind if e else ("vendor" if record.type == "Vendor" else "model")
    names = VENDOR_FIELDS if kind == "vendor" else MODEL_FIELDS
    fields = []
    for f in names:
        cur = _current(record, f)
        shown = (record.attributes or {}).get("vendor") if f == "vendor" else cur
        fields.append({"field": f, "label": FIELD_LABELS.get(f, f), "value": shown, "ref": cur if f == "vendor" else None,
                       "source": _source(e, f, cur),
                       "collection_value": (e.stated or {}).get(f) if e else None,
                       "conflict": (e.conflicts or {}).get(f) if e else None,
                       "correction": (e.corrections or {}).get(f) if e else None})
    out: dict = {"uid": record.uid, "key": record.key, "name": record.name, "type": record.type, "kind": kind,
                 "record_status": record.record_status, "is_global": record.is_global, "fields": fields,
                 "entry": None, "stated_only": {}, "relations": [], "sources": [], "retired": None, "units": [],
                 "releases": []}
    if e is not None:
        out["entry"] = {"catalogue_id": e.catalogue_id, "collection_id": e.collection_id,
                        "collection_version": e.collection_version, "status": e.status,
                        "adopted_at": e.adopted_at, "adopted_by": e.adopted_by,
                        "managed_fields": e.managed_fields}
        out["retired"] = e.retired
        c, entry = _entry_in_tree(tree if tree is not None else load_tree(), e.catalogue_id, e.collection_id)
        if entry is not None:
            data = entry.data
            out["stated_only"] = {k: data[k] for k in NOT_STORED if k in data and k != "relations"}
            out["relations"] = data.get("relations") or []
            out["sources"] = data.get("sources") or []
            if c is not None and c.version != e.collection_version:
                out["entry"]["shipped_version"] = c.version
        out["releases"] = [{"version": h.version, "from_version": h.from_version, "installed_at": h.installed_at,
                            "installed_by": h.installed_by}
                           for h in db.scalars(select(CatalogueInstallation).where(
                               CatalogueInstallation.workspace_id == e.workspace_id,
                               CatalogueInstallation.collection_id == e.collection_id)
                               .order_by(CatalogueInstallation.id.desc()))]
    if kind == "model":
        pm = Asset.attributes["product_model"].astext
        counts = db.execute(select(Asset.workspace_id, func.count()).where(pm == uid, Asset.deleted_at.is_(None))
                            .group_by(Asset.workspace_id)).all()
        names_of = {w.id: w.name for w in db.scalars(select(Workspace).where(
            Workspace.id.in_([w for w, _ in counts])))}
        hidden = 0
        for ws, n in sorted(counts):
            if ws in readable:
                out["units"].append({"workspace_id": ws, "name": names_of.get(ws, ws), "count": n})
            else:
                hidden += n
        if hidden:
            out["units"].append({"workspace_id": None, "name": "other workspaces", "count": hidden})
    return out


DECISIONS = ("managed", "local", "propose")


def decide_field(db: Session, workspace_id: str, actor: str, catalogue_id: str, field: str, decision: str,
                 reason: Optional[str] = None) -> CatalogueEntry:
    """One field of an installed entry, after the fact: `managed` takes the collection's value (and later
    releases update it), `local` keeps the record's and releases leave it, `propose` keeps it and proposes it
    back to Git. Any conflict on the field is resolved by the decision."""
    from app.ledger import service as ledger_service
    from app.ledger.engine import now
    if decision not in DECISIONS:
        raise CatalogueProblem(f"a field is one of: {', '.join(DECISIONS)}")
    e = db.scalar(select(CatalogueEntry).where(CatalogueEntry.workspace_id == workspace_id,
                                               CatalogueEntry.catalogue_id == catalogue_id).with_for_update())
    if e is None:
        raise LookupError(f"no catalogue entry {catalogue_id}")
    if field not in (e.stated or {}):
        raise CatalogueProblem(f"{catalogue_id}: the collection states no {field}")
    record = db.get(Asset, e.record_uid)
    managed, conflicts, corrections = set(e.managed_fields or []), dict(e.conflicts or {}), dict(e.corrections or {})
    conflicts.pop(field, None)
    cur = _current(record, field)
    if decision == "managed":
        managed.add(field)
        corrections.pop(field, None)
        if not _same(cur, e.stated[field]):
            ledger_service.edit_values(db, workspace_id, actor, record.uid, _changes(db, {field: e.stated[field]}),
                                       reason=reason or f"catalogue {e.collection_id} {e.collection_version}")
    elif decision == "local":
        managed.discard(field)
        corrections.pop(field, None)
    else:
        managed.discard(field)
        corrections[field] = {"value": cur, "by": actor, "release": e.stated[field], "at": now().isoformat(),
                              "reason": reason}
    e.managed_fields, e.conflicts, e.corrections = sorted(managed), conflicts, corrections
    db.flush()
    return e


def review_queue(db: Session, workspace_id: str) -> list[dict]:
    """The entries waiting for a person: conflicts from a release, values edited here on a managed field, and
    corrections proposed back."""
    out = []
    for e in sorted(entries(db, workspace_id).values(), key=lambda x: x.catalogue_id):
        record = db.get(Asset, e.record_uid)
        edited = [f for f in (e.managed_fields or []) if f in (e.stated or {}) and record is not None
                  and not _same(_current(record, f), e.stated[f])]
        if e.conflicts or e.corrections or edited:
            out.append({"catalogue_id": e.catalogue_id, "record_uid": e.record_uid,
                        "name": record.name if record else None, "collection_id": e.collection_id,
                        "conflicts": e.conflicts, "corrections": e.corrections, "edited": edited})
    return out


def readable_workspaces(db: Session, user) -> set[str]:
    from app.services.permissions import resolve_permission
    ids = list(db.scalars(select(Workspace.id)))
    if getattr(user, "is_admin", False):
        return set(ids)
    return {w for w in ids if resolve_permission(db, user, w, "read", "objects")}
