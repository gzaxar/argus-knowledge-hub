"""GLPI's installed devices matched to catalogue models through review (app/catalogue/glpi.py): exact and near
matches proposed — never set by themselves — accepted by a person and kept on the next run, a unit whose
model someone set left alone, ambiguity reported rather than guessed, and the unmatched listed."""
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import OidcIdentity, get_identity
from app.catalogue import glpi
from app.db import SessionLocal
from app.ledger import engine
from app.ledger import service as ledger
from app.ledger.identity import add_label
from app.main import app
from app.models.asset import Asset
from app.models.ledger import Claim, FactState
from app.models.schema import Schema
from app.models.user import User
from app.models.workspace import Workspace
from app.services import asset_keys
from app.services import catalogue_mapping as cm
from app.services.asset_types import ensure_asset_types


@pytest.fixture()
def w():
    t = secrets.token_hex(3)
    cat, it = f"cat-{t}", f"it-{t}"
    db = SessionLocal()
    db.add_all([Workspace(id=cat, name="Catalogue"), Workspace(id=it, name="IT")])
    db.flush()
    ensure_asset_types(db, cat)
    ensure_asset_types(db, it)
    admin = User(id=str(uuid.uuid4()), email=f"admin-{t}@argus.test", is_admin=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    model_schema, vendor_schema = cm.catalogue_types(db, cat)
    unit_type = db.scalar(select(Schema).where(Schema.workspace_id == it, Schema.applies_to == "objects",
                                               Schema.name.notin_(("Product Model", "Vendor"))).limit(1))
    w = {"db": db, "cat": cat, "it": it, "actor": admin.id, "model": model_schema, "vendor": vendor_schema,
         "unit_type": unit_type, "admin": admin}
    yield w
    db.rollback()
    db.close()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
    for ws in (it, cat):
        TestClient(app).delete(f"/v1/workspaces/{ws}")
    app.dependency_overrides.pop(get_identity, None)


def record(w, schema, name, **attrs) -> Asset:
    uid = str(uuid.uuid4())
    ledger.create_record(w["db"], w["cat"], w["actor"], uid=uid, schema_uid=schema.uid,
                         key=asset_keys.allocate(w["db"], w["cat"], schema), name=name, type_name=schema.name,
                         attributes=attrs, is_global=True)
    w["db"].commit()
    return w["db"].get(Asset, uid)


def unit(w, manufacturer, model, **attrs) -> Asset:
    a = Asset(uid=str(uuid.uuid4()), workspace_id=w["it"], schema_uid=w["unit_type"].uid,
              key=f"IT-{uuid.uuid4().hex[:8]}", name=f"{manufacturer} {model}", type=w["unit_type"].name,
              attributes={"argus_source": "GLPI", "manufacturer": manufacturer, "model": model, **attrs})
    w["db"].add(a)
    w["db"].commit()
    return a


def proposals(w) -> dict:
    """unit uid -> (proposed model uid, claim id), for the proposals waiting in review."""
    out = {}
    for c in w["db"].scalars(select(Claim).where(Claim.stream_id == f"catalogue-match:{w['it']}")):
        uid = c.source_ref[4:]
        f = w["db"].scalar(select(FactState).where(FactState.subject_uid == uid,
                                                   FactState.predicate == "attr:product_model",
                                                   FactState.contributor == f"claim:{c.claim_id}"))
        out[uid] = (c.value, c.claim_id, f.status if f else None)
    return out


def test_matches_are_proposed_for_review_accepted_and_kept(w):
    moxa = record(w, w["vendor"], "Moxa")
    add_label(w["db"], moxa.uid, "alias", "MOXA Technologies", "catalogue")
    w["db"].commit()
    nport = record(w, w["model"], "Moxa NPort 5450", vendor="Moxa", vendor_ref=moxa.uid, model_code="NPort 5450")
    exact = unit(w, "MOXA Technologies", "NPORT-5450")                       # alias, and the code's spelling
    near = unit(w, "Moxa", "NPort 5450 serial device server")                # the code inside GLPI's text
    other = unit(w, "Acme", "Thing 9")
    other2 = unit(w, "Acme", "Thing 9")
    mine = unit(w, "Moxa", "NPort 5450", product_model="someone-elses-choice")

    out = glpi.match(w["db"], w["it"], w["cat"])
    w["db"].commit()
    assert (out["proposals"], out["exact"], out["near"]) == (2, 1, 1)
    assert out["unmatched"] == [{"manufacturer": "Acme", "model": "Thing 9", "units": 2}]
    found = proposals(w)
    assert set(found) == {exact.uid, near.uid}                               # not over someone's choice
    assert found[exact.uid][0] == nport.uid and found[exact.uid][2] == "proposed"
    w["db"].expire_all()
    assert "product_model" not in w["db"].get(Asset, exact.uid).attributes   # nothing set by itself
    from app.intake.proposals import evidence_of
    ev = evidence_of(w["db"], found[near.uid][1])
    assert ev["evidence"]["match"] == "near" and ev["confidence"] == 0.8
    assert ev["evidence"]["glpi_model"] == "NPort 5450 serial device server"

    # A person accepts the exact one; the next run states it again, so it is never withdrawn.
    engine.apply_decisions(w["db"], w["it"], w["actor"], [{"kind": "accept", "target": {"claim_id": found[exact.uid][1]}}])
    w["db"].commit()
    w["db"].expire_all()
    assert w["db"].get(Asset, exact.uid).attributes["product_model"] == nport.uid
    again = glpi.match(w["db"], w["it"], w["cat"])
    w["db"].commit()
    w["db"].expire_all()
    assert again["status"] == "unchanged"
    assert w["db"].get(Asset, exact.uid).attributes["product_model"] == nport.uid
    assert w["db"].get(Asset, mine.uid).attributes["product_model"] == "someone-elses-choice"
    assert glpi.unmatched(w["db"], w["it"], w["cat"]) == [{"manufacturer": "Acme", "model": "Thing 9", "units": 2}]
    assert other.uid not in found and other2.uid not in found


def test_two_equally_good_models_are_reported_not_guessed(w):
    v = record(w, w["vendor"], "Cisco")
    a = record(w, w["model"], "Catalyst C9200-24T (a)", vendor="Cisco", vendor_ref=v.uid, model_code="C9200-24T")
    b = record(w, w["model"], "Catalyst C9200-24T (b)", vendor="Cisco", vendor_ref=v.uid, model_code="C9200 24T")
    u = unit(w, "Cisco Systems", "C9200-24T")                                # "Systems" is a legal-name word
    out = glpi.match(w["db"], w["it"], w["cat"])
    w["db"].commit()
    assert out["proposals"] == 0 and out["ambiguous"][0]["model"] == "C9200-24T"
    assert set(out["ambiguous"][0]["candidates"]) == {a.name, b.name} and u.uid not in proposals(w)


def test_the_api_runs_the_match_and_the_review_queue_shows_it(w, monkeypatch):
    from app.catalogue import install as inst
    monkeypatch.setattr(inst, "catalogue_workspace", lambda db: w["cat"])
    v = record(w, w["vendor"], "Moxa")
    model = record(w, w["model"], "Moxa NPort 5450", vendor="Moxa", vendor_ref=v.uid, model_code="NPort 5450")
    u = unit(w, "Moxa", "NPort 5450")
    client = TestClient(app)
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=w["admin"])
    try:
        r = client.post("/v1/catalogue/glpi-matches", headers={"X-Workspace-Id": w["it"]})
        assert r.status_code == 200, r.text
        assert r.json()["proposals"] == 1
        queue = client.get("/v1/ledger/review", headers={"X-Workspace-Id": w["it"]}).json()
        item = next(p for p in queue["proposals"] if p["record"]["uid"] == u.uid)
        assert item["value"] == model.uid and item["match"]["catalogue_id"] is None
        assert item["match"]["model_name"] == "Moxa NPort 5450" and item["match"]["match"] == "exact"
    finally:
        app.dependency_overrides.pop(get_identity, None)


def test_a_rejected_match_does_not_come_back(w):
    v = record(w, w["vendor"], "Moxa")
    record(w, w["model"], "Moxa NPort 5450", vendor="Moxa", vendor_ref=v.uid, model_code="NPort 5450")
    u = unit(w, "Moxa", "NPort 5450")
    glpi.match(w["db"], w["it"], w["cat"])
    w["db"].commit()
    _, claim_id, status = proposals(w)[u.uid]
    assert status == "proposed"
    engine.apply_decisions(w["db"], w["it"], w["actor"],
                           [{"kind": "reject", "target": {"claim_id": claim_id, "scope": "fingerprint"}}])
    w["db"].commit()
    glpi.match(w["db"], w["it"], w["cat"])
    w["db"].commit()
    w["db"].expire_all()
    assert proposals(w)[u.uid][2] == "rejected"                               # stated again, still rejected
    assert "product_model" not in w["db"].get(Asset, u.uid).attributes


def test_the_same_proposals_in_another_order_are_unchanged(w, monkeypatch):
    v = record(w, w["vendor"], "Moxa")
    record(w, w["model"], "Moxa NPort 5450", vendor="Moxa", vendor_ref=v.uid, model_code="NPort 5450")
    record(w, w["model"], "Moxa NPort 5410", vendor="Moxa", vendor_ref=v.uid, model_code="NPort 5410")
    unit(w, "Moxa", "NPort 5450")
    unit(w, "Moxa", "NPort 5410")
    unit(w, "Moxa", "NPort 5450")
    assert glpi.match(w["db"], w["it"], w["cat"])["status"] == "ran"
    w["db"].commit()
    ordered = glpi.units_to_match
    monkeypatch.setattr(glpi, "units_to_match", lambda db, ws: list(reversed(ordered(db, ws))))
    assert glpi.match(w["db"], w["it"], w["cat"])["status"] == "unchanged"
