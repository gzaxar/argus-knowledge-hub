"""Finding a unit by whatever names it, hearing about what one follows in any workspace, and JQL."""
import secrets
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.asset import Asset
from app.models.asset_subresources import AssetLabel
from app.models.membership import Membership
from app.models.user import User
from app.models.workspace import Workspace
from app.services import asset_types
from tests.test_field_client import resolve, world as field_world

client = TestClient(app)
FULL = dict(can_read=True, can_create=True, can_modify=True, can_read_tickets=True, can_create_tickets=True,
            can_modify_tickets=True, can_read_documents=True, can_create_documents=True, can_modify_documents=True,
            can_approve_documents=True)


def _label(db, asset_uid, type_, value):
    now = datetime.now(timezone.utc)
    db.add(AssetLabel(uid=str(uuid.uuid4()), asset_uid=asset_uid, type=type_, value=value, issuer="test",
                      created_at=now, updated_at=now))


def _asset(db, ws, schema_uid, key, attrs=None):
    a = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=schema_uid, key=key, name=f"Unit {key}",
              type="Ion Pump", attributes=attrs or {})
    db.add(a)
    db.flush()
    return a


# --------------------------------------------------------------------------- a scan, and the search boxes

def test_a_scan_offers_both_the_record_with_a_key_and_the_one_that_had_it():
    w = field_world()
    db = SessionLocal()
    pump = db.get(Asset, w["pump"])
    renamed = _asset(db, w["ws"], pump.schema_uid, f"{w['ws']}-NEW-1")
    _label(db, renamed.uid, "former_key", pump.key)           # an import kept the old record under that key
    renamed_uid = renamed.uid
    db.commit()
    db.close()
    r = resolve(w, f"/lookup/{w['ws']}-IP-1")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ambiguous"
    assert {c["uid"] for c in r.json()["detail"]["candidates"]} == {w["pump"], renamed_uid}
    assert all(c["workspace_id"] == w["ws"] for c in r.json()["detail"]["candidates"])


def test_a_scan_finds_a_key_in_any_case_an_inventory_number_and_an_alias():
    w = field_world()
    db = SessionLocal()
    pump = db.get(Asset, w["pump"])
    old = _asset(db, w["ws"], pump.schema_uid, f"{w['ws']}-OLD", {"inventory": f"77{w['ws'][-4:]}"})
    url = f"https://servicedesk.example/secure/ShowObject.jspa?id={secrets.randbelow(10**8)}"
    _label(db, old.uid, "qrcode", url)                        # the old record's printed code…
    new = _asset(db, w["ws"], pump.schema_uid, f"{w['ws']}-MIG")
    _label(db, new.uid, "alias", url)                         # …is the alias of the record it became
    old_uid, new_uid = old.uid, new.uid
    db.commit()
    db.close()
    assert resolve(w, f"/lookup/{w['ws']}-ip-1".lower()).json()["uid"] == w["pump"]
    assert resolve(w, f"/lookup/77{w['ws'][-4:]}").json()["uid"] == old_uid
    assert resolve(w, f"/lookup/Inv. 77{w['ws'][-4:]}").json()["uid"] == old_uid
    both = resolve(w, f"/lookup/{url}")
    assert both.status_code == 409
    assert {c["uid"] for c in both.json()["detail"]["candidates"]} == {old_uid, new_uid}


def test_the_search_boxes_find_a_unit_by_its_labels():
    w = field_world()
    db = SessionLocal()
    former = f"LNF-{secrets.token_hex(3)}"
    _label(db, w["pump"], "former_key", former)
    db.commit()
    db.close()
    found = client.get("/v1/hub/search", params={"q": former}, headers=w["headers"]).json()
    assert [a["uid"] for a in found["assets"]] == [w["pump"]]
    listed = client.get("/v1/assets", params={"q": former.lower(), "limit": 10}, headers=w["headers"]).json()
    assert [a["uid"] for a in listed] == [w["pump"]]
    by_inventory = client.get("/v1/assets", params={"q": f"INV-{w['ws']}", "limit": 10}, headers=w["headers"]).json()
    assert [a["uid"] for a in by_inventory] == [w["pump"]]


# --------------------------------------------------------------------------- people in two workspaces

@pytest.fixture()
def people():
    t = secrets.token_hex(3)
    ws, other = f"ff-{t}", f"ff-other-{t}"
    db = SessionLocal()
    db.add_all([Workspace(id=ws, name="Linac"), Workspace(id=other, name="Ring")])
    db.flush()
    types = asset_types.ensure_asset_types(db, ws).uids
    out = {}
    for name in ("ann", "bob", "cid"):
        u = User(id=str(uuid.uuid4()), email=f"{name}-{t}@argus.test", name=name, is_admin=False)
        db.add(u)
        db.flush()
        out[name] = u
    db.add(Membership(workspace_id=ws, user_id=out["ann"].id, **FULL))
    db.add(Membership(workspace_id=ws, user_id=out["bob"].id, **FULL))
    db.add(Membership(workspace_id=other, user_id=out["bob"].id, **FULL))
    db.add(Membership(workspace_id=ws, user_id=out["cid"].id, **{**FULL, "can_read_documents": False}))
    db.commit()
    for u in out.values():
        db.refresh(u)
        db.expunge(u)
    db.close()
    yield {"ws": ws, "other": other, "types": types, **out}
    app.dependency_overrides.pop(get_identity, None)
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    for w in (ws, other):
        db.delete(db.get(Workspace, w))
    db.commit()
    for u in out.values():
        db.delete(db.get(User, u.id))
    db.commit()
    db.close()


def as_(user):
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=user)


def inbox(w, who):
    as_(w[who])
    return client.get("/v1/notifications/everywhere", params={"include_read": True}).json()


def test_a_ticket_assigned_in_another_workspace_is_in_the_inbox_and_on_the_home(people):
    w = people
    as_(w["ann"])
    uid = str(uuid.uuid4())
    assert client.post("/v1/issues", headers={"X-Workspace-Id": w["ws"]},
                       json={"uid": uid, "title": "Check the gun vacuum", "assignee": w["bob"].id}).status_code in (200, 201)
    rows = inbox(w, "bob")                    # bob has the app open in the Ring workspace: it does not matter
    mine = [n for n in rows if n["issue_uid"] == uid]
    assert mine and mine[0]["title"] == "Assigned to you: Check the gun vacuum" and mine[0]["read"] is False
    assert mine[0]["workspace_name"] == "Linac"
    work = client.get("/v1/hub/my-work").json()
    assert [(t["uid"], t["why"], t["workspace_name"]) for t in work] == [(uid, "assigned", "Linac")]
    assert client.post(f"/v1/notifications/everywhere/{mine[0]['id']}/read").status_code == 200
    assert [n["read"] for n in inbox(w, "bob") if n["issue_uid"] == uid] == [True]
    as_(w["cid"])
    assert client.post(f"/v1/notifications/everywhere/{mine[0]['id']}/read").status_code == 404, "not hers"


def test_a_change_to_a_ticket_reaches_its_watchers(people):
    w = people
    as_(w["bob"])
    uid = str(uuid.uuid4())
    h = {"X-Workspace-Id": w["ws"]}
    client.post("/v1/issues", headers=h, json={"uid": uid, "title": "Gauge reads zero"})
    as_(w["ann"])
    t = client.get(f"/v1/issues/{uid}", headers=h)
    r = client.put(f"/v1/issues/{uid}", headers={**h, "If-Match": t.headers.get("etag", "")},
                   json={"priority": "High", "description": "Since the bake-out"})
    assert r.status_code == 200, r.text
    titles = [n["title"] for n in inbox(w, "bob")]
    assert any(x.startswith("Gauge reads zero:") and "priority" in x and "description" in x for x in titles)


def test_following_equipment_and_documents_in_any_workspace(people):
    w = people
    h = {"X-Workspace-Id": w["ws"]}
    as_(w["ann"])
    asset = str(uuid.uuid4())
    assert client.post("/v1/assets", headers=h, json={"uid": asset, "schema_uid": w["types"]["Ion Pump"],
                                                      "key": f"{w['ws']}-IP-7", "name": "Ion pump 7",
                                                      "attributes": {}}).status_code == 201
    doc = str(uuid.uuid4())
    assert client.post("/v1/documents", headers=h, json={"uid": doc, "title": "Bake-out", "body_markdown": "Heat"}).status_code == 201

    as_(w["bob"])
    assert client.put(f"/v1/notifications/following/asset/{asset}").json()["following"] is True
    assert client.put(f"/v1/notifications/following/document/{doc}").json()["followers"] == 2   # ann wrote it
    assert {f["uid"] for f in client.get("/v1/notifications/following").json()} == {asset, doc}
    as_(w["cid"])
    assert client.put(f"/v1/notifications/following/document/{doc}").status_code == 404, "she may not read it"

    as_(w["ann"])
    now = datetime.now(timezone.utc).isoformat()
    assert client.post(f"/v1/assets/{asset}/labels", headers=h, json={
        "uid": str(uuid.uuid4()), "type": "qrcode", "value": f"QR-{asset[:6]}", "issuer": "field",
        "created_at": now, "updated_at": now}).status_code == 201
    assert client.post(f"/v1/documents/{doc}/revisions/{doc}-r1/submit", headers=h).status_code == 200

    titles = [n["title"] for n in inbox(w, "bob")]
    assert any(t.startswith("Ion pump 7") and "Added qrcode label" in t for t in titles)
    # bob may approve documents here: asked to review, not told twice
    assert any(t.startswith("Review requested:") and t.endswith("revision 1") for t in titles)
    assert not any(t.endswith("revision 1 sent for review") for t in titles)
    assert not any("sent for review" in n["title"] for n in inbox(w, "ann")), "not what you did yourself"

    as_(w["bob"])
    assert client.delete(f"/v1/notifications/following/asset/{asset}").json()["following"] is False


# --------------------------------------------------------------------------- JQL

def test_jql_selects_tickets_equipment_and_documents(people):
    w = people
    h = {"X-Workspace-Id": w["ws"]}
    as_(w["ann"])
    for title, prio, who in (("Leak on the gun", "High", w["bob"].id), ("Gauge flickers", "Low", None)):
        client.post("/v1/issues", headers=h, json={"uid": str(uuid.uuid4()), "title": title, "priority": prio,
                                                   **({"assignee": who} if who else {})})
    client.post("/v1/assets", headers=h, json={"uid": str(uuid.uuid4()), "schema_uid": w["types"]["Ion Pump"],
                                               "key": f"{w['ws']}-IP-3", "name": "Gun ion pump",
                                               "attributes": {"serial": "VPI-4711"}})

    def q(entity, jql, who="ann", headers=h):
        as_(w[who])
        return client.get("/v1/search/jql", params={"entity": entity, "jql": jql}, headers=headers)

    r = q("tickets", 'summary ~ leak AND priority in (High, Highest)')
    assert r.status_code == 200 and [i["title"] for i in r.json()["items"]] == ["Leak on the gun"]
    assert [i["title"] for i in q("tickets", "assignee = currentUser()", "bob").json()["items"]] == ["Leak on the gun"]
    assert [i["title"] for i in q("tickets", "assignee IS EMPTY").json()["items"]] == ["Gauge flickers"]
    ordered = q("tickets", "created >= -1d ORDER BY priority DESC").json()["items"]
    assert [i["title"] for i in ordered] == ["Leak on the gun", "Gauge flickers"]
    assert q("assets", 'serial ~ "VPI-47" AND type = "Ion Pump"').json()["total"] == 1
    assert q("assets", 'text ~ "gun pump"').json()["total"] == 1
    # bob may read both workspaces; a project clause searches there, the current workspace otherwise.
    assert q("tickets", f"project = {w['other']}", "bob", {"X-Workspace-Id": w["other"]}).json()["total"] == 0
    assert q("tickets", f"project in ({w['ws']}, {w['other']})", "bob", {"X-Workspace-Id": w["other"]}).json()["total"] == 2
    bad = q("tickets", "status = ")
    assert bad.status_code == 422 and bad.json()["detail"]["position"] == 9
    assert q("tickets", "summary ~ x ORDER updated").status_code == 422
    assert client.get("/v1/search/jql/fields").json()["tickets"]
