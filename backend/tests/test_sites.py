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


# --------------------------------------------------------------------------- S2: indoors across workspaces

def _png(w=100, h=80) -> bytes:
    import io

    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(out, "PNG")
    return out.getvalue()


def _person(db, *grants) -> User:
    """A person with these (workspace, role) grants and nothing else."""
    from datetime import datetime, timezone

    from app.models.role import RoleBinding
    from app.services.roles import ensure_system_roles
    ensure_system_roles(db)
    u = User(id=str(uuid.uuid4()), email=f"p-{secrets.token_hex(3)}@argus.test", is_admin=False)
    db.add(u)
    db.flush()
    for ws, role in grants:
        db.add(RoleBinding(workspace_id=ws, subject_type="user", subject_id=u.id, role_id=role,
                           created_at=datetime.now(timezone.utc)))
    db.commit()
    db.refresh(u)
    db.expunge(u)
    return u


class _As:
    """A client signed in as one person on every request (the identity override is shared, so it is set again
    before each call rather than once)."""

    def __init__(self, user):
        self.user, self.client = user, TestClient(app)

    def __getattr__(self, method):
        call = getattr(self.client, method)

        def signed_in(*a, **k):
            app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=self.user)
            return call(*a, **k)
        return signed_in


def _as(user):
    return _As(user)


@pytest.fixture()
def plan(lab):
    """LNF's Edificio 2 with a ground floor and its plan (placed on the map); Hall 3 inside it; a SPARC and a
    BTF person; a person who reads both; and an outsider."""
    db, ids, r = lab["db"], lab["ids"], lab["rec"]
    indoor.place(db, r["hall"], place_uid=r["building"].uid, actor="t")
    level = indoor.save_level(db, r["building"], name="Ground floor", ordinal=0, actor="t")
    p = indoor.add_plan(db, r["building"], "ground.png", _png(), name="Ground floor", level=level, actor="t")
    indoor.georeference(db, p, [{"x": 0, "y": 0, "longitude": 12.6800, "latitude": 41.8200},
                                {"x": 100, "y": 80, "longitude": 12.6810, "latitude": 41.8195}])
    db.commit()
    people = {"sparc": _person(db, (ids["sparc"], "contributor")), "btf": _person(db, (ids["btf"], "contributor")),
              "both": _person(db, (ids["sparc"], "viewer"), (ids["btf"], "viewer")),
              "other": _person(db, (ids["other"], "contributor"))}
    yield {**lab, "plan": p, "level": level, "people": people}
    app.dependency_overrides.pop(get_identity, None)
    for u in people.values():
        db.delete(db.get(User, u.id))
    db.commit()


def _place_on(client, ws, record, plan_uid, place_uid, x, y):
    return client.put(f"/v1/assets/{record}/indoors", headers={"X-Workspace-Id": ws},
                      json={"place_uid": place_uid, "plan_uid": plan_uid, "x": x, "y": y})


def test_sparc_and_btf_share_one_lnf_plan_without_seeing_each_others_equipment(plan):
    db, ids, r, people, p = plan["db"], plan["ids"], plan["rec"], plan["people"], plan["plan"]
    sparc = _as(people["sparc"])
    assert _place_on(sparc, ids["sparc"], r["sparc_pump"].uid, p.uid, r["hall"].uid, 10, 10).status_code == 200
    btf = _as(people["btf"])
    assert _place_on(btf, ids["btf"], r["btf_pump"].uid, p.uid, r["hall"].uid, 20, 20).status_code == 200
    secret = make(db, ids["sparc"], "Vacuum Pump", "SPARC costed pump", classification="restricted:costs")
    indoor.place(db, secret, place_uid=r["hall"].uid, plan_uid=p.uid, x=30, y=30, actor="t")
    indoor.place(db, r["lnf_pump"], place_uid=r["hall"].uid, plan_uid=p.uid, x=40, y=40, actor="t")
    db.commit()

    def seen(user, ws):
        got = _as(user).get(f"/v1/plans/{p.uid}", headers={"X-Workspace-Id": ws})
        assert got.status_code == 200, got.text
        return {x["name"] for x in got.json()["placed"]}
    assert seen(people["sparc"], ids["sparc"]) == {"SPARC pump"}           # not BTF's, not restricted, not LNF's
    assert seen(people["btf"], ids["btf"]) == {"BTF pump"}
    assert seen(people["both"], ids["sparc"]) == {"SPARC pump", "BTF pump"}  # may read both: sees both
    assert seen(lab_admin(plan), ids["sparc"]) == {"SPARC pump", "BTF pump", "SPARC costed pump", "LNF's own pump"}

    # The facility reads the site's floor, plan and image; the record's containers and the hall's contents.
    assert sparc.get(f"/v1/assets/{r['building'].uid}/levels", headers={"X-Workspace-Id": ids["sparc"]}).json()["plans"][0]["uid"] == p.uid
    assert sparc.get(f"/v1/plans/{p.uid}/image", headers={"X-Workspace-Id": ids["sparc"]}).status_code == 200
    where = sparc.get(f"/v1/assets/{r['sparc_pump'].uid}/indoors", headers={"X-Workspace-Id": ids["sparc"]}).json()
    assert [c["name"] for c in where["in"]] == ["Hall 3", "Edificio 2"]
    hall = sparc.get(f"/v1/assets/{r['hall'].uid}/indoors", headers={"X-Workspace-Id": ids["sparc"]}).json()
    assert {c["name"] for c in hall["contents"]} == {"SPARC pump"}
    # On the map: the site's plan, in view from the facility, not from an outsider.
    box = "12.67,41.81,12.69,41.83"
    assert [x["uid"] for x in sparc.get(f"/v1/map/plans?bbox={box}", headers={"X-Workspace-Id": ids["sparc"]}).json()] == [p.uid]
    outsider = _as(people["other"])
    assert outsider.get(f"/v1/map/plans?bbox={box}", headers={"X-Workspace-Id": ids["other"]}).json() == []


def lab_admin(plan):
    return plan["admin"]


def test_only_the_site_changes_its_places_floors_and_plans(plan):
    ids, r, people, p, level = plan["ids"], plan["rec"], plan["people"], plan["plan"], plan["level"]
    sparc, h = _as(people["sparc"]), {"X-Workspace-Id": ids["sparc"]}
    assert sparc.patch(f"/v1/plans/{p.uid}", headers=h, json={"name": "mine"}).status_code == 404
    assert sparc.put(f"/v1/plans/{p.uid}/placement", headers=h, json={"points": [
        {"x": 0, "y": 0, "longitude": 1, "latitude": 1}, {"x": 9, "y": 9, "longitude": 2, "latitude": 2}]}).status_code == 404
    assert sparc.delete(f"/v1/plans/{p.uid}", headers=h).status_code == 404
    assert sparc.patch(f"/v1/levels/{level.uid}", headers=h, json={"name": "x"}).status_code == 404
    assert sparc.post(f"/v1/assets/{r['building'].uid}/levels", headers=h, json={"name": "Roof"}).status_code == 403
    assert sparc.put(f"/v1/assets/{r['building'].uid}", headers=h,
                     json={"name": "renamed", "attributes": {}, "schema_uid": r["building"].schema_uid}).status_code == 404
    # A workspace not at the site neither sees the plan nor places on it.
    outsider, ho = _as(people["other"]), {"X-Workspace-Id": ids["other"]}
    assert outsider.get(f"/v1/plans/{p.uid}", headers=ho).status_code == 404
    mine = make(plan["db"], ids["other"], "Vacuum Pump", "Outsider pump")
    plan["db"].commit()
    assert _place_on(outsider, ids["other"], mine.uid, p.uid, r["hall"].uid, 5, 5).status_code == 404


def test_withholding_a_building_previews_then_ends_facility_placements(plan):
    from app.models.indoor import IndoorPlacement
    from app.services import spatial
    db, ids, r, people, p = plan["db"], plan["ids"], plan["rec"], plan["people"], plan["plan"]
    sparc = _as(people["sparc"])
    _place_on(sparc, ids["sparc"], r["sparc_pump"].uid, p.uid, r["hall"].uid, 10, 10)
    _place_on(_as(people["btf"]), ids["btf"], r["btf_pump"].uid, p.uid, r["hall"].uid, 20, 20)
    indoor.place(db, r["lnf_pump"], place_uid=r["hall"].uid, actor="t")
    db.commit()
    admin, hl = _as(plan["admin"]), {"X-Workspace-Id": ids["lnf"]}
    preview = admin.put(f"/v1/assets/{r['building'].uid}/site-sharing", headers=hl, json={"shared": False}).json()
    assert preview["preview"] and preview["would_withhold"] == 2                    # the building and its hall
    assert {(x["workspace_id"], x["record"]["name"]) for x in preview["would_end"]} == {
        (ids["sparc"], "SPARC pump"), (ids["btf"], "BTF pump")}                     # LNF's own stays
    db.expire_all()
    assert db.get(Asset, r["building"].uid).site_shared                            # nothing changed yet

    done = admin.put(f"/v1/assets/{r['building'].uid}/site-sharing", headers=hl,
                     json={"shared": False, "confirm": True}).json()
    assert len(done["ended"]) == 2 and done["withheld"]
    db.expire_all()
    assert indoor.current(db, r["sparc_pump"].uid) is None
    ended = db.scalar(select(IndoorPlacement).where(IndoorPlacement.asset_uid == r["sparc_pump"].uid))
    assert ended.state == "withdrawn" and ended.valid_until is not None
    assert spatial.current(db, r["sparc_pump"].uid) is not None                    # keeps the plan's position
    assert indoor.current(db, r["lnf_pump"].uid) is not None                       # the site's own placement stays
    assert sparc.get(f"/v1/plans/{p.uid}", headers={"X-Workspace-Id": ids["sparc"]}).status_code == 404
    assert r["hall"].uid not in seen_from(db, ids["sparc"])                        # the hall inside goes too
    from app.models.asset_subresources import AssetHistory
    lines = [h.details for h in db.scalars(select(AssetHistory).where(AssetHistory.asset_uid == r["sparc_pump"].uid))]
    assert any(d.startswith("No longer placed in Hall 3") and "no longer shared" in d for d in lines), lines

    # Shared again: the places come back, the placements do not.
    admin.put(f"/v1/assets/{r['building'].uid}/site-sharing", headers=hl, json={"shared": True})
    db.expire_all()
    assert sparc.get(f"/v1/plans/{p.uid}", headers={"X-Workspace-Id": ids["sparc"]}).status_code == 200
    assert indoor.current(db, r["sparc_pump"].uid) is None


def test_a_facility_leaving_its_site_previews_then_loses_its_placements(plan):
    db, ids, r, people, p = plan["db"], plan["ids"], plan["rec"], plan["people"], plan["plan"]
    _place_on(_as(people["sparc"]), ids["sparc"], r["sparc_pump"].uid, p.uid, r["hall"].uid, 10, 10)
    _place_on(_as(people["btf"]), ids["btf"], r["btf_pump"].uid, p.uid, r["hall"].uid, 20, 20)
    admin = _as(plan["admin"])
    preview = admin.put(f"/v1/admin/sites/{ids['sparc']}/site", json={"site_id": None}).json()
    assert preview["preview"] and [x["record"]["name"] for x in preview["would_end"]] == ["SPARC pump"]
    done = admin.put(f"/v1/admin/sites/{ids['sparc']}/site", json={"site_id": None, "confirm": True}).json()
    assert len(done["ended"]) == 1
    db.expire_all()
    assert indoor.current(db, r["sparc_pump"].uid) is None and indoor.current(db, r["btf_pump"].uid) is not None
    assert r["building"].uid not in seen_from(db, ids["sparc"])
