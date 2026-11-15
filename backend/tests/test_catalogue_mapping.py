"""Imported hardware models mapped into a catalogue as Product Models and Vendors:
rules first, the AI for what rules cannot decide, a person's review, apply
through the ledger with the old key kept as an alias, undo, and skipped rows
that stay open for a later mapping."""
import json
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.asset import Asset
from app.models.asset_subresources import AssetLabel
from app.models.llm_config import LLMConfig
from app.models.schema import Schema
from app.models.user import User
from app.models.workspace import Workspace
from app.services import catalogue_mapping as cm
from app.services.asset_types import ensure_asset_types
from tests.confirm import typed

client = TestClient(app)


@pytest.fixture()
def world():
    t = secrets.token_hex(3)
    src, cat = f"imp-{t}", f"cat-{t}"
    db = SessionLocal()
    db.add_all([Workspace(id=src, name="Imported"), Workspace(id=cat, name="Catalogue")])
    db.flush()
    ensure_asset_types(db, cat)
    admin = User(id=str(uuid.uuid4()), email=f"admin-{t}@argus.test", is_admin=True)
    db.add(admin)
    company = Schema(uid=f"{src}:company", workspace_id=src, name="Company")
    switches = Schema(uid=f"{src}:switch-models", workspace_id=src, name="Switch Models")
    nas = Schema(uid=f"{src}:nas-models", workspace_id=src, name="NAS Models")
    db.add_all([company, switches, nas])
    db.flush()

    def asset(schema, key, name, **attrs):
        uid = str(uuid.uuid4())
        db.add(Asset(uid=uid, workspace_id=src, schema_uid=schema.uid, key=f"{key}-{t}", name=name,
                     type=schema.name, attributes={"key": key, "name": name, **attrs}))
        return uid

    cisco = asset(company, "LNFMAC-1", "CISCO Systems, Inc.")
    qnap = asset(company, "LNFMAC-2", "QNAP")
    dmc = asset(company, "LNFMAC-3", "DMC SISTEMI INTEGRATI SRL")
    uids = {
        "c9500": asset(switches, "LNFMAC-10", "C9500-40X-AC", producer=cisco, product_code="C9500-40X-A"),
        "c9500b": asset(switches, "LNFMAC-11", "Cisco C9500 40X", producer=cisco, product_code="C9500-40X-A"),
        "c4500": asset(switches, "LNFMAC-12", "Cisco Catalyst 4500-E", producer=cisco,
                       documentation="https://cisco.example/4500",
                       description="<div><p>Modular <b>chassis</b> switch</p></div>"),
        "ts653": asset(nas, "LNFMAC-20", "TS-653PRO-8G - NAS SENZA DISCHI", producer=qnap, vendor=dmc, cost="999"),
        "dmc": asset(nas, "LNFMAC-21", "DMC SISTEMI INTEGRATI SRL", vendor=dmc),
    }
    db.commit()
    # The catalogue already knows Cisco, under another spelling.
    vendor_schema = cm.catalogue_types(db, cat)[1]
    db.add(Asset(uid=str(uuid.uuid4()), workspace_id=cat, schema_uid=vendor_schema.uid, key=f"V-CISCO-{t}",
                 name="Cisco", type="Vendor", attributes={}))
    types = [switches.uid, nas.uid]
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    db.close()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
    yield {"src": src, "cat": cat, "t": t, "types": types, "uids": uids}
    # The tests run against a real database: leave no workspaces behind.
    for ws in (cat, src):
        client.delete(f"/v1/workspaces/{ws}", headers=typed(ws))
    app.dependency_overrides.pop(get_identity, None)


def start(w, use_ai=False):
    r = client.post("/v1/catalogue-mappings", json={"source_workspace_id": w["src"], "target_workspace_id": w["cat"],
                                                    "type_uids": w["types"], "use_ai": use_ai})
    assert r.status_code == 201, r.text
    m = client.get(f"/v1/catalogue-mappings/{r.json()['id']}").json()
    assert m["state"] == "ready", m
    return m


def rows(m):
    return {i["source_key"].rsplit("-", 1)[0]: i for i in m["items"]}


def test_rules_propose_vendor_class_datasheet_and_duplicates(world):
    m = start(world)
    r = rows(m)
    c9500 = r["LNFMAC-10"]["proposal"]
    assert c9500["action"] == "create_model"
    assert c9500["vendor"]["name"] == "Cisco" and c9500["vendor"]["existing_uid"]      # matched despite spelling
    assert c9500["fields"]["model_code"]["value"] == "C9500-40X-A"
    assert c9500["fields"]["device_class"]["value"] == "switch"
    dup = r["LNFMAC-11"]["proposal"]
    assert dup["action"] == "merge" and dup["duplicate_of"] == r["LNFMAC-10"]["id"]
    c4500 = r["LNFMAC-12"]["proposal"]
    assert c4500["fields"]["datasheet_url"]["value"] == "https://cisco.example/4500"
    assert c4500["fields"]["description"]["value"] == "Modular chassis switch"
    ts = r["LNFMAC-20"]["proposal"]
    assert ts["vendor"]["name"] == "QNAP" and ts["vendor"]["existing_uid"] is None     # a new vendor
    assert "Sold by: DMC SISTEMI INTEGRATI SRL" in ts["fields"]["description"]["value"]
    assert "cost" not in ts["fields"]["description"]["value"]
    assert any("company" in w for w in r["LNFMAC-21"]["proposal"]["warnings"])


def test_apply_creates_through_the_ledger_keeps_old_keys_and_skipped_rows_stay_open(world):
    w = world
    m = start(w)
    r = rows(m)
    mid = m["id"]
    for k in ("LNFMAC-10", "LNFMAC-11", "LNFMAC-20"):
        assert client.patch(f"/v1/catalogue-mappings/{mid}/items/{r[k]['id']}", json={"status": "accepted"}).status_code == 200
    # A correction accepts the row.
    fix = client.patch(f"/v1/catalogue-mappings/{mid}/items/{r['LNFMAC-12']['id']}",
                       json={"fields": {"name": "Catalyst 4500-E", "model_code": "WS-C4500E"}})
    assert fix.status_code == 200 and fix.json()["status"] == "accepted"
    assert client.patch(f"/v1/catalogue-mappings/{mid}/items/{r['LNFMAC-21']['id']}",
                        json={"status": "skipped"}).status_code == 200

    out = client.post(f"/v1/catalogue-mappings/{mid}/apply").json()
    assert out["applied"] == 4 and out["failed"] == []
    m = client.get(f"/v1/catalogue-mappings/{mid}").json()
    r = rows(m)
    db = SessionLocal()
    model = db.get(Asset, r["LNFMAC-10"]["result_uid"])
    assert model.workspace_id == w["cat"] and model.type == "Product Model"
    assert model.attributes["vendor"] == "Cisco" and model.attributes["model_code"] == "C9500-40X-A"
    assert r["LNFMAC-11"]["result_uid"] == model.uid                                   # merged, not created twice
    labels = {l.value for l in db.query(AssetLabel).filter(AssetLabel.asset_uid == model.uid,
                                                           AssetLabel.type == "former_key")}
    assert labels == {f"LNFMAC-10-{w['t']}", f"LNFMAC-11-{w['t']}"}
    corrected = db.get(Asset, r["LNFMAC-12"]["result_uid"])
    assert corrected.name == "Catalyst 4500-E" and corrected.attributes["model_code"] == "WS-C4500E"
    nas = db.get(Asset, r["LNFMAC-20"]["result_uid"])
    qnap = db.get(Asset, nas.attributes["vendor_ref"])
    assert qnap.type == "Vendor" and qnap.name == "QNAP" and qnap.workspace_id == w["cat"]
    assert db.get(Asset, w["uids"]["ts653"]).workspace_id == w["src"]                   # the source is untouched
    db.close()

    # The skipped row, and only it, is open for the next mapping.
    srcs = {s["name"]: s for s in client.get(f"/v1/catalogue-mappings/sources?workspace_id={w['src']}").json()}
    assert srcs["Switch Models"]["open"] == 0 and srcs["NAS Models"]["open"] == 1
    again = start(w)
    assert [i["source_key"] for i in again["items"]] == [f"LNFMAC-21-{w['t']}"]

    # Undo retires what was created and opens the rows again.
    assert client.post(f"/v1/catalogue-mappings/{mid}/undo").json()["retired"] >= 4
    db = SessionLocal()
    assert db.get(Asset, model.uid).record_status == "Retired"
    assert db.query(AssetLabel).filter(AssetLabel.asset_uid == model.uid, AssetLabel.type == "former_key").count() == 0
    db.close()
    srcs = {s["name"]: s for s in client.get(f"/v1/catalogue-mappings/sources?workspace_id={w['src']}").json()}
    assert srcs["Switch Models"]["open"] == 3


def test_the_ai_cleans_names_and_flags_companies_and_its_claims_are_checked(world, monkeypatch):
    w = world
    db = SessionLocal()
    db.add(LLMConfig(workspace_id=w["cat"], base_url="https://gateway.example/v1", model="m-1", enabled=True,
                     last_check_ok=True))
    db.commit()
    db.close()
    seen = []

    def complete(endpoint, system, user, max_tokens=512, extra=None):
        seen.append(user)
        ids = {}
        for block in user.split("<rows>")[1].split("\n\n"):
            lines = dict(line.split(": ", 1) for line in block.strip().splitlines() if ": " in line)
            ids[lines["name"]] = int(lines["id"])
        out = []
        for name, n in ids.items():
            if name.startswith("TS-653"):
                out.append({"id": n, "kind": "product_model", "name": "TS-653 Pro", "model_code": "TS-653PRO-8G",
                            "manufacturer": "QNAP", "device_class": "NAS",
                            "evidence": {"name": "TS-653PRO", "model_code": "TS-653PRO-8G"},
                            "confidence": {"name": 0.9, "model_code": 0.95}})
            elif name.startswith("DMC"):
                out.append({"id": n, "kind": "vendor", "name": "DMC Sistemi Integrati",
                            "evidence": {"name": "DMC SISTEMI INTEGRATI"}, "confidence": {"name": 0.9}})
            elif name == "Cisco Catalyst 4500-E":
                out.append({"id": n, "kind": "product_model", "name": "Catalyst 4500-E Supervisor",
                            "evidence": {"name": "Catalyst 4500-E Supervisor"}, "confidence": {"name": 0.95}})
        return json.dumps({"rows": out})

    monkeypatch.setattr("app.services.llm.complete", complete)
    m = start(w, use_ai=True)
    assert m["ai"]["used"] and m["ai"]["model"] == "m-1" and m["ai"]["runs"]
    r = rows(m)
    ts = r["LNFMAC-20"]["proposal"]
    assert ts["fields"]["name"] == {"value": "TS-653 Pro", "source": "ai", "confidence": 0.9, "evidence": "TS-653PRO"}
    assert ts["fields"]["model_code"]["value"] == "TS-653PRO-8G" and ts["fields"]["device_class"]["value"] == "nas"
    assert r["LNFMAC-21"]["proposal"]["action"] == "create_vendor"
    guessed = r["LNFMAC-12"]["proposal"]
    assert guessed["vendor"]["name"] == "Cisco"                                          # the producer link stays
    assert not any(x.startswith("No producer") for x in ts["warnings"])
    ungrounded = r["LNFMAC-12"]["proposal"]
    assert ungrounded["fields"]["name"]["confidence"] <= 0.5                          # not in the row: capped
    assert any("could not be found" in x for x in ungrounded["warnings"])
    assert "cost" not in "".join(seen) and "999" not in "".join(seen)


def test_no_usable_ai_falls_back_to_the_rules(world):
    m = start(world, use_ai=True)
    assert m["ai"]["used"] is False and "rules alone" in m["ai"]["reason"]
    assert all(i["proposal"]["fields"]["name"]["source"] == "rule" for i in m["items"])



def test_a_manufacturer_the_row_does_not_name_is_marked_as_a_guess():
    src = {"key": "K", "name": "TS-653PRO-8G - NAS SENZA DISCHI", "type": "NAS Models", "producer": None,
           "producer_uid": None, "producer_key": None, "reseller": None, "reseller_uid": None, "reseller_key": None,
           "product_code": None, "documentation": None, "description": "", "extra": {}}
    proposal = cm.rule_proposal(src, {}, set())
    assert "No producer or vendor recorded." in proposal["warnings"]
    text = cm._row_text(1, src)
    out = cm.merge_ai(proposal, {"id": 1, "kind": "product_model", "manufacturer": "Synology",
                                 "evidence": {"manufacturer": "Synology"}, "confidence": {"manufacturer": 0.9}},
                      text, {}, {})
    assert out["vendor"]["name"] == "Synology" and out["vendor"]["confidence"] == 0.5
    assert not any(w.startswith("No producer") for w in out["warnings"])
    assert any("the AI's guess" in w for w in out["warnings"])
    assert cm.confidence(out) <= 0.5                                                  # never accepted in bulk


def test_attachments_avatar_history_comments_and_tickets_come_along_and_undo_removes_them(world, tmp_path,
                                                                                            monkeypatch):
    import hashlib
    import os
    from datetime import datetime, timezone

    from app.models.asset_subresources import AssetComment, AssetHistory, AssetTicket
    from app.models.attachment import Attachment
    from app.models.issue import Issue
    from app.models.ledger import TicketLink
    monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path))
    w = world
    src_uid = w["uids"]["c4500"]
    when = datetime(2023, 5, 16, 16, 56, tzinfo=timezone.utc)
    db = SessionLocal()
    files = {}
    for name, body in (("LNFMAC-12-avatar.png", b"\x89PNG picture"), ("datasheet.pdf", b"%PDF-1.7 the datasheet")):
        uid = str(uuid.uuid4())
        path = tmp_path / f"src-{uid}"
        path.write_bytes(body)
        db.add(Attachment(uid=uid, workspace_id=w["src"], asset_uid=src_uid, filename=name, file_size=len(body),
                          sha256=hashlib.sha256(body).hexdigest(), author="jira.user", storage_path=str(path),
                          created_at=when, updated_at=when))
        files[name] = uid
    db.flush()
    db.get(Asset, src_uid).avatar_icon_uid = files["LNFMAC-12-avatar.png"]
    db.add(AssetHistory(uid=str(uuid.uuid4()), asset_uid=src_uid, type="1", author="a.rossi",
                        details="Object created", timestamp=when, backend_id="h-1"))
    db.add(AssetComment(uid=str(uuid.uuid4()), asset_uid=src_uid, author="b.bianchi", text="Supervisor replaced",
                        created=when, updated=when))
    db.add(AssetTicket(uid=str(uuid.uuid4()), asset_uid=src_uid, ticket_key="NET-42", summary="Port flapping",
                       type="Incident", status="Done", created=when, updated=when))
    ticket = Issue(uid=str(uuid.uuid4()), workspace_id=w["src"], asset_uid=src_uid, title="Switch down",
                   state="resolved")
    db.add(ticket)
    db.add(AssetLabel(uid=str(uuid.uuid4()), asset_uid=src_uid, type="qrcode",
                      value="https://servicedesk.example/secure/ShowObject.jspa?id=12", namespace=None,
                      issuer="import", verified=True, created_at=when, updated_at=when))
    db.commit()
    ticket_uid = ticket.uid
    db.close()

    m = start(w)
    row = rows(m)["LNFMAC-12"]
    assert row["source"]["carry"] == {"avatar": True, "attachments": 1, "history": 1, "comments": 1, "tickets": 2}
    client.patch(f"/v1/catalogue-mappings/{m['id']}/items/{row['id']}", json={"status": "accepted"})
    out = client.post(f"/v1/catalogue-mappings/{m['id']}/apply").json()
    assert out["applied"] == 1 and out["carried"]["attachments"] == 2 and out["carried"]["avatar"] == 1

    db = SessionLocal()
    target_uid = rows(client.get(f"/v1/catalogue-mappings/{m['id']}").json())["LNFMAC-12"]["result_uid"]
    target = db.get(Asset, target_uid)
    copied = {a.filename: a for a in db.query(Attachment).filter(Attachment.asset_uid == target_uid)}
    assert set(copied) == {"LNFMAC-12-avatar.png", "datasheet.pdf"}
    pdf = copied["datasheet.pdf"]
    assert pdf.uid != files["datasheet.pdf"] and pdf.workspace_id == w["cat"]              # a copy, in the catalogue
    assert open(pdf.storage_path, "rb").read() == b"%PDF-1.7 the datasheet" and pdf.author == "jira.user"
    assert pdf.created_at == when
    assert target.avatar_icon_uid == copied["LNFMAC-12-avatar.png"].uid
    history = {h.type: h for h in db.query(AssetHistory).filter(AssetHistory.asset_uid == target_uid)}
    assert history["1"].author == "a.rossi" and history["1"].timestamp == when
    assert history["1"].details.startswith("[LNFMAC-12-") and "mapped" in history
    comment = db.query(AssetComment).filter(AssetComment.asset_uid == target_uid).one()
    assert comment.author == "b.bianchi" and comment.text.endswith("Supervisor replaced")
    assert db.query(AssetTicket).filter(AssetTicket.asset_uid == target_uid).one().ticket_key == "NET-42"
    link = db.query(TicketLink).filter(TicketLink.asset_uid == target_uid).one()
    assert link.ticket_uid == ticket_uid and link.role == "related"
    assert db.get(Issue, ticket_uid).workspace_id == w["src"]                               # the ticket stays
    assert db.query(AssetLabel).filter(AssetLabel.asset_uid == target_uid, AssetLabel.type == "alias",
                                       AssetLabel.value.like("%ShowObject.jspa?id=12")).count() == 1
    # The source keeps everything.
    assert db.query(Attachment).filter(Attachment.asset_uid == src_uid).count() == 2
    assert os.path.exists(db.get(Attachment, files["datasheet.pdf"]).storage_path)
    paths = [a.storage_path for a in copied.values()]
    db.close()

    client.post(f"/v1/catalogue-mappings/{m['id']}/undo")
    db = SessionLocal()
    assert db.query(Attachment).filter(Attachment.asset_uid == target_uid).count() == 0
    assert not any(os.path.exists(p) for p in paths)
    assert db.query(AssetHistory).filter(AssetHistory.asset_uid == target_uid).count() == 0
    assert db.query(AssetComment).filter(AssetComment.asset_uid == target_uid).count() == 0
    assert db.query(TicketLink).filter(TicketLink.asset_uid == target_uid).count() == 0
    assert db.get(Asset, target_uid).avatar_icon_uid is None
    assert os.path.exists(db.get(Attachment, files["datasheet.pdf"]).storage_path)         # the source's file stays
    db.close()


def test_rows_applied_before_anything_came_along_can_bring_it_later(world):
    from app.models.asset_subresources import AssetHistory
    from app.models.catalogue_mapping import CatalogueMappingItem
    w = world
    db = SessionLocal()
    db.add(AssetHistory(uid=str(uuid.uuid4()), asset_uid=w["uids"]["c9500"], type="1", author="a.rossi",
                        details="Object created", timestamp=cm.now()))
    db.commit()
    db.close()
    m = start(w)
    row = rows(m)["LNFMAC-10"]
    client.patch(f"/v1/catalogue-mappings/{m['id']}/items/{row['id']}", json={"status": "accepted"})
    client.post(f"/v1/catalogue-mappings/{m['id']}/apply")
    db = SessionLocal()
    item = db.get(CatalogueMappingItem, row["id"])
    target = item.result_uid
    cm.uncarry(db, item.carried)                       # as if applied by the earlier version
    item.carried = {}
    db.commit()
    db.close()
    assert client.get(f"/v1/catalogue-mappings/{m['id']}").json()["pending_carry"] == 1
    out = client.post(f"/v1/catalogue-mappings/{m['id']}/carry").json()
    assert out["rows"] == 1 and out["failed"] == []
    assert client.post(f"/v1/catalogue-mappings/{m['id']}/carry").json()["rows"] == 0     # once only
    db = SessionLocal()
    assert db.query(AssetHistory).filter(AssetHistory.asset_uid == target, AssetHistory.type == "1").count() == 1
    db.close()
