"""The data invariants as a report (asset-model-revision §8.3, §8.6, §9.2,
§9.3, and identifier uniqueness; the legacy migration's I-MIG-4).

The ledger enforces these when a decision is made. The report checks the
state as it is, whatever wrote it: the legacy importer, a migration, or
someone working around the ledger. Nothing is changed; the ticket
derivation (I-TKT-3) is recomputed inside a savepoint and rolled back.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger import connectivity, engine, temporal
from app.ledger.engine import ACCESS_POINT, INSTALLABLE, INSTALLATION
from app.models.asset import Asset, Relation
from app.models.asset_subresources import AssetLabel
from app.models.issue import Issue
from app.models.ledger import Claim, Conflict, IdentityBinding, LedgerStream, TicketLink

EXAMPLES = 10
NOT_UNITS = INSTALLABLE | {INSTALLATION, ACCESS_POINT, "Control Device", "IOC", "Location", "Facility", "Section",
                           "Area", "Machine Module", "Product Model", "Work Package", "Equipment Port"}
CHECKED_ELSEWHERE = {
    "I-INS-7": "Proposed Installations may overlap anything; I-INS-1 and I-INS-2 check only Confirmed ones",
    "I-PORT-4": "an attached edge exists only where the port matching holds, which I-PORT-1 checks",
}


def _live(a: Asset) -> bool:
    return a.record_status != "Retired" and a.merged_into_uid is None and a.deleted_at is None


def report(db: Session, workspace_ids: Iterable[str]) -> dict:
    ws = sorted(set(workspace_ids))
    found: dict[str, list] = defaultdict(list)

    def bad(code: str, message: str, **detail):
        found[code].append({"message": message, **detail})

    records = list(db.scalars(select(Asset).where(Asset.workspace_id.in_(ws))))
    by_type = defaultdict(list)
    for a in records:
        by_type[a.type].append(a)

    # ---------------------------------------------------------------- Installations (§8.3)
    views = [engine.installation_view(db, i) for i in by_type[INSTALLATION]]
    confirmed = [v for v in views if v["status"] == "Confirmed" and v["record_status"] != "Retired"]
    for key, code in (("asset_uid", "I-INS-1"), ("position_uid", "I-INS-2")):
        groups = defaultdict(list)
        for v in confirmed:
            if v[key]:
                groups[v[key]].append(v)
        for group in groups.values():
            for i, a in enumerate(group):
                for b in group[i + 1:]:
                    kind = temporal.overlap(a["interval"], b["interval"])
                    if kind == "definite":
                        bad(code, f"{a['key']} and {b['key']} overlap", installations=[a["uid"], b["uid"]])
                    elif kind == "possible":
                        opened = db.scalar(select(Conflict.conflict_id).where(
                            Conflict.conflict_type == "possible_overlap",
                            Conflict.subject_uid.in_([a["uid"], b["uid"]])).limit(1))
                        if opened is None:
                            bad("I-INS-6", f"{a['key']} and {b['key']} possibly overlap with no review item",
                                installations=[a["uid"], b["uid"]])
    for v in confirmed:
        try:
            temporal.validate(v["interval"])
        except temporal.TemporalError as exc:
            bad("I-INS-3", f"{v['key']}: {exc}", installation=v["uid"])
    for v in views:
        if v["record_status"] == "Retired":
            continue
        pos = db.get(Asset, v["position_uid"]) if v["position_uid"] else None
        unit = db.get(Asset, v["asset_uid"]) if v["asset_uid"] else None
        if pos is None or pos.type not in INSTALLABLE:
            bad("I-INS-4", f"{v['key']} is not installed at an installable position", installation=v["uid"])
        if unit is None or unit.type in NOT_UNITS:
            bad("I-INS-4", f"{v['key']} is not an installation of Equipment", installation=v["uid"])
        if pos is not None and pos.workspace_id != v["workspace_id"]:
            bad("I-INS-5", f"{v['key']} is not in its position's workspace", installation=v["uid"])

    # ---------------------------------------------------------------- Access Points (§9.2)
    aps = by_type[ACCESS_POINT]
    by_address = defaultdict(list)
    for ap in aps:
        address = (ap.attributes or {}).get("address")
        if address:
            by_address[(ap.workspace_id, address)].append(connectivity.access_point_view(db, ap))
    for (w, address), group in by_address.items():
        if sum(1 for v in group if v["record_status"] == "Active") > 1:
            bad("I-AP-1", f"more than one Active Access Point for {address} in {w}", address=address)
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if temporal.overlap(a["interval"], b["interval"]) == "definite":
                    bad("I-AP-3", f"{a['key']} and {b['key']} served {address} at the same time", address=address)
    for ap in aps:
        edges = list(db.scalars(select(Relation).where(Relation.from_asset_uid == ap.uid)))
        assigned = [r for r in edges if r.relation_type == "assigned to"]
        if len(assigned) > 1:
            bad("I-AP-2", f"{ap.key} is assigned more than once", access_point=ap.uid)
        if assigned and any(r.relation_type == "implemented by" and r.derivation == "ledger" for r in edges):
            bad("I-AP-4", f"{ap.key} is assigned and still has an asserted `implemented by`", access_point=ap.uid)
        refs = [b.source_ref for b in db.scalars(select(IdentityBinding).where(IdentityBinding.uid == ap.uid))]
        streams = {c.stream_id for c in db.scalars(select(Claim).where(Claim.source_ref.in_(refs)))} if refs else set()
        owners = {s.workspace_id for s in db.scalars(select(LedgerStream).where(LedgerStream.id.in_(streams),
                                                                               LedgerStream.kind == "epik8s"))}
        if owners and ap.workspace_id not in owners:
            bad("I-AP-5", f"{ap.key} is not in the workspace whose configuration names it", access_point=ap.uid)

    # ---------------------------------------------------------------- ports (§9.3)
    for seg in [a for a in by_type[connectivity.BUS_SEGMENT] if a.record_status != "Retired"]:
        m = connectivity.match_segment(db, seg)
        attached = [r.to_asset_uid for r in db.scalars(select(Relation).where(
            Relation.from_asset_uid == seg.uid, Relation.relation_type == "attached to",
            Relation.derivation == "derived"))]
        should = [m["port_uid"]] if m["status"] == "attached" else []
        if sorted(attached) != sorted(should):
            bad("I-PORT-1", f"{seg.key}: attached to {attached or 'nothing'}, the matching says {should or 'nothing'}",
                segment=seg.uid)
        port_map = (seg.attributes or {}).get("port_map")
        if isinstance(port_map, dict) and port_map.get("installation_uid"):
            inst = db.get(Asset, port_map["installation_uid"])
            unit = engine.installation_view(db, inst)["asset_uid"] if inst is not None else None
            port = db.get(Asset, port_map.get("port_uid")) if port_map.get("port_uid") else None
            owner = connectivity.edge_target(db, port.uid, "port of") if port is not None else None
            if unit is None or owner != unit:
                bad("I-PORT-2", f"{seg.key}: its confirmed port map is not a port of that Installation's unit",
                    segment=seg.uid)
        ctype = connectivity._STATUS_CONFLICT.get(m["status"])
        if ctype and db.scalar(select(Conflict.conflict_id).where(Conflict.subject_uid == seg.uid,
                                                                  Conflict.conflict_type == ctype).limit(1)) is None:
            bad("I-PORT-3", f"{seg.key}: {m['status']} with no open review item", segment=seg.uid)

    # ---------------------------------------------------------------- tickets (§8.6)
    issues = list(db.scalars(select(Issue).where(Issue.workspace_id.in_(ws), Issue.deleted_at.is_(None),
                                                 Issue.asset_uid.isnot(None))))
    for issue in issues:
        subjects = db.scalars(select(TicketLink).where(TicketLink.ticket_uid == issue.uid,
                                                       TicketLink.role == "subject")).all()
        if len(subjects) != 1:
            bad("I-TKT-1", f"ticket {issue.uid} has {len(subjects)} subject links", ticket=issue.uid)
    for link in db.scalars(select(TicketLink).where(TicketLink.workspace_id.in_(ws),
                                                    TicketLink.origin == "migration-split")):
        if link.certainty != "possible":
            bad("I-TKT-2", "a migration-split link is counted as definite", ticket=link.ticket_uid)
    counted = defaultdict(int)
    for link in db.scalars(select(TicketLink).where(TicketLink.workspace_id.in_(ws))):
        if link.role == "subject" or (link.certainty == "definite" and link.origin == "derived"):
            counted[(link.ticket_uid, link.asset_uid)] += 1
    for (ticket, asset), n in counted.items():
        if n > 1:
            bad("I-TKT-2", f"ticket {ticket} is counted {n} times on one record", ticket=ticket)
    from app.ledger import tickets
    # I-TKT-3 is about derived links: subject and related links are what the ticket says.
    key = lambda l: (l.ticket_uid, l.asset_uid, l.role, l.certainty, l.origin)
    uids = [i.uid for i in issues]
    derived_q = select(TicketLink).where(TicketLink.ticket_uid.in_(uids), TicketLink.origin != "ticket")
    now_links = sorted(key(l) for l in db.scalars(derived_q))
    # Planned, not written: the report also runs in an export's read-only snapshot, where a savepoint that
    # rewrote the links and rolled back failed ("cannot execute DELETE in a read-only transaction").
    derived = sorted(key(l) for issue in issues for l in tickets.plan_links(db, issue)[0] if l.origin != "ticket")
    if now_links != derived:
        missing, extra = set(derived) - set(now_links), set(now_links) - set(derived)
        bad("I-TKT-3", f"{len(missing)} derivable link(s) missing, {len(extra)} link(s) no derivation supports",
            missing=[list(x) for x in sorted(missing)[:EXAMPLES]], extra=[list(x) for x in sorted(extra)[:EXAMPLES]])

    # ---------------------------------------------------------------- identifiers
    holders = defaultdict(set)
    live = {a.uid: a for a in records if _live(a) and a.type not in (INSTALLATION, ACCESS_POINT)}
    for a in live.values():
        attrs = a.attributes or {}
        if attrs.get("serial"):
            holders[("serial", str(attrs["serial"]), (attrs.get("manufacturer") or "").lower())].add(a.uid)
        if attrs.get("inventory_number"):
            holders[("inventory_number", str(attrs["inventory_number"]), "")].add(a.uid)
    for label in db.scalars(select(AssetLabel).where(AssetLabel.asset_uid.in_(list(live)),
                                                     AssetLabel.type.in_(("jiraObjectId", "qrcode")),
                                                     AssetLabel.verified.is_(True))):
        holders[(label.type, label.value, "")].add(label.asset_uid)
    for (field, value, maker), uids_ in holders.items():
        if len(uids_) > 1:
            bad("uniqueness", f"{field} {value}{' (' + maker + ')' if maker else ''} is held by {len(uids_)} records",
                records=sorted(uids_))

    codes = ["I-INS-1", "I-INS-2", "I-INS-3", "I-INS-4", "I-INS-5", "I-INS-6", "I-INS-7", "I-AP-1", "I-AP-2",
             "I-AP-3", "I-AP-4", "I-AP-5", "I-PORT-1", "I-PORT-2", "I-PORT-3", "I-PORT-4", "I-TKT-1", "I-TKT-2",
             "I-TKT-3", "uniqueness"]
    out = {c: {"ok": not found[c], "count": len(found[c]), "examples": found[c][:EXAMPLES],
               **({"note": CHECKED_ELSEWHERE[c]} if c in CHECKED_ELSEWHERE else {})} for c in codes}
    return {"workspaces": ws, "ok": all(v["ok"] for v in out.values()),
            "failing": [c for c in codes if not out[c]["ok"]], "invariants": out}
