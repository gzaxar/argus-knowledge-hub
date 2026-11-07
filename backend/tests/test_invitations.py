"""People given access by their e-mail address before their first sign-in, and claiming it when they sign in."""
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import OidcIdentity, _resolve_oidc_user, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.role import RoleBinding
from app.models.user import User
from app.models.workspace import Workspace
from app.services import invitations, notify

client = TestClient(app)


@pytest.fixture()
def world():
    t = secrets.token_hex(4)
    ws = f"inv-{t}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name="Invitations"))
    admin = User(id=str(uuid.uuid4()), email=f"admin-{t}@argus.test", name="Ada Admin", is_admin=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    db.close()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
    yield {"ws": ws, "t": t, "h": {"X-Workspace-Id": ws}}
    app.dependency_overrides.pop(get_identity, None)
    db = SessionLocal()
    db.query(RoleBinding).filter(RoleBinding.workspace_id == ws).delete()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    db.delete(db.get(Workspace, ws))
    db.commit()
    db.close()


@pytest.fixture()
def mailbox(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "send_plain", lambda to, subject, body: sent.append((to, subject, body)))
    monkeypatch.setenv("ARGUS_WEB_URL", "https://argus.example.org")
    return sent


def test_addresses_are_read_as_pasted():
    found, bad = invitations.addresses('Ann <Ann.B@INFN.it>; bob@lnf.infn.it\nann.b@infn.it, not-one, "c@x.org"')
    assert found == ["ann.b@infn.it", "bob@lnf.infn.it", "c@x.org"] and bad == ["not-one"]


def test_an_invitation_adds_grants_and_tells_them(world, mailbox):
    ws, t = world["ws"], world["t"]
    resp = client.post(f"/v1/workspaces/{ws}/invitations", headers=world["h"], json={
        "emails": f"New.Person-{t}@infn.it, typo-address", "role_id": "reporter", "message": "Welcome to BTF."})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    [p] = out["people"]
    assert p["email"] == f"new.person-{t}@infn.it" and p["added"] and p["granted"] and p["emailed"]
    assert not p["signed_in"] and out["not_addresses"] == ["typo-address"]
    [(to, subject, body)] = mailbox
    assert to == p["email"] and "Invitations" in subject
    assert "Ada Admin gave you the" in body and "Welcome to BTF." in body and f"https://argus.example.org/?ws={ws}" in body
    rows = client.get(f"/v1/workspaces/{ws}/bindings", headers=world["h"]).json()
    mine = next(r for r in rows if r["subject_id"] == p["user_id"])
    assert mine["subject_pending"] and mine["role_id"] == "reporter"


def test_inviting_again_only_adds_what_is_missing(world, mailbox):
    ws, t = world["ws"], world["t"]
    body = {"emails": f"twice-{t}@infn.it", "role_id": "viewer", "send_email": False}
    first = client.post(f"/v1/workspaces/{ws}/invitations", headers=world["h"], json=body).json()["people"][0]
    again = client.post(f"/v1/workspaces/{ws}/invitations", headers=world["h"], json=body).json()["people"][0]
    assert first["added"] and first["granted"] and not again["added"] and not again["granted"]
    assert first["user_id"] == again["user_id"] and mailbox == []


def test_a_mail_that_cannot_go_is_said_and_the_access_stays(world, monkeypatch):
    def refuse(to, subject, body):
        raise notify.MailError("E-mail is not configured on this installation")
    monkeypatch.setattr(notify, "send_plain", refuse)
    out = client.post(f"/v1/workspaces/{world['ws']}/invitations", headers=world["h"],
                      json={"emails": f"nomail-{world['t']}@infn.it", "role_id": "viewer"}).json()
    [p] = out["people"]
    assert p["granted"] and not p["emailed"] and "not configured" in p["error"]


def test_the_first_sign_in_claims_the_invited_account_whatever_the_case(world, mailbox):
    ws, t = world["ws"], world["t"]
    p = client.post(f"/v1/workspaces/{ws}/invitations", headers=world["h"],
                    json={"emails": f"claim-{t}@infn.it", "role_id": "viewer", "send_email": False}).json()["people"][0]
    db = SessionLocal()
    user = _resolve_oidc_user(db, {"sub": f"sub-{t}", "email": f"Claim-{t}@INFN.it", "name": "Claire"})
    db.commit()
    assert user.id == p["user_id"] and user.oidc_sub == f"sub-{t}" and user.name == "Claire"
    assert db.scalar(select(RoleBinding.role_id).where(RoleBinding.subject_id == user.id,
                                                      RoleBinding.workspace_id == ws)) == "viewer"
    db.close()
    rows = client.get(f"/v1/workspaces/{ws}/bindings", headers=world["h"]).json()
    assert not next(r for r in rows if r["subject_id"] == p["user_id"])["subject_pending"]


def test_only_who_manages_the_workspace_may_invite(world):
    t = world["t"]
    db = SessionLocal()
    nobody = User(id=str(uuid.uuid4()), email=f"nobody-{t}@argus.test")
    db.add(nobody)
    db.commit()
    db.refresh(nobody)
    db.expunge(nobody)
    db.close()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=nobody)
    resp = client.post(f"/v1/workspaces/{world['ws']}/invitations", headers=world["h"],
                       json={"emails": f"x-{t}@infn.it", "role_id": "viewer"})
    assert resp.status_code == 403


# --- into a group, and the groups themselves -----------------------------------------------------------------

def test_many_addresses_into_a_new_group_that_gets_the_role(world, mailbox):
    ws, t = world["ws"], world["t"]
    out = client.post(f"/v1/workspaces/{ws}/invitations", headers=world["h"], json={
        "emails": f"g1-{t}@infn.it\ng2-{t}@infn.it", "role_id": "reporter", "new_group": f"BTF shift crew {t}"}).json()
    assert out["group_name"] == f"BTF shift crew {t}" and out["group_granted"]
    assert all(p["added"] and p["joined"] for p in out["people"]) and len(mailbox) == 2
    assert "added you to the group" in mailbox[0][2] and "Reporter" in mailbox[0][2]
    rows = client.get(f"/v1/workspaces/{ws}/bindings", headers=world["h"]).json()
    assert any(r["subject_type"] == "group" and r["subject_id"] == out["group_uid"] and r["role_id"] == "reporter"
               for r in rows)
    assert not any(r["subject_id"] in {p["user_id"] for p in out["people"]} for r in rows), "the group holds it"
    members = client.get(f"/v1/groups/{out['group_uid']}/members", headers=world["h"]).json()
    assert {m["email"] for m in members} == {f"g1-{t}@infn.it", f"g2-{t}@infn.it"}
    from app.models.user import User as U
    from app.services.permissions import has_permission
    db = SessionLocal()
    assert has_permission(db, db.get(U, out["people"][0]["user_id"]), ws, "read", "objects")
    db.close()


def test_a_group_is_made_renamed_filled_emptied_and_deactivated(world, mailbox):
    ws, t, h = world["ws"], world["t"], world["h"]
    g = client.post("/v1/groups", headers=h, json={"name": f"Vacuum team {t}", "description": "pumps"}).json()
    assert g["source"] == "local" and g["member_count"] == 0 and g["workspaces"] == []
    assert client.post("/v1/groups", headers=h, json={"name": f"Vacuum team {t}"}).status_code == 409
    added = client.post(f"/v1/groups/{g['uid']}/members", headers=h,
                        json={"emails": f"v1-{t}@infn.it, v2-{t}@infn.it", "send_email": False}).json()
    assert [p["joined"] for p in added["people"]] == [True, True] and mailbox == []
    renamed = client.patch(f"/v1/groups/{g['uid']}", headers=h, json={"name": f"Vacuum {t}"}).json()
    assert renamed["name"] == f"Vacuum {t}" and renamed["member_count"] == 2
    gone = added["people"][0]["user_id"]
    assert client.delete(f"/v1/groups/{g['uid']}/members/{gone}", headers=h).status_code == 204
    assert client.delete(f"/v1/groups/{g['uid']}/members/{gone}", headers=h).status_code == 404
    off = client.patch(f"/v1/groups/{g['uid']}", headers=h, json={"active": False}).json()
    assert not off["active"] and off["member_count"] == 1


def test_a_group_holding_a_role_elsewhere_is_changed_only_by_who_manages_there(world):
    ws, t, h = world["ws"], world["t"], world["h"]
    db = SessionLocal()
    other = f"inv-other-{t}"
    db.add(Workspace(id=other, name="Other"))
    manager = User(id=str(uuid.uuid4()), email=f"mgr-{t}@argus.test")
    db.add(manager)
    db.commit()
    db.refresh(manager)
    db.expunge(manager)
    db.close()
    g = client.post("/v1/groups", headers=h, json={"name": f"Shared {t}"}).json()
    from datetime import datetime, timezone
    db = SessionLocal()
    db.add_all([RoleBinding(workspace_id=other, subject_type="group", subject_id=g["uid"], role_id="viewer",
                            created_at=datetime.now(timezone.utc)),
                RoleBinding(workspace_id=ws, subject_type="user", subject_id=manager.id, role_id="owner",
                            created_at=datetime.now(timezone.utc))])
    db.commit()
    db.close()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=manager)
    try:
        resp = client.post(f"/v1/groups/{g['uid']}/members", headers=h, json={"emails": f"sneak-{t}@infn.it"})
        assert resp.status_code == 403 and other in resp.json()["detail"]
    finally:
        db = SessionLocal()
        db.query(RoleBinding).filter(RoleBinding.workspace_id == other).delete()
        from app.ledger.audit import allow_purge
        allow_purge(db)
        db.delete(db.get(Workspace, other))
        db.commit()
        db.close()


def test_a_directory_group_is_not_changed_here(world):
    from app.models.group import Group
    t = world["t"]
    db = SessionLocal()
    db.add(Group(uid=f"ldap-{t}", dn=f"cn=g{t},dc=infn", name=f"LDAP {t}", source="ldap", active=True))
    db.commit()
    db.close()
    resp = client.post(f"/v1/groups/ldap-{t}/members", headers=world["h"], json={"emails": f"x-{t}@infn.it"})
    assert resp.status_code == 409 and "directory" in resp.json()["detail"]
