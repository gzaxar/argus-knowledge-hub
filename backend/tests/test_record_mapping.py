"""Imported records mapped onto a workspace's types by a plan per source type:
rules and the AI propose the plan, a person corrects it, rows follow it;
applying creates the records through the ledger with references resolved,
old keys kept, subresources carried, and links turned into relations once
both ends are mapped."""
import json
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import or_

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.asset import Asset, Relation
from app.models.asset_subresources import AssetLabel
from app.models.llm_config import LLMConfig
from app.models.schema import Schema
from app.models.user import User
from app.models.workspace import Workspace
from app.services.asset_types import ensure_asset_types
from tests.confirm import typed

client = TestClient(app)


@pytest.fixture()
def world():
    t = secrets.token_hex(3)
    src, cat, dst, other = f"imp-{t}", f"cat-{t}", f"dst-{t}", f"oth-{t}"
    db = SessionLocal()
    db.add_all([Workspace(id=w, name=w) for w in (src, cat, dst, other)])
    db.flush()
    # The target's own copy of the catalogue types: the database may hold other shared catalogues, and a
    # workspace's own type is the one it uses.
    ensure_asset_types(db, dst)
    # Like accelerator-infn: the target owns the shared set of types (equipment, catalogue, locations).
    from app.services.asset_types import GLOBAL_TYPES
    for schema in db.query(Schema).filter(Schema.workspace_id == dst, Schema.name.in_(GLOBAL_TYPES)):
        schema.is_global = True
    admin = User(id=str(uuid.uuid4()), email=f"admin-{t}@argus.test", is_admin=True)
    db.add(admin)
    pm = db.scalar(__import__("sqlalchemy").select(Schema).where(Schema.workspace_id == dst,
                                                                  Schema.name == "Product Model"))
    shared_pm = Asset(uid=str(uuid.uuid4()), workspace_id=cat, schema_uid=pm.uid, key=f"PM-PKR-{t}",
                      name=f"PKR 251 {t}", type="Product Model", attributes={"model_code": f"PKR251{t}"},
                      is_global=True)
    hidden_pm = Asset(uid=str(uuid.uuid4()), workspace_id=cat, schema_uid=pm.uid, key=f"PM-ATH-{t}",
                      name=f"ATH 2303 M {t}", type="Product Model", attributes={}, is_global=False)
    db.add_all([shared_pm, hidden_pm])
    gauges = Schema(uid=f"{src}:gauges", workspace_id=src, name="Gauges")
    pumps = Schema(uid=f"{src}:pumps", workspace_id=src, name="Secondary Pumps")
    db.add_all([gauges, pumps])
    db.flush()

    def asset(schema, key, name, **attrs):
        uid = str(uuid.uuid4())
        db.add(Asset(uid=uid, workspace_id=src, schema_uid=schema.uid, key=f"{key}-{t}", name=name, type=schema.name,
                     attributes={"key": key, "name": name, "created": "11/Feb/26 3:50 PM", **attrs}))
        return uid

    owner = f"SERVIZIO VUOTO {t.upper()}"
    ctrl = asset(gauges, "LNFT2-1", "FI33-V-VUG-TPG-001", owner=owner, status="Active",
                 facility="EUAPS", hw_model=f"TPG 366 {t}", locations="LNF.D1.DE56.B1.BAL1")
    g = asset(gauges, "LNFT2-2", "FI33-V-VUG-FR-001", owner=owner, status="Active", facility="EUAPS",
              hw_model=f"PKR 251 {t}", locations="LNF.D1.DE56.B1.BAL1", controller=ctrl)
    p = asset(pumps, "LNFT2-3", "SP5-V-PMP-TRB-003", owner=owner, status="Uninstalled",
              facility="EUAPS", hw_model=f"ATH 2303 M {t}")
    db.flush()
    db.add(Relation(workspace_id=src, from_asset_uid=p, to_asset_uid=g, relation_type="HW connection"))
    ids = {"gauges": gauges.uid, "pumps": pumps.uid}
    pm_uid = shared_pm.uid
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    db.close()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
    yield {"src": src, "dst": dst, "cat": cat, "t": t, "types": ids, "uids": {"ctrl": ctrl, "g": g, "p": p},
           "pm": pm_uid, "owner": owner}
    for ws in (dst, src, cat, other):
        client.delete(f"/v1/workspaces/{ws}", headers=typed(ws))
    from app.models.group import Group
    db = SessionLocal()
    for g in db.query(Group).filter(Group.name.ilike(f"%{t}%")):
        db.delete(g)
    db.commit()
    db.close()
    app.dependency_overrides.pop(get_identity, None)


def start(w, use_ai=False):
    r = client.post("/v1/catalogue-mappings", json={"kind": "records", "source_workspace_id": w["src"],
                                                    "target_workspace_id": w["dst"],
                                                    "type_uids": list(w["types"].values()), "use_ai": use_ai})
    assert r.status_code == 201, r.text
    m = client.get(f"/v1/catalogue-mappings/{r.json()['id']}").json()
    assert m["state"] == "ready", m
    return m


def rows(m):
    return {i["source_key"].rsplit("-", 1)[0]: i for i in m["items"]}


def test_rules_plan_the_types_they_can_name_and_the_fields_every_import_has(world):
    w = world
    m = start(w)
    plan = m["plan"]
    gauges = plan[w["types"]["gauges"]]
    assert gauges["target_type"]["name"] == "Vacuum Gauge" and gauges["target_type"]["source"] == "rule"
    assert plan[w["types"]["pumps"]]["target_type"] is None                        # not clear from the name
    f = gauges["fields"]
    assert f["hw_model"]["kind"] == "reference" and f["hw_model"]["target"] == "product_model"
    assert f["status"] == {**f["status"], "kind": "enum", "target": "argus_lifecycle"}
    assert f["status"]["values"] == {"Active": "in_service"}
    assert f["facility"]["target"] == "argus_facility"
    assert f["owner"]["kind"] == "group" and f["owner"]["target"] == "argus_owner"
    assert f["controller"]["kind"] == "link"
    g = rows(m)["LNFT2-2"]["proposal"]
    assert g["type"]["name"] == "Vacuum Gauge"
    assert g["attributes"]["product_model"]["value"] == w["pm"]                     # resolved, shared
    assert g["attributes"]["model"]["value"] == f"PKR 251 {w['t']}"
    assert g["attributes"]["argus_lifecycle"]["value"] == "In service"             # stored as its label
    assert f"owner: {w['owner']}" in g["attributes"]["description"]["value"]       # no such group yet
    assert any("No group" in x for x in g["warnings"])
    assert any("No Location" in x for x in g["warnings"])
    assert any("choose one" in x for x in rows(m)["LNFT2-3"]["proposal"]["warnings"])


def test_a_corrected_plan_moves_its_rows_and_apply_creates_links_once_both_ends_exist(world):
    w = world
    m = start(w)
    mid = m["id"]
    voc = client.get(f"/v1/catalogue-mappings/{mid}/vocabulary").json()
    turbo = next(t for t in voc["types"] if t["name"] == "Turbo Pump")
    assert "acts on" in voc["verbs"]
    r = client.put(f"/v1/catalogue-mappings/{mid}/plan/{w['types']['pumps']}",
                   json={"target_type_uid": turbo["uid"], "relations": {"HW connection": {"verb": "reached through"}},
                         "fields": {"status": {"kind": "enum", "target": "argus_lifecycle",
                                               "values": {"Uninstalled": "standby"}}}})
    assert r.status_code == 200, r.text
    r = client.put(f"/v1/catalogue-mappings/{mid}/plan/{w['types']['gauges']}",
                   json={"fields": {"controller": {"kind": "link", "verb": "acts on", "reverse": True}}})
    assert r.status_code == 200, r.text
    from app.models.catalogue_mapping import CatalogueMapping
    db = SessionLocal()                                       # stored, not only in the request's memory
    assert db.get(CatalogueMapping, mid).plan[w["types"]["gauges"]]["fields"]["controller"]["verb"] == "acts on"
    db.close()
    m = client.get(f"/v1/catalogue-mappings/{mid}").json()
    pump = rows(m)["LNFT2-3"]["proposal"]
    assert pump["type"]["name"] == "Turbo Pump" and pump["attributes"]["argus_lifecycle"]["value"] == "Standby"
    assert any("not shared" in x for x in pump["warnings"])                        # ATH exists, not shared
    assert pump["attributes"]["product_model"]["hidden"]["name"] == f"ATH 2303 M {w['t']}"
    assert pump["attributes"]["product_model"]["value"] is None
    assert [h["name"] for h in m["hidden_references"]] == [f"ATH 2303 M {w['t']}"]

    # Only the pump first: its link waits for the gauge.
    client.patch(f"/v1/catalogue-mappings/{mid}/items/{rows(m)['LNFT2-3']['id']}", json={"status": "accepted"})
    refused = client.post(f"/v1/catalogue-mappings/{mid}/apply")                   # never silently text-only
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "hidden_references"
    assert client.post(f"/v1/catalogue-mappings/{mid}/share-references").json() == {"shared": 1}
    m = client.get(f"/v1/catalogue-mappings/{mid}").json()
    assert m["hidden_references"] == []
    assert rows(m)["LNFT2-3"]["proposal"]["attributes"]["product_model"]["value"]       # now it resolves
    out = client.post(f"/v1/catalogue-mappings/{mid}/apply").json()
    assert out["applied"] == 1 and out["relations"] == 0, out
    for k in ("LNFT2-1", "LNFT2-2"):
        client.patch(f"/v1/catalogue-mappings/{mid}/items/{rows(m)[k]['id']}", json={"status": "accepted"})
    out = client.post(f"/v1/catalogue-mappings/{mid}/apply").json()
    assert out["applied"] == 2 and out["relations"] == 2 and not out["relations_failed"], out

    m = client.get(f"/v1/catalogue-mappings/{mid}").json()
    r = rows(m)
    db = SessionLocal()
    gauge, pump, ctrl = (db.get(Asset, r[k]["result_uid"]) for k in ("LNFT2-2", "LNFT2-3", "LNFT2-1"))
    assert gauge.workspace_id == w["dst"] and gauge.type == "Vacuum Gauge" and gauge.name == "FI33-V-VUG-FR-001"
    assert gauge.attributes["product_model"] == w["pm"] and gauge.attributes["argus_facility"] == "EUAPS"
    assert pump.type == "Turbo Pump" and pump.attributes["model"] == f"ATH 2303 M {w['t']}"
    assert pump.attributes["product_model"]
    # The reference is an edge of the graph too: the gauge is an instance of its Product Model.
    assert (gauge.uid, "instance of", w["pm"]) in {(e.from_asset_uid, e.relation_type, e.to_asset_uid)
                                                    for e in db.query(Relation).filter(Relation.from_asset_uid == gauge.uid)}
    assert not gauge.is_global and not pump.is_global                                # kept in the target by default
    edges = {(e.from_asset_uid, e.relation_type, e.to_asset_uid) for e in db.query(Relation).filter(
        Relation.workspace_id == w["dst"])}
    assert (pump.uid, "reached through", gauge.uid) in edges
    assert (ctrl.uid, "acts on", gauge.uid) in edges                                # reversed: controller acts on gauge
    assert db.query(AssetLabel).filter(AssetLabel.asset_uid == gauge.uid, AssetLabel.type == "former_key").count() == 1
    db.close()

    undone = client.post(f"/v1/catalogue-mappings/{mid}/undo").json()
    assert undone["relations_removed"] == 2 and undone["retired"] == 3
    srcs = {s["name"]: s for s in client.get(
        f"/v1/catalogue-mappings/sources?workspace_id={w['src']}&kind=records&target_workspace_id={w['dst']}").json()}
    assert srcs["Gauges"]["open"] == 2 and srcs["Secondary Pumps"]["open"] == 1


def test_the_ai_plans_types_fields_and_links_within_the_vocabulary(world, monkeypatch):
    w = world
    db = SessionLocal()
    db.add(LLMConfig(workspace_id=w["dst"], base_url="https://gateway.example/v1", model="m-1", enabled=True,
                     last_check_ok=True))
    db.commit()
    db.close()

    def complete(endpoint, system, user, max_tokens=512, extra=None):
        if "<types>" in user:
            return json.dumps({"types": [{"source": "Secondary Pumps", "target": "Turbo Pump", "confidence": 0.9,
                                          "reason": "turbomolecular pumps"},
                                         {"source": "Gauges", "target": "Starship", "confidence": 0.9}]})
        if "Secondary Pumps" in user:
            return json.dumps({"fields": {"owner": {"kind": "drop"},
                                          "status": {"kind": "enum", "target": "argus_lifecycle",
                                                     "values": {"Uninstalled": "standby"}},
                                          "facility": {"kind": "copy", "target": "no_such_attribute"}},
                               "links": {"HW connection": {"verb": "reached through", "reverse": False}},
                               "confidence": 0.85})
        return json.dumps({"fields": {"owner": {"kind": "drop"}},
                           "links": {"controller": {"verb": "invents", "reverse": True}}, "confidence": 0.8})

    monkeypatch.setattr("app.services.llm.complete", complete)
    m = start(w, use_ai=True)
    assert m["ai"]["used"] and len(m["ai"]["runs"]) == 3
    plan = m["plan"]
    pumps, gauges = plan[w["types"]["pumps"]], plan[w["types"]["gauges"]]
    assert pumps["target_type"]["name"] == "Turbo Pump" and pumps["target_type"]["source"] == "ai"
    assert gauges["target_type"]["name"] == "Vacuum Gauge"                         # "Starship" is not a type
    assert pumps["fields"]["owner"]["kind"] == "group"          # a confident rule is not overridden by the AI
    assert pumps["fields"]["status"]["values"] == {"Uninstalled": "standby"}
    assert pumps["fields"]["facility"]["target"] == "argus_facility"               # an unknown key is ignored
    assert pumps["relations"]["HW connection"]["verb"] == "reached through"
    assert gauges["fields"]["controller"]["verb"] is None                          # not a verb: dropped
    pump = rows(m)["LNFT2-3"]["proposal"]
    assert pump["attributes"]["argus_lifecycle"]["value"] == "Standby"                  # the AI's value map


def test_missing_locations_are_created_once_and_shared_by_every_row_that_names_them(world):
    w = world
    m = start(w)
    mid = m["id"]
    voc = client.get(f"/v1/catalogue-mappings/{mid}/vocabulary").json()
    gauge_type = m["plan"][w["types"]["gauges"]]["target_type"]["uid"]
    location = next(a for a in voc["attributes"][gauge_type] if a["key"] == "argus_location")
    area = next(t for t in location["create_types"] if t["name"] == "Area")
    assert {t["name"] for t in location["create_types"]} >= {"Area", "Building", "Rack"}
    bad = client.put(f"/v1/catalogue-mappings/{mid}/plan/{w['types']['gauges']}",
                     json={"fields": {"locations": {"kind": "reference", "target": "argus_location",
                                                    "create_type": gauge_type}}})
    assert bad.status_code == 422                                                  # a gauge is not a location
    r = client.put(f"/v1/catalogue-mappings/{mid}/plan/{w['types']['gauges']}",
                   json={"fields": {"locations": {"kind": "reference", "target": "argus_location",
                                                  "create_type": area["uid"]}}})
    assert r.status_code == 200, r.text
    m = client.get(f"/v1/catalogue-mappings/{mid}").json()
    g = rows(m)["LNFT2-2"]["proposal"]
    assert g["attributes"]["argus_location"]["create"]["type"] == "Area"
    assert not any("Location" in x for x in g["warnings"])
    for k in ("LNFT2-1", "LNFT2-2"):
        client.patch(f"/v1/catalogue-mappings/{mid}/items/{rows(m)[k]['id']}", json={"status": "accepted"})
    out = client.post(f"/v1/catalogue-mappings/{mid}/apply").json()
    assert out["applied"] == 2, out
    r = rows(client.get(f"/v1/catalogue-mappings/{mid}").json())
    db = SessionLocal()
    a, b = db.get(Asset, r["LNFT2-1"]["result_uid"]), db.get(Asset, r["LNFT2-2"]["result_uid"])
    assert a.attributes["argus_location"] == b.attributes["argus_location"]         # one Area for both
    place = db.get(Asset, a.attributes["argus_location"])
    assert place.type == "Area" and place.name == "LNF.D1.DE56.B1.BAL1" and place.workspace_id == w["dst"]
    assert not place.is_global                                                      # in the target, like the rows
    db.close()
    # A new mapping of the remaining row now finds the Area without creating another.
    rc = client.post(f"/v1/catalogue-mappings/{mid}/recheck").json()
    assert rc["rows"] == 1
    client.post(f"/v1/catalogue-mappings/{mid}/undo")
    db = SessionLocal()
    assert db.get(Asset, place.uid).record_status == "Retired"
    db.close()


def test_records_stay_in_the_target_unless_the_plan_shares_them(world):
    w = world
    m = start(w)
    mid = m["id"]
    gauges = w["types"]["gauges"]
    assert m["plan"][gauges]["share"] is False                                     # even for a shared type
    assert rows(m)["LNFT2-2"]["proposal"]["share"] is False
    r = client.put(f"/v1/catalogue-mappings/{mid}/plan/{gauges}", json={"share": True})
    assert r.status_code == 200 and r.json()["share"] is True
    m = client.get(f"/v1/catalogue-mappings/{mid}").json()
    row = rows(m)["LNFT2-2"]
    assert row["proposal"]["share"] is True
    client.patch(f"/v1/catalogue-mappings/{mid}/items/{row['id']}", json={"status": "accepted"})
    assert client.post(f"/v1/catalogue-mappings/{mid}/apply").json()["applied"] == 1
    uid = rows(client.get(f"/v1/catalogue-mappings/{mid}").json())["LNFT2-2"]["result_uid"]
    db = SessionLocal()
    assert db.get(Asset, uid).is_global is True
    db.close()


@pytest.fixture()
def cameras(world):
    w = world
    db = SessionLocal()
    cams = Schema(uid=f"{w['src']}:cameras", workspace_id=w["src"], name="Cameras")
    db.add(cams)
    db.flush()
    uids = {}
    for key, name, mac, ip in (("LNFT2-10", "FP3-B-CAM-VIS-001", f"00:30:53:{w['t'][:2]}:aa:01", "192.168.10.21"),
                               ("LNFT2-11", "FP3-B-CAM-VIS-002", f"00:30:53:{w['t'][:2]}:aa:01", "192.168.10.22")):
        uid = str(uuid.uuid4())
        db.add(Asset(uid=uid, workspace_id=w["src"], schema_uid=cams.uid, key=f"{key}-{w['t']}", name=name,
                     type="Cameras", attributes={"key": key, "name": name, "s_n": f"40{w['t']}{key[-1]}",
                                                 "mac_address": mac, "ip": ip, "hostname": name.lower(),
                                                 "status": "Active"}))
        uids[key] = uid
    cams_uid = cams.uid
    db.commit()
    db.close()
    return {**w, "cams": cams_uid}


def test_a_gige_camera_brings_its_ethernet_port_with_the_mac_and_its_address(cameras):
    from app.ledger.identity import strong_identifiers
    w = cameras
    r = client.post("/v1/catalogue-mappings", json={"kind": "records", "source_workspace_id": w["src"],
                                                    "target_workspace_id": w["dst"], "type_uids": [w["cams"]]})
    m = client.get(f"/v1/catalogue-mappings/{r.json()['id']}").json()
    plan = m["plan"][w["cams"]]
    assert plan["target_type"]["name"] == "Camera"
    assert plan["fields"]["s_n"]["target"] == "serial"
    assert plan["fields"]["mac_address"] == {**plan["fields"]["mac_address"], "kind": "companion",
                                             "companion": "ethernet", "target": "mac"}
    assert plan["fields"]["ip"]["companion"] == "address" and plan["fields"]["hostname"]["companion"] == "address"
    assert plan["companions"]["ethernet"]["type"]["name"] == "Equipment Port"
    assert plan["companions"]["address"]["verb"] == "described by"

    first = rows(m)["LNFT2-10"]
    linked = {c["id"]: c for c in first["proposal"]["companions"]}
    assert linked["ethernet"]["name"] == "FP3-B-CAM-VIS-001 eth0"
    assert {k: a["value"] for k, a in linked["ethernet"]["attributes"].items()} == {
        "mac": f"00:30:53:{w['t'][:2]}:aa:01", "port_kind": "RJ45", "port_label": "eth0"}
    assert {k: a["value"] for k, a in linked["address"]["attributes"].items()} == {
        "ip": "192.168.10.21", "hostname": "fp3-b-cam-vis-001", "record_kind": "Ethernet configuration"}
    assert "mac" not in (first["proposal"]["attributes"].get("description") or {}).get("value", "")
    # An "IP" that is a host name becomes the host name, with a note.
    from app.services import record_mapping as rm
    item = type("I", (), {"source": {"attributes": {"ip": "cceuapscam26"}}, "source_name": "cam"})()
    notes = []
    out = rm.derive_companions(SessionLocal(), plan, item, notes)
    address = next(c for c in out if c["id"] == "address")
    assert address["attributes"]["hostname"]["value"] == "cceuapscam26" and "ip" not in address["attributes"]
    assert any("host name" in n for n in notes)

    for k in ("LNFT2-10", "LNFT2-11"):
        client.patch(f"/v1/catalogue-mappings/{m['id']}/items/{rows(m)[k]['id']}", json={"status": "accepted"})
    out = client.post(f"/v1/catalogue-mappings/{m['id']}/apply").json()
    # The second camera claims the first one's MAC: the same hardware cannot be recorded twice.
    assert out["applied"] == 1 and len(out["failed"]) == 1 and "mac" in out["failed"][0]["error"], out

    camera_uid = rows(client.get(f"/v1/catalogue-mappings/{m['id']}").json())["LNFT2-10"]["result_uid"]
    db = SessionLocal()
    camera = db.get(Asset, camera_uid)
    assert camera.type == "Camera" and camera.attributes["serial"].startswith("40")
    edges = db.query(Relation).filter(or_(Relation.from_asset_uid == camera_uid, Relation.to_asset_uid == camera_uid)).all()
    port = next(db.get(Asset, e.from_asset_uid) for e in edges if e.relation_type == "port of")
    address = next(db.get(Asset, e.to_asset_uid) for e in edges if e.relation_type == "described by")
    assert port.type == "Equipment Port" and port.attributes["mac"].endswith(":aa:01") and port.attributes["port_kind"] == "RJ45"
    assert address.type == "Address Record" and address.attributes["ip"] == "192.168.10.21"
    # An Address Record naming the same MAC is not a second holder of the hardware.
    assert strong_identifiers({"mac": port.attributes["mac"]}, "Address Record") == []
    assert strong_identifiers({"mac": port.attributes["mac"]}, "Equipment Port") != []
    port_uid, address_uid = port.uid, address.uid
    db.close()

    client.post(f"/v1/catalogue-mappings/{m['id']}/undo")
    db = SessionLocal()
    assert all(db.get(Asset, u).record_status == "Retired" for u in (camera_uid, port_uid, address_uid))
    db.close()


def test_pipes_find_the_vacuum_component_by_its_alias_and_get_its_kind(world):
    w = world
    db = SessionLocal()
    pipes = Schema(uid=f"{w['src']}:pipes", workspace_id=w["src"], name="Pipes")
    db.add(pipes)
    db.flush()
    db.add(Asset(uid=str(uuid.uuid4()), workspace_id=w["src"], schema_uid=pipes.uid, key=f"LNFT2-20-{w['t']}",
                 name="FI31-V-VUP-TRL-001", type="Pipes",
                 attributes={"key": "LNFT2-20", "name": "FI31-V-VUP-TRL-001", "description": "Tratto discendente"}))
    pipes_uid = pipes.uid
    db.commit()
    db.close()
    r = client.post("/v1/catalogue-mappings", json={"kind": "records", "source_workspace_id": w["src"],
                                                    "target_workspace_id": w["dst"], "type_uids": [pipes_uid]})
    m = client.get(f"/v1/catalogue-mappings/{r.json()['id']}").json()
    plan = m["plan"][pipes_uid]
    assert plan["target_type"]["name"] == "Vacuum Component" and "pipe" in plan["target_type"]["reason"]
    assert plan["fixed"] == {"component_kind": "Pipe"}
    row = m["items"][0]
    assert row["proposal"]["attributes"]["component_kind"]["value"] == "Pipe"
    # A person can change what every row gets.
    r = client.put(f"/v1/catalogue-mappings/{m['id']}/plan/{pipes_uid}",
                   json={"fixed": {"component_kind": "Bellows", "flange_type": "CF"}})
    assert r.status_code == 200 and r.json()["fixed"] == {"component_kind": "Bellows", "flange_type": "CF"}
    bad = client.put(f"/v1/catalogue-mappings/{m['id']}/plan/{pipes_uid}", json={"fixed": {"flange_type": "XYZ"}})
    assert bad.status_code == 422
    row = client.get(f"/v1/catalogue-mappings/{m['id']}").json()["items"][0]
    client.patch(f"/v1/catalogue-mappings/{m['id']}/items/{row['id']}", json={"status": "accepted"})
    assert client.post(f"/v1/catalogue-mappings/{m['id']}/apply").json()["applied"] == 1
    uid = client.get(f"/v1/catalogue-mappings/{m['id']}").json()["items"][0]["result_uid"]
    db = SessionLocal()
    rec = db.get(Asset, uid)
    assert rec.type == "Vacuum Component" and rec.attributes["component_kind"] == "Bellows"
    assert rec.attributes["flange_type"] == "CF" and not rec.is_global
    db.close()


def test_the_owner_becomes_the_owning_service_a_group_found_or_made_once(world):
    from app.models.group import Group
    w = world
    m = start(w)
    mid, gauges = m["id"], w["types"]["gauges"]
    r = client.put(f"/v1/catalogue-mappings/{mid}/plan/{gauges}",
                   json={"fields": {"owner": {"kind": "group", "target": "argus_owner", "create_missing": True}}})
    assert r.status_code == 200, r.text
    m = client.get(f"/v1/catalogue-mappings/{mid}").json()
    g = rows(m)["LNFT2-2"]["proposal"]
    name = f"Servizio Vuoto {w['t'].title()}"
    assert g["attributes"]["argus_owner"]["create_group"]["name"] == name           # written the usual way
    for k in ("LNFT2-1", "LNFT2-2"):
        client.patch(f"/v1/catalogue-mappings/{mid}/items/{rows(m)[k]['id']}", json={"status": "accepted"})
    assert client.post(f"/v1/catalogue-mappings/{mid}/apply").json()["applied"] == 2
    r = rows(client.get(f"/v1/catalogue-mappings/{mid}").json())
    db = SessionLocal()
    a, b = db.get(Asset, r["LNFT2-1"]["result_uid"]), db.get(Asset, r["LNFT2-2"]["result_uid"])
    assert a.attributes["argus_owner"] == b.attributes["argus_owner"]               # one group for both
    group = db.get(Group, a.attributes["argus_owner"])
    assert group.name == name and group.source == "local"
    group_uid = group.uid
    db.close()
    out = client.post(f"/v1/catalogue-mappings/{mid}/undo").json()
    assert out["groups_removed"] == 1
    db = SessionLocal()
    assert db.get(Group, group_uid) is None
    # A group that exists (from the directory) is found whatever its spelling; nothing is made.
    db.add(Group(uid=str(uuid.uuid4()), name=f"Servizio Vuóto {w['t']}", source="ldap", dn=f"cn=vuoto-{w['t']}"))
    db.commit()
    db.close()
    client.post(f"/v1/catalogue-mappings/{mid}/recheck")
    g = rows(client.get(f"/v1/catalogue-mappings/{mid}").json())["LNFT2-2"]["proposal"]
    assert g["attributes"]["argus_owner"]["label"] == f"Servizio Vuóto {w['t']}" and "create_group" not in g["attributes"]["argus_owner"]


def test_rows_applied_with_text_only_get_their_reference_once_it_is_shared(world):
    w = world
    m = start(w)
    mid = m["id"]
    voc = client.get(f"/v1/catalogue-mappings/{mid}/vocabulary").json()
    turbo = next(t for t in voc["types"] if t["name"] == "Turbo Pump")
    client.put(f"/v1/catalogue-mappings/{mid}/plan/{w['types']['pumps']}", json={"target_type_uid": turbo["uid"]})
    m = client.get(f"/v1/catalogue-mappings/{mid}").json()
    client.patch(f"/v1/catalogue-mappings/{mid}/items/{rows(m)['LNFT2-3']['id']}", json={"status": "accepted"})
    out = client.post(f"/v1/catalogue-mappings/{mid}/apply?keep_text=true").json()      # chosen knowingly
    assert out["applied"] == 1
    uid = rows(client.get(f"/v1/catalogue-mappings/{mid}").json())["LNFT2-3"]["result_uid"]
    db = SessionLocal()
    pump = db.get(Asset, uid)
    assert "product_model" not in pump.attributes and pump.attributes["model"] == f"ATH 2303 M {w['t']}"
    hidden = db.query(Asset).filter(Asset.name == f"ATH 2303 M {w['t']}").one()
    assert client.post(f"/v1/catalogue-mappings/{mid}/fill-references").json() == {
        "records": 0, "filled": 0, "still_hidden": 1}
    hidden.is_global = True                                   # the catalogue is shared afterwards
    db.commit()
    hidden_uid = hidden.uid
    db.close()
    out = client.post(f"/v1/catalogue-mappings/{mid}/fill-references").json()
    assert out == {"records": 1, "filled": 1, "still_hidden": 0}
    db = SessionLocal()
    assert db.get(Asset, uid).attributes["product_model"] == hidden_uid
    edge = db.query(Relation).filter(Relation.from_asset_uid == uid, Relation.relation_type == "instance of").one()
    assert edge.to_asset_uid == hidden_uid and edge.derivation == "ledger"          # follows the filled-in field
    db.close()
    assert client.post(f"/v1/catalogue-mappings/{mid}/fill-references").json()["filled"] == 0     # once


def test_lists_go_to_multi_valued_attributes_and_structures_to_text_as_json():
    from app.services import record_mapping as rm
    zones = {"key": "zones", "type": "string", "multiValue": True}
    assert rm.coerce_value(zones, ["FI", "FI1"]) == ["FI", "FI1"]
    assert rm.coerce_value(zones, "FP7") == ["FP7"]                                     # one value, a list of one
    assert rm.coerce_value(zones, []) is None
    settings = {"key": "settings", "type": "text"}
    assert rm.coerce_value(settings, {"velo": 1, "dhlm": 24}) == '{"dhlm": 24, "velo": 1}'
    single = {"key": "serial", "type": "string"}
    assert rm.coerce_value(single, ["A"]) == "A"
    assert rm.coerce_value(single, ["A", "B"]) is None                                 # does not fit: description
    count = {"key": "n", "type": "integer", "multiValue": True}
    assert rm.coerce_value(count, ["1", "x"]) is None


def test_a_link_already_named_with_an_argus_verb_keeps_it():
    from app.services import record_mapping as rm
    assert rm.rule_relation("provided by") == {"verb": "provided by", "reverse": False, "source": "rule",
                                               "confidence": 0.95}
    assert rm.rule_relation("HW connection")["verb"] is None                           # needs a decision
    assert rm.rule_relation("on line")["verb"] is None                                 # deprecated


def test_a_record_applied_by_one_mapping_is_not_created_again_by_another(world):
    w = world
    first, second = start(w), start(w)                         # two open mappings of the same records
    for m in (first, second):
        row = rows(m)["LNFT2-2"]
        client.patch(f"/v1/catalogue-mappings/{m['id']}/items/{row['id']}", json={"status": "accepted"})
    assert client.post(f"/v1/catalogue-mappings/{first['id']}/apply").json()["applied"] == 1
    out = client.post(f"/v1/catalogue-mappings/{second['id']}/apply").json()
    assert out["applied"] == 0 and "already mapped" in out["failed"][0]["error"]
    db = SessionLocal()
    assert db.query(Asset).filter(Asset.workspace_id == w["dst"], Asset.name == "FI33-V-VUG-FR-001").count() == 1
    db.close()
