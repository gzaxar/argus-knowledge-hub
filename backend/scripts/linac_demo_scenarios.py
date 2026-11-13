"""Three troubleshooting stories in the Valmora linac demo bundle, and two corrections that make its failure model
answer: IOCs hosted on their server (not "deployed on", which means the beamline served), and the gauges read by a
gauge controller module of the vacuum rack (the rack also powers the ion pumps, so "readings frozen, pumps fine"
must point at the module). Run with the bundle root as argument; idempotent."""
import hashlib
import json
import sys
import uuid
from pathlib import Path

root = Path(sys.argv[1])
WS = "valmora-linac-demo"
T = WS + ":argus-object:"
DT = WS + ":argus-document:"
TT = WS + ":argus-ticket:"
KW = ["synthetic-demo"]
PLAN = "9725cd2b-a190-4a3c-a088-14c6482c1642"          # Accelerator Building — ground floor
LEVEL = "5f98a35d-8294-40cf-a227-01d615768821"


def path(name):
    return root / "records" / f"{name}.jsonl"


def rows(name):
    return [json.loads(l) for l in path(name).read_text().splitlines() if l.strip()]


def dump(name, items):
    path(name).write_text("".join(json.dumps(r, ensure_ascii=False, separators=(", ", ": "), sort_keys=True) + "\n"
                                  for r in items))


def _ident(r, key):
    if key == "uid":
        return r.get("uid")
    return tuple(r.get(k) for k in key)


def append(name, new, key="uid"):
    have = rows(name)
    ids = {_ident(r, key) for r in have}
    new = [r for r in new if _ident(r, key) is None or _ident(r, key) not in ids]
    if any("$row" in r for r in have):
        nxt = max(r["$row"] for r in have) + 1
        for r in new:
            r["$row"] = nxt
            nxt += 1
    dump(name, have + new)
    return len(new)


C = "2026-03-02T09:00:00+00:00"


def asset(uid, key, name, typ, slug, **attrs):
    return {"attributes": {"argus_keywords": KW, **attrs}, "avatar_icon_uid": None, "created_at": C,
            "deleted_at": None, "inbound_relations": [], "is_global": False, "key": key, "merged_into_uid": None,
            "name": name, "outbound_relations": [], "record_status": "Active", "schema_uid": T + slug, "type": typ,
            "uid": uid, "updated_at": C, "workspace_id": WS}


ASSETS = [
    asset("vl-moxa-01", "VL-MOXA-01", "Moxa NPort 5650-8 (magnet power supply serial lines)", "Serial Converter",
          "serial-converter", argus_location="vl-room-service", hostname="moxa-mag", ip="10.20.3.41",
          manufacturer="Moxa", model="NPort 5650-8", serial="SYN-MOXA-01", firmware_version="3.11",
          n_serial_ports=8, serial_modes=["RS-232", "RS-422", "RS-485"], tcp_port_base=4001,
          inventory_number="VL-INV-MOXA-01", condition="good"),
    asset("vl-moxa-01-p3", "VL-MOXA-01-P3", "Moxa NPort 5650-8 · serial port 3 (TCP 4003)", "Equipment Port",
          "equipment-port", port_label="P3", port_kind="rs_485_2w", baud=9600, framing="8N1", tcp_port=4003,
          port_role="Quadrupole supplies PS-Q1, PS-Q2, PS-Q3 (Modbus addresses 1, 2, 3)"),
    asset("vl-moxa-01-p4", "VL-MOXA-01-P4", "Moxa NPort 5650-8 · serial port 4 (TCP 4004)", "Equipment Port",
          "equipment-port", port_label="P4", port_kind="rs_232", baud=19200, framing="8N1", tcp_port=4004,
          port_role="Spectrometer dipole supply PS-DM1"),
    asset("vl-moxa-spare", "VL-MOXA-SPARE", "Spare Moxa NPort 5650-8", "Serial Converter", "serial-converter",
          argus_location="vl-room-service", manufacturer="Moxa", model="NPort 5650-8", serial="SYN-MOXA-SP1",
          firmware_version="3.11", is_designated_spare=True, argus_lifecycle="standby",
          note="Factory settings: load the saved configuration of VL-MOXA-01 before use."),
    asset("vl-vac-ctl-gm", "VL-VAC-CTL-GM", "Gauge controller module GM-1 (vacuum controller rack)",
          "Vacuum Controller", "vacuum-controller", argus_location="vl-room-service", manufacturer="Synthetica Vac",
          model="TGC-3", serial="SYN-VAC-GM1", firmware_version="2.3", n_channels=3,
          note="Reads the three cold-cathode gauges of the bunker and gives the interlock PLC its setpoint relays."),
    asset("vl-sp-thy-01", "VL-SP-THY-01", "Spare thyratron for the modulators", "Spare Part", "spare-part",
          argus_location="vl-room-gallery", is_designated_spare=True, argus_lifecycle="standby",
          note="One spare for M-1, M-2 and M-3; reservoir set to the factory value."),
]

R = C


def rel(a, verb, b, derivation=None, rule=None):
    return {"created_at": R, "derivation": derivation, "from_asset_uid": a, "relation_type": verb, "rule": rule,
            "to_asset_uid": b, "workspace_id": WS}


NEW_RELATIONS = [
    rel("vl-moxa-01-p3", "port of", "vl-moxa-01"),
    rel("vl-moxa-01-p4", "port of", "vl-moxa-01"),
    rel("vl-ps-q1", "reached through", "vl-moxa-01-p3"),
    rel("vl-ps-q2", "reached through", "vl-moxa-01-p3"),
    rel("vl-ps-q3", "reached through", "vl-moxa-01-p3"),
    rel("vl-ps-dip", "reached through", "vl-moxa-01-p4"),
    rel("vl-ioc-mag", "connects to", "vl-moxa-01"),
    rel("vl-moxa-01", "located in", "vl-room-service", "derived", "located-in/1"),
    rel("vl-moxa-spare", "located in", "vl-room-service", "derived", "located-in/1"),
    rel("vl-vac-ctl-gm", "part of", "vl-vac-ctl"),
    rel("vl-vac-ctl-gm", "located in", "vl-room-service", "derived", "located-in/1"),
    rel("vl-ioc-vac", "controls", "vl-vac-ctl-gm"),
    rel("vl-sp-thy-01", "located in", "vl-room-gallery", "derived", "located-in/1"),
]


def fix_relations():
    """IOCs are hosted on their server; the gauges are read by the gauge module."""
    out, changed = [], 0
    for r in rows("relations"):
        if r["relation_type"] == "deployed on" and r["to_asset_uid"] == "vl-srv-ioc":
            r["relation_type"] = "hosted on"
            changed += 1
        if r["relation_type"] == "reads" and r["from_asset_uid"] == "vl-vac-ctl":
            r["from_asset_uid"] = "vl-vac-ctl-gm"
            changed += 1
        out.append(r)
    dump("relations", out)
    return changed


def ticket(uid, kind, state, prio, title, desc, asset_uid, created, assignee, by, closed=None, attrs=None):
    return {"asset_uid": asset_uid, "assignee": assignee, "attributes": attrs or {}, "closed_at": closed,
            "created_at": created, "created_by": by, "deleted_at": None, "description": desc, "due_date": None,
            "field_versions": None, "labels": KW, "priority": prio, "schema_uid": TT + kind, "state": state,
            "title": title, "uid": uid, "updated_at": closed or created, "version": 1, "workspace_id": WS}


TICKETS = [
    ticket("vl-t-014", "incident", "closed", "high", "PS-Q2 readback frozen in the control room",
           "After the Moxa firmware update of 8 September the readback of PS-Q2 stayed constant in the control room "
           "and new setpoints were not applied (synthetic).",
           "vl-ps-q2", "2026-09-08T10:15:00+00:00", "vl-u-noor", "vl-u-elena", "2026-09-08T15:40:00+00:00",
           {"argus_root_cause": "The firmware update reset serial port 3 of VL-MOXA-01 to RS-232; the RS-485 "
                                "supplies answered intermittently.",
            "argus_corrective_action": "Set port 3 back to RS-485 2-wire, 9600 8N1, and saved the configuration; added "
                                       "the check to the serial line runbook."}),
    ticket("vl-t-015", "incident", "new", "high", "Quadrupoles Q1–Q3: no readback, setpoints not applied",
           "Since the start of the shift the control room shows no readback from the quadrupole supplies Q1, Q2 and "
           "Q3, and setpoints sent to them have no effect. The beam is still on (synthetic).",
           "vl-ps-q1", "2026-11-12T07:05:00+00:00", None, "vl-u-elena"),
    ticket("vl-t-016", "incident", "closed", "high", "M-2 HV overcurrent trips during conditioning",
           "Modulator M-2 tripped on HV overcurrent four times in two hours while conditioning ACC02 (synthetic).",
           "vl-mod-2", "2026-08-21T22:10:00+00:00", "vl-u-jonas", "vl-u-noor", "2026-08-23T11:00:00+00:00",
           {"argus_root_cause": "Thyratron reservoir voltage had drifted low; the tube fired late under load.",
            "argus_corrective_action": "Reservoir set back to the factory value by Synthetica RF under contract "
                                       "VL-C-2025-001; trips stopped. Replace the thyratron if it drifts again.",
            "argus_downtime_minutes": 290}),
    ticket("vl-t-017", "incident", "new", "high", "Bunker vacuum readings frozen, sector valves closed",
           "Since 06:00 the three bunker gauges show the same value and the vacuum PLC has closed sector valves VV-1 "
           "and VV-2. The beam is off (synthetic).",
           "vl-vg-1", "2026-11-12T06:20:00+00:00", None, "vl-u-luca"),
    ticket("vl-t-018", "incident", "closed", "medium", "Gauge readings frozen after controller firmware update",
           "After the gauge module was updated to firmware 2.3 the readings stopped changing after a few hours "
           "(synthetic).",
           "vl-vac-ctl-gm", "2026-07-02T09:00:00+00:00", "vl-u-luca", "vl-u-luca", "2026-07-02T11:30:00+00:00",
           {"argus_root_cause": "Firmware 2.3 of the gauge module hangs its acquisition loop after a serial timeout "
                                "from the IOC; the outputs freeze at the last value.",
            "argus_corrective_action": "Power-cycled the gauge module (rear switch); vendor fix expected in 2.4."}),
]


def comment(uid, issue, author, at, body):
    return {"author": author, "body": body, "created_at": at, "issue_uid": issue, "uid": uid, "updated_at": at}


COMMENTS = [
    comment("vl-t-014-c1", "vl-t-014", "vl-u-noor", "2026-09-08T15:30:00+00:00",
            "Moxa web console: port 3 showed RS-232 after the update. Set RS-485 2-wire, saved, readback is back."),
    comment("vl-t-015-c1", "vl-t-015", "vl-u-elena", "2026-11-12T07:20:00+00:00",
            "Q4, Q5, Q6 and the dipole DM1 read back fine from the same IOC; only Q1–Q3 are dead."),
    comment("vl-t-003-c2", "vl-t-003", "vl-u-jonas", "2026-11-12T08:10:00+00:00",
            "Local panel: HV overcurrent, two trips after the restart. Not reset a third time, as the runbook says; "
            "Synthetica RF called."),
    comment("vl-t-016-c1", "vl-t-016", "vl-u-jonas", "2026-08-23T10:50:00+00:00",
            "Reservoir found at 5.6 V instead of 6.3 V. Reset by the vendor; four hours of conditioning without trips."),
    comment("vl-t-017-c1", "vl-t-017", "vl-u-luca", "2026-11-12T06:45:00+00:00",
            "Ion pump currents IP-1 to IP-5 are normal and steady in the archiver. The gauges have not moved since "
            "05:58."),
    comment("vl-t-018-c1", "vl-t-018", "vl-u-luca", "2026-07-02T11:20:00+00:00",
            "Front panel of GM-1 frozen too. Rear power switch off and on: readings back within a minute."),
]


def hist(uid, issue, author, at, typ, frm=None, to=None, details=None):
    return {"author": author, "backend_id": None, "details": details, "field": "state" if typ == "transition" else None,
            "from_value": frm, "issue_uid": issue, "timestamp": at, "to_value": to, "type": typ, "uid": uid}


HISTORY = []
for t in TICKETS:
    HISTORY.append(hist(t["uid"] + "-h0", t["uid"], t["created_by"], t["created_at"], "created",
                        details="Created (synthetic demo ticket)"))
    if t["closed_at"]:
        HISTORY.append(hist(t["uid"] + "-h1", t["uid"], t["assignee"], t["closed_at"], "transition", "new",
                            t["state"]))

NOTE = "> **Synthetic demo content.** The Valmora linac, its people, suppliers and figures are fictional.\n\n\n"
SERIAL = NOTE + """# Magnet power supply serial lines

The quadrupole supplies [PS-Q1](/assets/vl-ps-q1), [PS-Q2](/assets/vl-ps-q2) and [PS-Q3](/assets/vl-ps-q3) share one
RS-485 2-wire line on serial port 3 of the Moxa NPort [VL-MOXA-01](/assets/vl-moxa-01) (10.20.3.41, TCP port 4003),
at Modbus addresses 1, 2 and 3. The spectrometer dipole supply [PS-DM1](/assets/vl-ps-dip) has its own RS-232 line on
port 4 (TCP 4004). PS-Q4 to PS-Q6 and PS-SOL1 are on the controls Ethernet directly.

The IOC [IOC magnets-ps](/assets/vl-ioc-mag) on [SRV-IOC](/assets/vl-srv-ioc) opens the TCP ports of the Moxa.

A fault on the Moxa or on port 3 silences Q1, Q2 and Q3 together; one supply alone silent points at that supply or
its drop. How the line is cabled between the supplies — cable labels, routing and the order of the drops — is not
recorded in ARGUS yet: the cable database has not been imported.
"""
RB_SERIAL = NOTE + """# Magnet power supply serial line: checks

Use when several supplies on the Moxa stop reading back at once.

1. **Which supplies?** Q1–Q3 together: the Moxa or port 3 (go on). One supply: that supply, its address, its drop.
   The supplies keep their last current when the line is lost: the beam is not lost, but it cannot be corrected.
2. `ping 10.20.3.41` from SRV-IOC. No answer: power and network of the Moxa in the service area.
3. **Moxa web console, port 3**: RS-485 2-wire, 9600 8N1. A firmware update has reset it to RS-232 before
   (September): set it back and **save**.
4. `telnet 10.20.3.41 4003` from SRV-IOC must connect; then restart IOC magnets-ps and check the readbacks.
5. A dead Moxa: the spare [VL-MOXA-SPARE](/assets/vl-moxa-spare) is in the service area; load the saved configuration
   of VL-MOXA-01 first (same IP, same port modes).
"""
RB_VAC = NOTE + """# Frozen vacuum readings: checks

Use when the bunker gauges stop changing, especially if the vacuum PLC has closed the sector valves.

1. **Is the vacuum bad, or only its reading?** Look at the ion pump currents (IP-1 to IP-5, in the archiver): they
   are an independent measure of pressure. Normal and steady currents: the vacuum is fine and the gauge readout
   has failed.
2. **Do not open the sector valves** until a gauge reading is trusted again: the interlock closed them because it
   lost its setpoint relays, which is the safe side.
3. **Gauge controller module GM-1** in the vacuum controller rack (service area): a frozen front panel means its
   acquisition has hung — firmware 2.3 is known to do it after a serial timeout from the IOC. Power-cycle it with the
   rear switch; the ion pumps are powered by the rack, not by the module, and keep running.
4. Readings back and plausible: reset the interlock from the PLC, then open VV-1 and VV-2.
5. Record what you found on the ticket.
"""
RB_MOD = NOTE + """# Modulator fault trip: first response

1. Read the **fault code on the local panel** of the modulator before resetting anything.
2. **HV overcurrent**: reset at most twice. A third trip means the thyratron or the PFN: do not insist, call
   Synthetica RF (contract VL-C-2025-001, 24 hours a day during runs).
3. Check the personnel safety interlock state (it acts on the modulators): a PSS trip is not a modulator fault.
4. A drifting thyratron reservoir caused the trips of August; a spare thyratron is in the klystron gallery.
5. While a modulator is off, its klystron's structures get no RF: the beam after them is lost or degraded — tell the
   control room which energy is still reachable.
"""


def doc(uid, code, title, typ, created, summary, body, applies, owner="vl-u-noor"):
    d = {"authority_level": "informativo", "code": code, "confidentiality": "interno", "created_at": created,
         "current_revision_uid": uid + "-r1", "document_type_uid": DT + typ, "is_global": False,
         "owner_user_id": owner, "responsible_service_asset_uid": None, "retention_class": "5y",
         "retired_at": None, "source": "manual", "superseded_by_uid": None, "title": title, "uid": uid,
         "updated_at": created, "workspace_id": WS}
    r = {"approved_at": created, "approved_by": "vl-u-elena", "attributes": {"argus_summary": summary},
         "authored_by": owner, "body_markdown": body, "created_at": created, "document_uid": uid,
         "next_review_due": None, "published_at": created, "review_comment": None, "revision_number": 1,
         "state": "published", "steps": [], "submitted_at": None, "superseded_by_uid": None, "uid": uid + "-r1",
         "updated_at": created, "valid_from": None, "valid_until": None}
    rels = [{"created_at": created, "from_document_uid": uid, "relation_type": "describes", "to_type": "asset",
             "to_uid": a, "workspace_id": WS} for a in applies]
    return d, r, rels


DOCS = [
    doc("vl-doc-serial-lines", "VL-NT-003", "Magnet power supply serial lines", "note", "2026-03-05T00:00:00+00:00",
        "Which supplies share which Moxa port; cabling not recorded (synthetic).", SERIAL,
        ["vl-moxa-01", "vl-moxa-01-p3", "vl-moxa-01-p4", "vl-ps-q1", "vl-ps-q2", "vl-ps-q3", "vl-ps-dip"]),
    doc("vl-doc-rb-serial", "VL-RB-001", "Magnet power supply serial line: checks", "runbook",
        "2026-09-09T00:00:00+00:00", "What to check when several supplies on the Moxa go quiet (synthetic).",
        RB_SERIAL, ["vl-moxa-01", "vl-moxa-01-p3", "vl-ioc-mag"]),
    doc("vl-doc-rb-vac", "VL-RB-002", "Frozen vacuum readings: checks", "runbook", "2026-07-03T00:00:00+00:00",
        "Telling bad vacuum from a frozen gauge readout, and recovering it safely (synthetic).", RB_VAC,
        ["vl-vac-ctl-gm", "vl-vac-ctl", "vl-plc-vac", "vl-vg-1", "vl-vg-2", "vl-vg-3"], owner="vl-u-luca"),
    doc("vl-doc-rb-mod", "VL-RB-003", "Modulator fault trip: first response", "runbook",
        "2026-08-24T00:00:00+00:00", "What to do, and not do, when a modulator trips (synthetic).", RB_MOD,
        ["vl-mod-1", "vl-mod-2", "vl-mod-3", "vl-sp-thy-01"], owner="vl-u-jonas"),
]


def placement(asset_uid, place, x, y, note=None):
    return {"asset_uid": asset_uid, "confirmed_by": "demo-author", "created_at": C, "level_uid": LEVEL, "note": note,
            "place_uid": place, "plan_uid": PLAN, "plan_x": x, "plan_y": y, "source": "manual", "state": "confirmed",
            "uid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"valmora/{asset_uid}/placement")), "valid_from": C,
            "valid_until": None, "workspace_id": WS}


PLACEMENTS = [
    placement("vl-moxa-01", "vl-room-service", 615.0, 188.0),
    placement("vl-vac-ctl-gm", "vl-room-service", 646.0, 192.0),
    placement("vl-moxa-spare", "vl-room-service", 668.0, 232.0, "spares cabinet"),
    placement("vl-sp-thy-01", "vl-room-gallery", 365.0, 120.0, "spares shelf"),
]

TOUR = [
    {"link": "/tickets/vl-t-015", "title": "Quadrupoles go quiet",
     "text": "Three quadrupole supplies stop reading back while three others on the same IOC are fine: Ask ARGUS "
             "finds what only the three share — the Moxa and its port 4003 — the September firmware reset, the "
             "runbook and the spare."},
    {"link": "/tickets/vl-t-017", "title": "Frozen vacuum readings",
     "text": "The bunker gauges freeze and the interlock closes the sector valves. The ion pumps say the vacuum is "
             "fine: the gauge module is the suspect, and the runbook says not to open the valves yet."},
    {"link": "/tickets/vl-t-003", "title": "A modulator trip",
     "text": "M-2 trips on HV overcurrent: what it takes down (klystron K-2, two structures, the beam after them), "
             "what happened in August, who to call under which contract, and where the spare thyratron is."},
]

counts = {"relations (fixed)": fix_relations()}
counts.update({
    "assets": append("assets", ASSETS),
    "relations": append("relations", NEW_RELATIONS, key=("from_asset_uid", "relation_type", "to_asset_uid")),
    "tickets": append("tickets", TICKETS),
    "ticket_comments": append("ticket_comments", COMMENTS),
    "ticket_history": append("ticket_history", HISTORY),
    "documents": append("documents", [d for d, _, _ in DOCS]),
    "document_revisions": append("document_revisions", [r for _, r, _ in DOCS]),
    "document_relations": append("document_relations", [x for _, _, rs in DOCS for x in rs],
                                 key=("from_document_uid", "relation_type", "to_uid")),
    "indoor_placements": append("indoor_placements", PLACEMENTS),
})

mp = root / "manifest.json"
m = json.loads(mp.read_text())
for fam, meta in m["families"].items():
    p = root / meta["file"]
    if p.exists():
        data = p.read_bytes()
        meta["sha256"], meta["rows"] = hashlib.sha256(data).hexdigest(), sum(1 for l in data.splitlines() if l.strip())
for e in m["files"]:
    data = (root / e["path"]).read_bytes()
    e["sha256"], e["size"] = hashlib.sha256(data).hexdigest(), len(data)
steps = m["demo"]["steps"]
links = {s["link"] for s in steps}
for s in TOUR:
    if s["link"] in links:
        for x in steps:
            if x["link"] == s["link"]:
                x.update(s)
    else:
        steps.insert(len(steps) - 2, s)
mp.write_text(json.dumps(m, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
print(counts)
