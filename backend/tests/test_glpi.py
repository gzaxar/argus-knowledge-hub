"""GLPI in the IT package: discovery of what an installation is (GLPI 10 with the fields and genericobject
plugins, GLPI 11 with asset definitions), its schema proposed and applied only once reviewed, entity
scoping, the import through the ledger (idempotent, local edits kept by the authority policy, nothing
retired without a decision), tickets and documents, and the live client against GLPI's REST API shape."""
import base64
import copy
import json
import secrets
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.integrations.glpi import discovery, importer, mapping, schema, source
from app.ledger import service
from app.models.asset import Asset, Relation
from app.models.attachment import Attachment
from app.models.asset_subresources import AssetTicket
from app.models.issue import Issue
from app.models.ledger import Conflict
from app.models.schema import Schema
from app.models.user import User
from app.models.workspace import Workspace
from app.packages import install as installer

FIXTURES = Path(__file__).parent / "fixtures" / "glpi"


def snap(name: str) -> dict:
    return source.load_fixture(FIXTURES / f"{name}.json")


@pytest.fixture()
def it_ws():
    made = []

    def make(packages=("it",)):
        w = f"glpi-{secrets.token_hex(3)}"
        db = SessionLocal()
        db.add(Workspace(id=w, name=w))
        db.flush()
        installer.install(db, w, list(packages))
        db.commit()
        db.close()
        made.append(w)
        return w
    yield make
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    for w in made:
        for c in db.scalars(select(Conflict).where(Conflict.workspace_id == w)):
            db.delete(c)
        row = db.get(Workspace, w)
        if row is not None:
            db.delete(row)
    db.commit()
    db.close()


def settings(ws: str, s: dict, **extra) -> importer.Settings:
    """A configuration sending entity 1 (LNF, with Lab IT under it) and the root's shared items to `ws`;
    the other site stays outside the map. Keys get a prefix of their own per test."""
    params = {"base_url": s["instance"], "key_prefix": f"G{secrets.token_hex(2).upper()}",
              "entity_map": [{"entity_id": 1, "recursive": True, "workspace_id": ws},
                             {"entity_id": 0, "recursive": False, "workspace_id": ws}], **extra}
    return importer.Settings.of(params, ws)


def by_ref(db, ref: str):
    from app.models.ledger import IdentityBinding
    b = db.get(IdentityBinding, ref)
    return db.get(Asset, b.uid) if b else None


def unique_instance(s: dict) -> dict:
    """Each test its own GLPI (the ledger's identities are installation-wide)."""
    s = copy.deepcopy(s)
    s["instance"] = f"https://glpi-{secrets.token_hex(3)}.example.org"
    return s


# --------------------------------------------------------------------------- discovery

def test_discovery_records_what_each_version_exposes():
    d10, d11 = discovery.discover(snap("glpi10")), discovery.discover(snap("glpi11"))
    assert (d10["version"], d10["major"], d11["version"], d11["major"]) == ("10.0.16", 10, "11.0.1", 11)
    assert d10["capabilities"]["plugin_fields"] and d10["capabilities"]["genericobject"]
    assert not d10["capabilities"]["custom_assets"] and d11["capabilities"]["custom_assets"]
    assert d11["capabilities"]["high_level_api"] == "v2" and d10["capabilities"]["high_level_api"] is None
    assert d10["itemtypes"]["Computer"] == {"count": 5, "status": "mapped", "maps_to": "Computing Node"}
    assert d10["itemtypes"]["Phone"]["status"] == "unavailable" and "ERROR_RIGHT_MISSING" in d10["itemtypes"]["Phone"]["why"]
    assert {e["completename"]: e["records"] for e in d10["entities"]}["Root entity > Other site"] == 2
    kinds = {f["system_name"]: f["kind"] for f in d11["custom_fields"]}
    assert kinds == {"calibration_due": "date", "accuracy": "float", "lab": "enumeration", "signature": None}
    plugin = {f["name"]: f["kind"] for f in d10["plugin_fields"]}
    assert plugin == {"budgetcodefield": "string", "criticalityfield": "enumeration", "relatedfield": None}


def test_the_default_entity_map_sends_the_top_entity_and_what_is_under_it():
    s = snap("glpi10")
    m = mapping.default_entity_map(s, "home")
    assert m == [{"entity_id": 0, "entity": "Root entity", "recursive": True, "workspace_id": "home"}]
    targets = mapping.entity_targets(s, [{"entity_id": 1, "recursive": True, "workspace_id": "a"},
                                         {"entity_id": 0, "recursive": False, "workspace_id": "b"}])
    assert targets == {"0": "b", "1": "a", "2": "a", "3": None}


# --------------------------------------------------------------------------- the schema

def test_glpi_11_custom_assets_are_proposed_reused_or_created_and_applied_only_once_approved(it_ws):
    ws = it_ws()
    s = unique_instance(snap("glpi11"))
    db = SessionLocal()
    proposal = schema.propose(db, ws, s)
    types = {t["system_name"]: t for t in proposal["types"]}
    assert (types["Rack"]["action"], types["Rack"]["argus_type"]) == ("reuse", "Rack"), "an ARGUS type of that name"
    lab = types["LabInstrument"]
    assert (lab["action"], lab["argus_type"], lab["parent"]) == ("create", "Lab instrument", "IT Equipment")
    fields = {f["source"]: f for f in lab["fields"]}
    assert fields["custom_lab"]["kind"] == "enumeration"
    assert [o["value"] for o in fields["custom_lab"]["options"]] == ["Optics lab", "RF lab"]
    assert fields["custom_signature"]["action"] == "unsupported"
    assert any(u["source"] == "custom_signature" for u in proposal["unsupported"])
    assert schema.status({}, s) == "awaiting review"

    # nothing is created by proposing, nor imported before approval
    assert db.scalar(select(Schema).where(Schema.workspace_id == ws, Schema.name == "Lab instrument")) is None
    st = settings(ws, s)
    report = importer.plan(db, st, s)
    assert {"itemtype": "Glpi\\CustomAsset\\LabInstrumentAsset", "records": 1} in report["awaiting_schema_review"]

    approved = schema.approve(db, ws, proposal, "tester")
    db.commit()
    made = db.scalar(select(Schema).where(Schema.workspace_id == ws, Schema.name == "Lab instrument"))
    assert {a["key"] for a in made.attributes} == {"glpi_calibration_due", "glpi_accuracy", "glpi_lab"}
    assert schema.status({"approved": approved}, s) == "approved"
    st = settings(ws, s, schema={"approved": approved})
    importer.run(db, st, s, "tester")
    db.commit()
    osc = by_ref(db, mapping.ref(st.instance, "Glpi\\CustomAsset\\LabInstrumentAsset", 1))
    assert osc.type == "Lab instrument" and osc.attributes["glpi_lab"] == "RF lab"
    assert osc.attributes["glpi_calibration_due"] == "2026-11-01" and osc.attributes["glpi_accuracy"] == 0.5
    assert "custom_signature" in json.loads(osc.attributes["glpi_unmapped"]), "an unsupported field is kept"
    db.close()


def test_a_changed_source_schema_waits_for_review_and_changes_nothing_by_itself(it_ws):
    ws = it_ws()
    s = unique_instance(snap("glpi11"))
    db = SessionLocal()
    approved = schema.approve(db, ws, schema.propose(db, ws, s), "tester")
    db.commit()
    changed = copy.deepcopy(s)
    changed["custom"]["custom_fields"].append({"id": 5, "assetdefinitions_id": 2, "system_name": "owner_email",
                                               "label": "Owner e-mail", "type": "Glpi\\Asset\\CustomFieldType\\StringType"})
    changed["items"]["Glpi\\CustomAsset\\LabInstrumentAsset"][0]["custom_owner_email"] = "lab@example.org"
    assert schema.status({"approved": approved}, changed) == "awaiting review"
    before = db.scalar(select(Schema).where(Schema.workspace_id == ws, Schema.name == "Lab instrument")).attributes
    st = settings(ws, changed, schema={"approved": approved})
    importer.run(db, st, changed, "tester")
    db.commit()
    lab = db.scalar(select(Schema).where(Schema.workspace_id == ws, Schema.name == "Lab instrument"))
    assert lab.attributes == before, "the installed schema is as approved"
    osc = by_ref(db, mapping.ref(st.instance, "Glpi\\CustomAsset\\LabInstrumentAsset", 1))
    assert json.loads(osc.attributes["glpi_unmapped"])["custom_owner_email"] == "lab@example.org"
    proposal = schema.propose(db, ws, changed)
    new = {f["source"]: f["action"] for t in proposal["types"] for f in t["fields"]}
    assert new["custom_owner_email"] == "create" and new["custom_lab"] == "reuse"
    db.close()


def test_glpi_10_plugin_fields_go_on_the_workspace_type_once_approved(it_ws):
    ws = it_ws()
    s = unique_instance(snap("glpi10"))
    db = SessionLocal()
    proposal = schema.propose(db, ws, s)
    ext = {e["source"]: e for e in proposal["extensions"]}
    assert ext["infos.budgetcodefield"]["argus_type"] == "Computing Node"
    assert ext["infos.relatedfield"]["action"] == "unsupported"
    assert "infos.sectionheader" not in ext
    generic = {t["source"]: t for t in proposal["types"]}
    assert generic["PluginGenericobjectUps"]["action"] == "create"
    approved = schema.approve(db, ws, proposal, "tester")
    st = settings(ws, s, schema={"approved": approved})
    importer.run(db, st, s, "tester")
    db.commit()
    srv = by_ref(db, mapping.ref(st.instance, "Computer", 1))
    assert srv.attributes["glpi_infos_budgetcodefield"] == "B-17"
    assert srv.attributes["glpi_infos_criticalityfield"] == "High"
    assert json.loads(srv.attributes["glpi_unmapped"])["infos.relatedfield"] == "Computer:2"
    node = db.get(Schema, srv.schema_uid)
    while node.name != "Computing Node":
        node = db.get(Schema, node.parent_schema_uid)
    assert "glpi_infos_budgetcodefield" in {a["key"] for a in node.attributes}
    from app.packages.loader import available
    shipped = {t["name"]: t for t in available()["it"].section("object_types")["types"]}
    assert "glpi_infos_budgetcodefield" not in {a["key"] for a in shipped["Computing Node"].get("attributes") or []}
    ups = by_ref(db, mapping.ref(st.instance, "PluginGenericobjectUps", 1))
    assert ups.type == "UPS unit"
    db.close()


# --------------------------------------------------------------------------- importing

@pytest.mark.parametrize("version", ["glpi10", "glpi11"])
def test_an_import_maps_the_standard_records_scoped_by_entity(version, it_ws):
    ws = it_ws()
    s = unique_instance(snap(version))
    db = SessionLocal()
    login = f"jdoe-{secrets.token_hex(3)}"
    s["users"]["5"]["login"] = s["dropdowns"]["User"]["5"] = login
    jdoe = User(id=f"u-{secrets.token_hex(3)}", email=f"{login}@example.org", username=login)
    db.add(jdoe)
    db.commit()
    st = settings(ws, s)
    plan = importer.plan(db, st, s)
    here = plan["workspaces"][ws]
    created = {r["ref"].split(":", 2)[2] for r in here["creates"]}
    assert {"Computer:1", "Computer:2", "NetworkEquipment:1", "Location:10", "Contract:1", "Software:1",
            "SoftwareLicense:1", "NetworkPort:1"} <= created
    assert "Computer:3" not in created and "Computer:4" not in created and "Computer:5" not in created
    assert plan["outside_entity_map"] == 2                        # lap-7 and the other site's ticket
    assert db.scalar(select(Asset).where(Asset.workspace_id == ws)) is None, "a plan writes nothing"

    importer.run(db, st, s, "tester")
    db.commit()
    srv = by_ref(db, mapping.ref(st.instance, "Computer", 1))
    assert srv.type == "Server" and srv.workspace_id == ws
    a = srv.attributes
    assert (a["serial"], a["inventory_number"], a["manufacturer"], a["model"], a["hostname"]) == \
        ("SN-1001", "INV-1001", "Dell", "PowerEdge R650", "srv-db01")
    assert a["argus_responsible"] == jdoe.id and a["ip"] == "192.168.10.5" and a["mac"] == "aa:bb:cc:00:11:22"
    assert a["description"] == "Main database" and a["glpi_url"].endswith("/front/computer.form.php?id=1")
    room = by_ref(db, mapping.ref(st.instance, "Location", 10))
    assert a["argus_location"] == room.uid
    kept = json.loads(a["glpi_unmapped"])
    assert kept["states_id"] == {"id": 1, "name": "In use"} and kept["uuid"] == "4c4c-4544"
    assert by_ref(db, mapping.ref(st.instance, "Computer", 2)).type == "Workstation"
    assert "users_id" in json.loads(by_ref(db, mapping.ref(st.instance, "Computer", 2)).attributes["glpi_unmapped"])
    assert by_ref(db, mapping.ref(st.instance, "NetworkEquipment", 2)).type == "Wireless Access Point"
    lic = by_ref(db, mapping.ref(st.instance, "SoftwareLicense", 1))
    assert lic.attributes["license_key"] == "XXXX-YYYY-ZZZZ" and lic.attributes["seats"] == 50
    assert lic.attributes["licensed_product"] == by_ref(db, mapping.ref(st.instance, "Software", 2)).uid
    contract = by_ref(db, mapping.ref(st.instance, "Contract", 1))
    assert contract.attributes["end_date"] == "2027-01-01" and contract.attributes["renewal"] == "Tacit"
    assert contract.attributes["counterparty"] == [by_ref(db, mapping.ref(st.instance, "Supplier", 1)).uid]
    edges = {(r.relation_type, r.to_asset_uid) for r in db.scalars(select(Relation).where(Relation.from_asset_uid == srv.uid))}
    assert ("has installed", by_ref(db, mapping.ref(st.instance, "SoftwareVersion", 1)).uid) in edges
    assert ("governed by", contract.uid) in edges
    port = by_ref(db, mapping.ref(st.instance, "NetworkPort", 1))
    assert port.key == f"{srv.key}:eth0"
    # tickets, problems and changes, linked to what GLPI links them to; the document attached once to each
    tickets = {t.attributes["argus_source_key"]: t for t in db.scalars(select(Issue).where(Issue.workspace_id == ws))}
    t1 = tickets[mapping.ref(st.instance, "Ticket", 1)]
    assert (t1.title, t1.state, t1.priority, t1.description) == ("Database slow", "in_progress", "High",
                                                                 "Users report slow queries.")
    assert db.get(Schema, t1.schema_uid).name == "Incident" and t1.asset_uid == srv.uid
    assert tickets[mapping.ref(st.instance, "Ticket", 2)].state == "closed"
    change = tickets[mapping.ref(st.instance, "Change", 1)]
    assert db.get(Schema, change.schema_uid).name == "Change" and change.state == "assessed"
    assert db.scalar(select(AssetTicket).where(AssetTicket.ticket_key == mapping.ref(st.instance, "Problem", 1))).asset_uid == srv.uid
    atts = list(db.scalars(select(Attachment).where(Attachment.workspace_id == ws)))
    assert len(atts) == 2 and {x.asset_uid or x.issue_uid for x in atts} == {srv.uid, t1.uid}
    # the room's coordinates went through the map's rules
    from app.models.spatial import SpatialFeature
    loc = db.scalar(select(SpatialFeature).where(SpatialFeature.subject_uid == room.uid))
    geometry = json.loads(loc.geometry) if isinstance(loc.geometry, str) else loc.geometry
    assert geometry["coordinates"] == [12.6713, 41.8226]                              # GeoJSON: lon, lat
    db.close()


def test_importing_the_same_snapshot_again_changes_nothing(it_ws):
    ws = it_ws()
    s = unique_instance(snap("glpi10"))
    db = SessionLocal()
    st = settings(ws, s)
    importer.run(db, st, s, "tester")
    db.commit()
    counts = (db.query(Asset).filter(Asset.workspace_id == ws).count(), db.query(Issue).filter(Issue.workspace_id == ws).count(),
              db.query(Attachment).filter(Attachment.workspace_id == ws).count())
    plan = importer.plan(db, st, s)["workspaces"][ws]
    assert plan["creates"] == [] and plan["updates"] == [] and plan["conflicts"] == []
    assert plan["tickets"]["creates"] == 0 and plan["tickets"]["updates"] == 0
    again = importer.run(db, st, s, "tester")["workspaces"][ws]
    db.commit()
    assert again["ledger"]["parse_skipped"] is True
    assert (db.query(Asset).filter(Asset.workspace_id == ws).count(), db.query(Issue).filter(Issue.workspace_id == ws).count(),
            db.query(Attachment).filter(Attachment.workspace_id == ws).count()) == counts
    db.close()


@pytest.mark.parametrize("authority", ["argus", "glpi"])
def test_a_re_import_updates_what_changed_and_keeps_local_edits_by_the_authority_policy(authority, it_ws):
    ws = it_ws()
    s = unique_instance(snap("glpi10"))
    db = SessionLocal()
    st = settings(ws, s, authority={"records": authority, "tickets": authority})
    importer.run(db, st, s, "tester")
    db.commit()
    srv = by_ref(db, mapping.ref(st.instance, "Computer", 1))
    sw = by_ref(db, mapping.ref(st.instance, "NetworkEquipment", 1))
    # local edits: one field GLPI will also change, one it will not
    service.edit_values(db, ws, "steward", srv.uid, {"attr:serial": "SN-LOCAL", "attr:inventory_number": "INV-LOCAL"})
    t1 = db.scalar(select(Issue).where(Issue.attributes["argus_source_key"].astext == mapping.ref(st.instance, "Ticket", 1)))
    t1.title = "Database slow (checked)"
    db.commit()

    newer = copy.deepcopy(s)
    comp = newer["items"]["Computer"][0]
    comp["serial"], comp["date_mod"] = "SN-2002", "2026-10-01 07:00:00"           # changed in GLPI too
    newer["items"]["NetworkEquipment"][0]["serial"] = "SW-78"                       # changed only in GLPI
    t = newer["items"]["Ticket"][0]
    t["name"], t["status"] = "Database slow again", 5
    plan = importer.plan(db, st, newer)["workspaces"][ws]
    upd = {r["ref"]: r for r in plan["updates"]}
    assert upd[mapping.ref(st.instance, "NetworkEquipment", 1)]["fields"] == ["serial"]
    conflict = next(c for c in plan["conflicts"] if c["field"] == "serial")
    assert (conflict["argus"], conflict["glpi"], conflict["previously"]) == ("SN-LOCAL", "SN-2002", "SN-1001")
    kept = next(k for k in plan["local_edits_kept"] if k["ref"] == mapping.ref(st.instance, "Computer", 1))
    assert "inventory_number" in kept["fields"]
    assert plan["tickets"]["conflicts"][0]["field"] == "title"

    importer.run(db, st, newer, "tester")
    db.commit()
    db.refresh(srv), db.refresh(sw), db.refresh(t1)
    assert sw.attributes["serial"] == "SW-78", "a GLPI change to a field nobody edited here applies"
    assert srv.attributes["inventory_number"] == "INV-LOCAL", "an edit GLPI did not contradict stays"
    assert t1.state == "resolved", "GLPI's own change to the ticket applies"
    # A person's confirmed edit is never overwritten by a source: it holds, and the difference is a review item.
    assert srv.attributes["serial"] == "SN-LOCAL"
    assert list(db.scalars(select(Conflict).where(Conflict.subject_uid == srv.uid, Conflict.predicate == "attr:serial")))
    # Tickets are not in the ledger: the authority policy decides there.
    assert t1.title == ("Database slow (checked)" if authority == "argus" else "Database slow again")
    db.close()


def test_a_record_glpi_stops_listing_is_never_retired_without_a_decision(it_ws):
    ws = it_ws()
    s = unique_instance(snap("glpi10"))
    db = SessionLocal()
    st = settings(ws, s)
    importer.run(db, st, s, "tester")
    db.commit()
    pc = by_ref(db, mapping.ref(st.instance, "Computer", 2))
    sw = by_ref(db, mapping.ref(st.instance, "NetworkEquipment", 1))
    newer = copy.deepcopy(s)
    newer["items"]["Computer"] = [c for c in newer["items"]["Computer"] if c["id"] != 2]
    newer["items"]["NetworkEquipment"][0]["is_deleted"] = 1                  # moved to GLPI's trash
    newer["items"]["Item_SoftwareVersion"] = [x for x in newer["items"]["Item_SoftwareVersion"] if x["items_id"] != 2]
    plan = importer.plan(db, st, newer)["workspaces"][ws]
    reasons = {c["ref"]: c["reason"] for c in plan["retirement_candidates"]}
    assert reasons == {mapping.ref(st.instance, "Computer", 2): "no longer listed by GLPI",
                       mapping.ref(st.instance, "NetworkEquipment", 1): "in GLPI's trash",
                       mapping.ref(st.instance, "NetworkPort", 2): "in GLPI's trash"}     # the switch's port
    importer.run(db, st, newer, "tester")
    db.commit()
    db.refresh(pc), db.refresh(sw)
    assert (pc.record_status, sw.record_status) == ("Active", "Active"), "nothing retired by the import"
    items = {c.subject_uid: c for c in db.scalars(select(Conflict).where(Conflict.conflict_type == "retirement_candidate",
                                                                       Conflict.workspace_id == ws))}
    assert {pc.uid, sw.uid} <= set(items) and len(items) == 3
    # a person decides: retire one, keep the other
    importer.decide_retirement(db, ws, st, mapping.ref(st.instance, "Computer", 2), "retire", "steward")
    importer.decide_retirement(db, ws, st, mapping.ref(st.instance, "NetworkEquipment", 1), "keep", "steward")
    db.commit()
    st2 = settings(ws, newer, key_prefix=st.prefix, retired_refs=[mapping.ref(st.instance, "Computer", 2)],
                   kept_refs=[mapping.ref(st.instance, "NetworkEquipment", 1)])
    importer.run(db, st2, newer, "tester")
    db.commit()
    db.refresh(pc), db.refresh(sw)
    assert pc.record_status == "Retired" and sw.record_status == "Active"
    left = list(db.scalars(select(Conflict).where(Conflict.conflict_type == "retirement_candidate",
                                                Conflict.workspace_id == ws)))
    assert [c.detail["source"] for c in left] == [mapping.ref(st.instance, "NetworkPort", 2)], "only the undecided"
    db.close()


def test_an_import_needs_the_it_package_and_installs_nothing(it_ws):
    from app.packages.requirements import MissingPrerequisite
    ws = it_ws(packages=("core-facility",))
    s = unique_instance(snap("glpi10"))
    db = SessionLocal()
    plan = importer.plan(db, settings(ws, s), s)
    assert set(plan["workspaces"][ws]["missing_packages"]) == {"it-catalogue", "records"}
    with pytest.raises(MissingPrerequisite):
        importer.run(db, settings(ws, s), s, "tester")
    db.rollback()
    assert set(installer.installed(db, ws)) == {"core-facility"}
    db.close()


def test_a_licence_key_is_visible_only_to_those_given_the_class(it_ws):
    from app.services.visibility import Grants, restricted_fields
    ws = it_ws()
    s = unique_instance(snap("glpi10"))
    db = SessionLocal()
    st = settings(ws, s)
    importer.run(db, st, s, "tester")
    db.commit()
    lic = by_ref(db, mapping.ref(st.instance, "SoftwareLicense", 1))
    assert restricted_fields(db, lic.schema_uid)["license_key"] == "license_keys"
    from app.services.visibility import hidden_fields
    assert "license_key" in hidden_fields(db, lic, Grants())
    assert "license_key" not in hidden_fields(db, lic, Grants({"license_keys"}))
    db.close()


# --------------------------------------------------------------------------- the live client

class FakeResponse:
    def __init__(self, status, body=None, headers=None, content=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.content = content if content is not None else json.dumps(body).encode() if body is not None else b""
        self.text = self.content.decode(errors="replace")

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeGlpi:
    """GLPI's legacy REST API over a fixture: sessions, pages with Content-Range, missing rights, documents."""

    def __init__(self, fixture: dict, page: int = 2):
        self.f, self.page, self.calls = fixture, page, []
        self.verify = True

    def get(self, url, headers=None, params=None, timeout=None):
        from urllib.parse import unquote
        self.calls.append((url, dict(headers or {}), dict(params or {})))
        if url.endswith("/api.php/v2/status"):
            return FakeResponse(401 if self.f["api"].get("high_level") else 404, {})
        path = unquote(url.split("/apirest.php/", 1)[1]).rstrip("/")
        if path == "initSession":
            assert headers["Authorization"] == "user_token secret-user" and headers["App-Token"] == "secret-app"
            return FakeResponse(200, {"session_token": "s-1"})
        assert headers.get("Session-Token") == "s-1", "every call after the first carries the session"
        if path == "killSession":
            return FakeResponse(200, {})
        if path == "getGlpiConfig":
            return FakeResponse(200, {"cfg_glpi": {"version": self.f["config"]["version"], "secret_thing": "x"}})
        if path.startswith("Document/") and params.get("alt") == "media":
            return FakeResponse(200, content=base64.b64decode(self.f["files"][path.split("/")[1]]))
        rows = self._rows(path)
        if rows is None:
            return FakeResponse(403 if path in self.f["unavailable"] else 400, ["ERROR_RIGHT_MISSING"])
        start, end = (int(x) for x in params["range"].split("-"))
        end = min(end, start + self.page - 1)
        chunk = rows[start:end + 1]
        return FakeResponse(206 if len(rows) > len(chunk) else 200, chunk,
                            {"Content-Range": f"{start}-{start + len(chunk) - 1}/{len(rows)}"})

    def _rows(self, itemtype):
        f = self.f
        if itemtype == "Entity":
            return f["entities"]
        if itemtype in f["items"]:
            return f["items"][itemtype]
        if itemtype in f["dropdowns"]:
            return [{"id": int(k), "name": v} for k, v in f["dropdowns"][itemtype].items()]
        custom = f["custom"]
        if itemtype == source.GLPI11_DEFINITIONS and custom.get("asset_definitions"):
            return custom["asset_definitions"]
        if itemtype == source.GLPI11_FIELDS and custom.get("custom_fields"):
            return custom["custom_fields"]
        if itemtype == "PluginFieldsContainer" and custom.get("plugin_containers"):
            return custom["plugin_containers"]
        if itemtype == "PluginFieldsField" and custom.get("plugin_fields"):
            return custom["plugin_fields"]
        if itemtype == "PluginGenericobjectType" and custom.get("generic_types"):
            return custom["generic_types"]
        for container, per in (custom.get("plugin_values") or {}).items():
            for it, rows in per.items():
                if itemtype in source.plugin_value_itemtypes(it, container)[-1:]:
                    return rows
        if itemtype == "Plugin":
            return f["plugins"] or None
        return None


@pytest.mark.parametrize("version", ["glpi10", "glpi11"])
def test_the_live_client_reads_what_the_api_exposes_page_by_page(version):
    f = snap(version)
    fake = FakeGlpi(f)
    with source.LegacyClient(f["instance"], "secret-user", "secret-app", session=fake) as client:
        read = source.read(client)
        assert client.document(1) == b"%PDF-1.4 warranty"
    assert fake.calls[-1][0].endswith("/killSession/")
    assert read["config"] == {"version": f["config"]["version"]}, "only what discovery needs is kept"
    assert [r["id"] for r in read["items"]["Computer"]] == [1, 2, 3, 4, 5], "every page"
    assert "Phone" in read["unavailable"]
    assert read["api"]["high_level"] == f["api"]["high_level"]
    if version == "glpi11":
        assert read["custom"]["asset_definitions"] and read["items"]["Glpi\\CustomAsset\\LabInstrumentAsset"]
        assert read["dropdowns"]["Glpi\\CustomDropdown\\LabDropdown"] == {"1": "Optics lab", "2": "RF lab"}
    else:
        assert read["custom"]["plugin_values"]["infos"]["Computer"][0]["budgetcodefield"] == "B-17"
    found = discovery.discover(read)
    assert found["version"] == f["config"]["version"]
    assert all(c[2].get("expand_dropdowns") in (None, "false") for c in fake.calls), "ids, resolved here"


# --------------------------------------------------------------------------- the API

def test_the_api_keeps_tokens_secret_and_walks_discovery_review_preview_import_and_decisions(it_ws, monkeypatch):
    import uuid as _uuid
    from fastapi.testclient import TestClient
    from app.auth import OidcIdentity, get_identity
    from app.main import app
    from app.models.import_config import ImportConfig
    from app.routers import glpi as glpi_router
    ws = it_ws()
    s = unique_instance(snap("glpi11"))
    db = SessionLocal()
    admin = User(id=str(_uuid.uuid4()), email=f"glpi-{secrets.token_hex(3)}@argus.test", name="admin", is_admin=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    db.close()
    current = {"snap": s}
    monkeypatch.setattr(glpi_router, "read_live", lambda c: copy.deepcopy(current["snap"]))
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
    client = TestClient(app)
    h = {"X-Workspace-Id": ws}
    try:
        r = client.post("/v1/glpi/connections", headers=h, json={
            "name": "Lab GLPI", "base_url": s["instance"], "user_token": "user-secret", "app_token": "app-secret",
            "verify_tls": True, "key_prefix": f"API{secrets.token_hex(2).upper()}", "documents": True, "tickets": True})
        assert r.status_code == 201, r.text
        c = r.json()
        assert c["has_credentials"] and "user-secret" not in r.text and "app-secret" not in r.text
        db = SessionLocal()
        stored = db.get(ImportConfig, c["uid"])
        assert "user-secret" not in (stored.encrypted_secret or "") and "user-secret" not in json.dumps(stored.params)
        db.close()
        found = client.post(f"/v1/glpi/connections/{c['uid']}/discover", headers=h).json()
        assert found["discovery"]["version"] == "11.0.1" and found["schema"]["status"] == "awaiting review"
        assert found["entity_map"][0]["entity_id"] == 0
        listed = client.get("/v1/glpi/connections", headers=h).text
        assert "user-secret" not in listed
        stale = client.post(f"/v1/glpi/connections/{c['uid']}/schema/approve", headers=h, json={"digest": "old"})
        assert stale.status_code == 409
        ok = client.post(f"/v1/glpi/connections/{c['uid']}/schema/approve", headers=h,
                         json={"digest": found["schema"]["proposal"]["digest"]})
        assert ok.status_code == 200 and ok.json()["status"] == "approved"
        preview = client.post(f"/v1/glpi/connections/{c['uid']}/preview", headers=h).json()
        assert preview["schema_status"] == "approved" and preview["workspaces"][ws]["creates"]
        changed = copy.deepcopy(s)
        changed["items"]["Computer"][0]["name"] = "srv-db01-renamed"
        current["snap"] = changed
        refused = client.post(f"/v1/glpi/connections/{c['uid']}/run", headers=h, json={"expect_digest": preview["digest"]})
        assert refused.status_code == 409 and refused.json()["detail"]["error"] == "GLPI changed since the preview"
        done = client.post(f"/v1/glpi/connections/{c['uid']}/run", headers=h, json={})
        assert done.status_code == 200, done.text
        assert done.json()["job_uid"]
        # GLPI stops listing a computer: a candidate, decided through the API
        gone = copy.deepcopy(changed)
        gone["items"]["Computer"] = [x for x in gone["items"]["Computer"] if x["id"] != 2]
        current["snap"] = gone
        assert client.post(f"/v1/glpi/connections/{c['uid']}/run", headers=h, json={}).status_code == 200
        cands = client.get(f"/v1/glpi/connections/{c['uid']}/retirement-candidates", headers=h).json()
        ref2 = next(x["ref"] for x in cands if x["ref"].endswith(":Computer:2"))
        kept = client.post(f"/v1/glpi/connections/{c['uid']}/retirement-candidates", headers=h,
                           json={"ref": ref2, "decision": "keep"})
        assert kept.status_code == 200
        assert ref2 not in {x["ref"] for x in client.get(f"/v1/glpi/connections/{c['uid']}/retirement-candidates",
                                                          headers=h).json()}
        assert client.post(f"/v1/glpi/connections/{c['uid']}/run", headers=h, json={}).status_code == 200
        db = SessionLocal()
        assert by_ref(db, ref2).record_status == "Active", "kept: an ARGUS record now"
        db.close()
    finally:
        app.dependency_overrides.pop(get_identity, None)
        db = SessionLocal()
        db.delete(db.get(User, admin.id))
        db.commit()
        db.close()


def test_a_restricted_value_is_left_out_of_the_report_for_whoever_may_not_see_it():
    from app.services.visibility import Grants
    report = {"workspaces": {"w": {"conflicts": [
        {"field": "license_key", "argus": "A", "glpi": "B", "previously": "C", "restricted": "license_keys"},
        {"field": "serial", "argus": "1", "glpi": "2", "previously": "3"}]}}}
    out = importer.redact(copy.deepcopy(report), Grants())["workspaces"]["w"]["conflicts"]
    assert out[0]["argus"] == "(restricted)" and out[1]["argus"] == "1"
    assert importer.redact(copy.deepcopy(report), Grants({"license_keys"}))["workspaces"]["w"]["conflicts"][0]["argus"] == "A"
