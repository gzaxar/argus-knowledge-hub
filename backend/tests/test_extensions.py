"""Model extensions (§5.1, §13 S8): an extension enters only with an owner,
a source and a query; the suite runs every declared extension's query on
its fixture."""
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import extensions as ext
from app.db import SessionLocal
from app.ledger import engine
from app.main import app
from app.models.asset import Asset, Relation
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.services import asset_types, causal_model
from tests.test_ledger_transition import token

client = TestClient(app)


# --- every declared extension answers its own question -----------------------------------------------------------------

@pytest.mark.parametrize("extension", ext.declared(), ids=[e.id for e in ext.declared()])
def test_every_declared_extension_passes_the_gate_and_its_query_answers_on_its_fixture(extension):
    assert ext.check(extension) == []
    db = SessionLocal()
    try:
        result = ext.run_fixture(db, extension)
    finally:
        db.close()
    assert result["ok"], result


def test_the_relations_of_declared_extensions_are_classified_for_the_walk():
    for e in ext.declared():
        for r in e.relations:
            assert causal_model.classify(r.name) is not None, r.name


# --- a sample extension, as an owner would write one ------------------------------------------------------------------

def _cables(db, ws):
    """Which cables have no end at a rack: cabling nobody can trace."""
    rows = []
    for cable in db.scalars(select(Asset).where(Asset.workspace_id == ws, Asset.type == "Fanout Cable")):
        ends = set(db.scalars(select(Relation.to_asset_uid).where(Relation.from_asset_uid == cable.uid,
                                                                   Relation.relation_type == "terminates at")))
        if not ends:
            rows.append({"uid": cable.uid, "key": cable.key})
    return rows


def _cable_fixture(db, ws):
    def rec(type_, key):
        a = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=engine.ensure_type(db, ws, type_).uid,
                  key=key, name=key, type=type_, attributes={})
        db.add(a)
        db.flush()
        return a
    rack, traced, loose = rec("Rack", "RACK-B12"), rec("Fanout Cable", "CBL-1"), rec("Fanout Cable", "CBL-2")
    db.add(Relation(workspace_id=ws, from_asset_uid=traced.uid, to_asset_uid=rack.uid, relation_type="terminates at"))
    db.flush()
    return {"loose": loose.uid}


def sample(**changes):
    base = dict(
        id=f"cabling-test-{secrets.token_hex(2)}", trigger="cabling", owner="Controls cabling (test)",
        source="ARGUS, entered by the cabling team", summary="signal cables and where they end",
        types=[ext.ExtType("Fanout Cable", "Asset", "A cable carrying a signal",
                           [("length_m", "Length (m)", "float"),
                            ("kind", "Kind", "enumeration", ["coax", "twisted pair", "fibre"])])],
        relations=[ext.ExtRelation("terminates at", "environment", causal_model.NONE, None,
                                   "cable → where one end lands", source_types={"Fanout Cable"},
                                   at_most_per_source=2)],
        query=ext.ExtQuery("untraced cables", "Which cables have no end at a rack?", _cables, _cable_fixture,
                           lambda rows, ctx: [r["uid"] for r in rows] == [ctx["loose"]]),
    )
    base.update(changes)
    return ext.Extension(**base)


def test_the_gate_wants_an_owner_a_source_and_a_query():
    assert ext.check(sample(), []) == []
    assert "it has no owner" in ext.check(sample(owner=" "), [])
    assert "it has no source" in ext.check(sample(source=""), [])
    assert any("no query" in p for p in ext.check(sample(query=None), []))
    assert any("not one of the triggers" in p for p in ext.check(sample(trigger="lasers"), []))


def test_the_gate_refuses_what_would_break_the_model():
    assert any("exists already" in p for p in ext.check(sample(types=[ext.ExtType("Ion Pump", "Asset", "x")]), []))
    assert any("does not have" in p for p in ext.check(sample(types=[ext.ExtType("Cable", "Wiring", "x")]), []))
    assert any("exists already" in p for p in ext.check(sample(relations=[
        ext.ExtRelation("powers", "power", causal_model.FORWARD, causal_model.FUNCTION, "x")]), []))
    assert any("which way" in p for p in ext.check(sample(relations=[
        ext.ExtRelation("feeds", "power", "sideways", causal_model.FUNCTION, "x")]), []))
    assert any("takes with it" in p for p in ext.check(sample(relations=[
        ext.ExtRelation("feeds", "power", causal_model.FORWARD, None, "x")]), []))
    assert any("unknown type" in p for p in ext.check(sample(relations=[
        ext.ExtRelation("feeds", "power", causal_model.FORWARD, causal_model.FUNCTION, "x",
                        target_types={"Flux Capacitor"})]), []))
    # Two extensions may not both add the same type.
    a, b = sample(), sample()
    assert any("exists already" in p for p in ext.check(b, [a, b]))


def test_a_declared_relation_reaches_the_walk_and_the_registry():
    s = sample(relations=[ext.ExtRelation("energises", "power", causal_model.FORWARD, causal_model.FUNCTION,
                                          "distribution board → load", source_types={"Fanout Cable"},
                                          at_most_per_target=1)])
    assert ext.semantics([s])["energises"].flows == causal_model.FORWARD
    endpoints, cardinality = ext.registry_rules([s])
    assert endpoints["energises"] == (("in", {"Fanout Cable"}), None) and cardinality["energises"] == (None, 1)
    assert ext.semantics([sample(owner="")]) == {}                  # refused by the gate: not in the walk


@pytest.fixture
def catalogue(monkeypatch):
    cat = f"cat-{secrets.token_hex(3)}"
    db = SessionLocal()
    db.add(Workspace(id=cat, name=cat))
    db.flush()
    asset_types.ensure_asset_types(db, cat, scope=asset_types.SCOPE_GLOBAL)
    headers = token(db, cat)
    db.commit()
    db.close()
    good = sample()
    broken = sample(id=f"broken-{secrets.token_hex(2)}", trigger="stores", types=[], relations=[],
                    query=ext.ExtQuery("nothing", "?", lambda db, ws: [], lambda db, ws: {}, lambda rows, ctx: False))
    monkeypatch.setattr(ext, "declared", lambda: [broken, good])
    return {"ws": cat, "headers": headers, "good": good, "broken": broken}


def test_an_extension_is_admitted_into_a_catalogue_as_a_decision(catalogue):
    h, good = catalogue["headers"], catalogue["good"]
    listed = {t["trigger"]: t for t in client.get("/v1/catalogue/extensions?run_fixtures=true", headers=h)
              .json()["triggers"]}
    assert set(listed) == set(ext.TRIGGERS)
    assert listed["safety"]["extensions"] == []                     # waiting for an owner, a source and a query
    item = listed["cabling"]["extensions"][0]
    assert item["problems"] == [] and item["fixture"]["ok"] and item["admitted"] is None

    assert client.post(f"/v1/catalogue/extensions/{good.id}/admit", headers=h, json={"reason": ""}).status_code == 422
    refused = client.post(f"/v1/catalogue/extensions/{catalogue['broken'].id}/admit", headers=h,
                          json={"reason": "try"})
    assert refused.status_code == 422 and "expected answer" in refused.json()["detail"]["error"]
    assert client.get(f"/v1/catalogue/extensions/{good.id}/query", headers=h).status_code == 422   # not admitted

    r = client.post(f"/v1/catalogue/extensions/{good.id}/admit", headers=h, json={"reason": "cabling team owns it"})
    assert r.status_code == 201, r.text
    assert r.json()["types"] == ["Fanout Cable"]
    db = SessionLocal()
    schema = db.query(Schema).filter_by(workspace_id=catalogue["ws"], name="Fanout Cable").one()
    parent = db.get(Schema, schema.parent_schema_uid)
    assert parent.name == "Asset" and schema.is_global and {a["key"] for a in schema.attributes} == {"length_m", "kind"}
    assert db.query(Workspace).filter(Workspace.name.like(f"fixture of {good.id}")).count() == 0   # fixture thrown away
    db.close()
    assert client.post(f"/v1/catalogue/extensions/{good.id}/admit", headers=h,
                       json={"reason": "again"}).status_code == 422
    after = {t["trigger"]: t for t in client.get("/v1/catalogue/extensions", headers=h).json()["triggers"]}
    assert after["cabling"]["extensions"][0]["admitted"]["reason"] == "cabling team owns it"
    q = client.get(f"/v1/catalogue/extensions/{good.id}/query", headers=h)
    assert q.status_code == 200 and q.json()["rows"] == []


def test_only_the_catalogue_admits(catalogue):
    ws = f"bl-{secrets.token_hex(3)}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name=ws))
    db.flush()
    headers = token(db, ws)
    db.commit()
    db.close()
    r = client.post(f"/v1/catalogue/extensions/{catalogue['good'].id}/admit", headers=headers, json={"reason": "x"})
    assert r.status_code == 403
