"""Sites (docs/sites.md, app/services/sites.py): a laboratory's places shared with the facilities at it, and
nothing else of the laboratory or of another facility; the relationship validated; withholding a place and what
is inside it."""
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.asset import Asset
from app.models.user import User
from app.models.workspace import Workspace
from app.services import asset_types, indoor, sites
from app.services.attribute_validation import _is_reference_visible
from app.services.visibility import asset_visible_in, visible_assets_clause


def make(db, ws, type_name, name, **attrs) -> Asset:
    a = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=asset_types.type_uid(ws, type_name),
              key=f"{ws.upper()}-{uuid.uuid4().hex[:6]}", name=name, type=type_name, attributes=attrs)
    db.add(a)
    db.flush()
    return a


@pytest.fixture()
def lab():
    t = secrets.token_hex(3)
    ids = {k: f"{k}-{t}" for k in ("lnf", "sparc", "btf", "other")}
    db = SessionLocal()
    for w in ids.values():
        db.add(Workspace(id=w, name=w))
    db.flush()
    for w in ids.values():
        asset_types.ensure_asset_types(db, w)
    admin = User(id=str(uuid.uuid4()), email=f"admin-{t}@argus.test", is_admin=True)
    db.add(admin)
    db.commit()
    sites.set_role(db, ids["lnf"], True)
    for f in ("sparc", "btf"):
        sites.set_site(db, ids[f], ids["lnf"])
    rec = {"building": make(db, ids["lnf"], "Building", "Edificio 2"),
           "hall": make(db, ids["lnf"], "Area", "Hall 3"),
           "lnf_pump": make(db, ids["lnf"], "Vacuum Pump", "LNF's own pump"),
           "sparc_pump": make(db, ids["sparc"], "Vacuum Pump", "SPARC pump"),
           "btf_pump": make(db, ids["btf"], "Vacuum Pump", "BTF pump")}
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    yield {"db": db, "ids": ids, "rec": rec, "admin": admin}
    db.rollback()
    from app.ledger.audit import allow_purge
    for f in ("sparc", "btf"):
        db.get(Workspace, ids[f]).site_id = None
    db.commit()
    allow_purge(db)
    for w in ("sparc", "btf", "other", "lnf"):
        db.delete(db.get(Workspace, ids[w]))
    db.delete(db.get(User, admin.id))
    db.commit()
    db.close()


def seen_from(db, ws) -> set[str]:
    return set(db.scalars(select(Asset.uid).where(visible_assets_clause(ws))))


def test_facilities_see_the_sites_places_and_nothing_else_of_it_or_of_each_other(lab):
    db, ids, r = lab["db"], lab["ids"], lab["rec"]
    assert r["building"].site_shared and r["hall"].site_shared
    assert not r["lnf_pump"].site_shared                       # not a place: the site's own
    sparc = seen_from(db, ids["sparc"])
    assert {r["building"].uid, r["hall"].uid, r["sparc_pump"].uid} <= sparc
    assert r["lnf_pump"].uid not in sparc and r["btf_pump"].uid not in sparc
    btf = seen_from(db, ids["btf"])
    assert r["building"].uid in btf and r["sparc_pump"].uid not in btf
    other = seen_from(db, ids["other"])
    assert r["building"].uid not in other                     # not at the site: not shared, not global
    assert asset_visible_in(r["building"], ids["sparc"]) and not asset_visible_in(r["building"], ids["other"])
    assert _is_reference_visible(db, r["hall"], ids["btf"]) and not _is_reference_visible(db, r["lnf_pump"], ids["btf"])


def test_the_asset_list_of_a_facility_includes_the_sites_places(lab):
    db, ids, r = lab["db"], lab["ids"], lab["rec"]
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=lab["admin"])
    try:
        listed = {a["uid"] for a in TestClient(app).get("/v1/assets", headers={"X-Workspace-Id": ids["sparc"]}).json()}
    finally:
        app.dependency_overrides.pop(get_identity, None)
    assert r["building"].uid in listed and r["btf_pump"].uid not in listed and r["lnf_pump"].uid not in listed


def test_the_relationship_is_validated(lab):
    db, ids = lab["db"], lab["ids"]
    with pytest.raises(sites.SiteProblem, match="not a site"):
        sites.set_site(db, ids["other"], ids["sparc"])
    with pytest.raises(sites.SiteProblem, match="not at itself"):
        sites.set_site(db, ids["lnf"], ids["lnf"])
    with pytest.raises(sites.SiteProblem, match="a site is at no site"):
        sites.set_role(db, ids["sparc"], True)                # SPARC is at LNF: it cannot become a site
    sites.set_role(db, ids["other"], True)
    with pytest.raises(sites.SiteProblem, match="a site is at no site"):
        sites.set_site(db, ids["other"], ids["lnf"])          # a site cannot be at a site
    with pytest.raises(sites.SiteProblem, match="has facilities"):
        sites.set_role(db, ids["lnf"], False)
    db.rollback()


def test_the_catalogue_is_neither_a_site_nor_at_one(lab, monkeypatch):
    from app.catalogue import install
    from app.catalogue.system import ROLE
    db, ids = lab["db"], lab["ids"]
    ws = db.get(Workspace, ids["other"])
    ws.role = ROLE        # treated as the catalogue for this test only: never written (one catalogue per installation)
    with pytest.raises(sites.SiteProblem, match="catalogue"):
        sites.set_role(db, ids["other"], True)
    with pytest.raises(sites.SiteProblem, match="catalogue"):
        sites.set_site(db, ids["other"], ids["lnf"])
    db.rollback()


def test_a_withheld_place_and_everything_inside_it_stop_being_shared(lab):
    db, ids, r = lab["db"], lab["ids"], lab["rec"]
    room = make(db, ids["lnf"], "Area", "Room 12")
    indoor.place(db, room, place_uid=r["hall"].uid, actor="t")      # Room 12 in Hall 3
    indoor.place(db, r["hall"], place_uid=r["building"].uid, actor="t")   # Hall 3 in Edificio 2
    db.commit()
    assert room.site_shared
    r["building"].site_withheld = True
    sites.refresh(db, ids["lnf"])
    db.commit()
    db.expire_all()
    sparc = seen_from(db, ids["sparc"])
    assert not ({r["building"].uid, r["hall"].uid, room.uid} & sparc)
    assert sites.inside(db, r["building"].uid) == [r["building"].uid, r["hall"].uid, room.uid]
    r["building"].site_withheld = False
    sites.refresh(db, ids["lnf"])
    db.commit()
    assert {r["building"].uid, r["hall"].uid, room.uid} <= seen_from(db, ids["sparc"])


def test_administrators_set_sites_through_the_api(lab):
    db, ids = lab["db"], lab["ids"]
    plain = User(id=str(uuid.uuid4()), email=f"u-{secrets.token_hex(3)}@argus.test", is_admin=False)
    db.add(plain)
    db.commit()
    db.refresh(plain)
    db.expunge(plain)
    client = TestClient(app)
    try:
        app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=plain)
        assert client.get("/v1/admin/sites").status_code == 403
        app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=lab["admin"])
        [lnf] = [s for s in client.get("/v1/admin/sites").json() if s["id"] == ids["lnf"]]
        assert set(lnf["facilities"]) == {ids["sparc"], ids["btf"]} and lnf["shared_places"] == 2
        r = client.put(f"/v1/admin/sites/{ids['other']}/site", json={"site_id": ids["sparc"]})
        assert r.status_code == 422 and "not a site" in r.json()["detail"]["error"]
        assert client.put(f"/v1/admin/sites/{ids['other']}/site", json={"site_id": ids["lnf"]}).status_code == 200
        me = {w["id"]: w for w in client.get("/v1/me/workspaces").json()}
        assert me[ids["other"]]["site_id"] == ids["lnf"] and me[ids["lnf"]]["role"] == "site"
    finally:
        app.dependency_overrides.pop(get_identity, None)
        db.get(Workspace, ids["other"]).site_id = None
        db.delete(db.get(User, plain.id))
        db.commit()
