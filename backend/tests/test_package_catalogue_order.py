"""A workspace hanging from a shared catalogue is upgraded after its catalogue: the installer names what the
catalogue lacks instead of failing on a missing type, and a catalogue keeps installing its packages as shared."""
import secrets

import pytest

from app.db import SessionLocal
from app.models.workspace import Workspace
from app.packages import install as installer


@pytest.fixture()
def pair():
    t = secrets.token_hex(3)
    cat, ws = f"cat-{t}", f"line-{t}"
    db = SessionLocal()
    for w in (cat, ws):
        db.add(Workspace(id=w, name=w))
    db.flush()
    installer.install(db, cat, ["core-facility", "core-objects"], scope="global", actor="test")
    installer.install(db, ws, ["core-facility", "core-objects"], catalogue_workspace_id=cat, actor="test")
    db.commit()
    yield db, cat, ws
    db.rollback()
    from app.ledger.audit import allow_purge
    for w in (ws, cat):
        allow_purge(db)
        row = db.get(Workspace, w)
        if row is not None:
            db.delete(row)
        db.commit()
    db.close()


def test_a_workspace_is_told_what_its_catalogue_lacks(pair):
    db, cat, ws = pair
    with pytest.raises(installer.CatalogueBehind) as e:
        installer.plan(db, ws, ["it"])
    db.rollback()
    assert e.value.catalogue == cat
    needs = {n["package_id"]: n for n in e.value.needs}
    assert "it" in needs and needs["it"]["has"] is None and needs["it"]["shared_types"] > 0
    assert "core-records" in needs                       # what `it` stands on, too
    assert cat in str(e.value)


def test_the_catalogue_keeps_installing_as_the_shared_catalogue(pair):
    db, cat, ws = pair
    plan = installer.plan(db, cat, ["it"])
    db.rollback()
    assert plan.options == {"scope": "global"}
    assert {s.package_id for s in plan.steps if s.action == "install"} >= {"it", "core-records"}


def test_once_the_catalogue_has_it_the_workspace_can(pair):
    db, cat, ws = pair
    installer.install(db, cat, ["it"], actor="test")
    db.flush()
    plan = installer.plan(db, ws, ["it"])
    assert plan.options["catalogue_workspace_id"] == cat
    assert any(s.package_id == "it" and s.action == "install" for s in plan.steps)
    db.rollback()


def test_the_api_returns_the_catalogue_and_what_it_needs(pair, monkeypatch):
    from fastapi.testclient import TestClient
    from app.auth import OidcIdentity, get_identity
    from app.main import app
    from app.models.user import User
    db, cat, ws = pair
    admin = User(id="admin-catalogue-order", email="admin-co@argus.test", is_admin=True)
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
    try:
        r = TestClient(app).post(f"/v1/workspaces/{ws}/packages/preview", json={"packages": ["it"]})
    finally:
        app.dependency_overrides.pop(get_identity, None)
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["code"] == "catalogue_behind" and d["catalogue_workspace_id"] == cat
    assert any(n["package_id"] == "it" for n in d["needs"])
