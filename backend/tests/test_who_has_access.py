"""Who has access to a workspace, and how: every route in one list, the same as what decides each request; the
whole list only to those who manage access, on Access and in Ask ARGUS's workspace_access lookup."""
import secrets
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.auth import OidcIdentity
from app.db import SessionLocal
from app.models.group import Group, GroupMember
from app.models.membership import Membership
from app.models.role import RoleBinding, SiteGroupRoleBinding
from app.models.user import User
from app.models.workspace import SiteAdministrator, Workspace
from app.routers import roles
from app.services import mcp_tools
from app.services import who_has_access as wha
from app.services.permissions import effective_permissions
from app.services.roles import ensure_system_roles


@pytest.fixture()
def lab():
    t = secrets.token_hex(4)
    db = SessionLocal()
    ensure_system_roles(db)
    site, fac = f"lnf-{t}", f"satc-{t}"
    db.add(Workspace(id=site, name="LNF", role="site"))
    db.flush()
    db.add(Workspace(id=fac, name="SATC", site_id=site))
    people = {n: User(id=f"{n}-{t}", email=f"{n}-{t}@infn.it", name=n.replace("_", " ").title(), active=True,
                      is_admin=(n == "root"))
              for n in ("root", "site_admin", "ws_admin", "it_member", "site_member", "area", "outsider", "viewer")}
    db.add_all(people.values())
    db.flush()
    now = datetime.now(timezone.utc)
    it = Group(uid=f"it-{t}", name=f"IT-LNF {t}", source="local", active=True)
    ops = Group(uid=f"ops-{t}", name=f"Operations {t}", source="local", active=True, home_site_id=site)
    gone = Group(uid=f"gone-{t}", name=f"Old {t}", source="local", active=False)
    db.add_all([it, ops, gone])
    db.flush()
    db.add_all([
        SiteAdministrator(site_id=site, user_id=people["site_admin"].id),
        GroupMember(group_uid=it.uid, user_id=people["it_member"].id, source="local"),
        GroupMember(group_uid=ops.uid, user_id=people["site_member"].id, source="local"),
        GroupMember(group_uid=gone.uid, user_id=people["outsider"].id, source="local"),
        RoleBinding(workspace_id=fac, subject_type="group", subject_id=it.uid, role_id="workspace_admin", created_at=now),
        RoleBinding(workspace_id=fac, subject_type="group", subject_id=gone.uid, role_id="curator", created_at=now),
        RoleBinding(workspace_id=fac, subject_type="user", subject_id=people["ws_admin"].id, role_id="workspace_admin",
                    created_at=now),
        RoleBinding(workspace_id=fac, subject_type="user", subject_id=people["viewer"].id, role_id="viewer",
                    created_at=now),
        SiteGroupRoleBinding(site_id=site, group_uid=ops.uid, role_id="reporter", created_at=now),
        Membership(workspace_id=fac, user_id=people["area"].id, can_read=True, can_read_tickets=False,
                   can_read_documents=False),
    ])
    db.commit()
    yield {"db": db, "site": site, "ws": fac, "p": people, "t": t}
    db.rollback()
    from app.ledger.audit import allow_purge
    for w in (fac, site):
        ws = db.get(Workspace, w)
        if ws is not None:
            allow_purge(db)
            db.delete(ws)
            db.commit()
    # Users stay, as in the other access tests; this one must not stay an administrator of the installation.
    db.get(User, people["root"].id).is_admin = False
    db.commit()
    db.close()


def _by_email(listing):
    return {p["email"]: p for p in listing["people"]}


def test_every_route_in_one_list_with_what_decides_each_request(lab):
    db, p, ws = lab["db"], lab["p"], lab["ws"]
    out = wha.who_has_access(db, ws)
    people = _by_email(out)
    sources = {n: {r["source"] for r in people[p[n].email]["routes"]}
               for n in ("root", "site_admin", "ws_admin", "it_member", "site_member", "area", "viewer")}
    assert sources["root"] == {"instance_administrator"}
    assert sources["site_admin"] == {"site_administrator"}
    assert sources["ws_admin"] == {"direct"}
    assert sources["it_member"] == {"group"}
    assert sources["site_member"] == {"site"}
    assert sources["area"] == {"legacy"}
    # A deactivated group gives nothing, so its member is not listed.
    assert p["outsider"].email not in people
    for n in ("site_admin", "ws_admin", "it_member", "site_member", "area", "viewer"):
        decided = {r: sorted(a) for r, a in effective_permissions(db, p[n], ws).items() if a}
        assert {r: sorted(a) for r, a in people[p[n].email]["rights"].items()} == decided, n
    assert people[p["site_admin"].email]["rights"]["workspace"] == ["manage_members"]
    assert people[p["area"].email]["rights"] == {"objects": ["read"]}
    assert out["anyone_signed_in"] == {} and out["site_id"] == lab["site"]
    # The installation's own administrators last: they reach every workspace.
    emails = [x["email"] for x in out["people"]]
    assert emails.index(p["ws_admin"].email) < emails.index(p["root"].email)


def test_what_anyone_signed_in_gets_is_said_apart(lab):
    db = lab["db"]
    w = db.get(Workspace, lab["ws"])
    w.default_can_read = True
    w.default_can_read_documents = True
    db.commit()
    assert wha.who_has_access(db, lab["ws"])["anyone_signed_in"] == {"objects": ["read"], "documents": ["read"]}


def test_the_list_is_for_those_who_manage_access(lab):
    db, p, ws = lab["db"], lab["p"], lab["ws"]
    for n in ("ws_admin", "it_member", "site_admin", "root"):
        assert roles.who_has_access(ws, identity=OidcIdentity(user=p[n]), db=db)["workspace_id"] == ws
    for n in ("viewer", "site_member", "area"):
        with pytest.raises(HTTPException) as e:
            roles.who_has_access(ws, identity=OidcIdentity(user=p[n]), db=db)
        assert e.value.status_code == 403


def test_ask_tells_a_manager_everyone_and_anyone_else_only_about_themselves(lab):
    db, p, ws = lab["db"], lab["p"], lab["ws"]
    wha.set_viewer(wha.viewer_for(db, OidcIdentity(user=p["it_member"]), ws))
    out = mcp_tools.workspace_access(db, ws)
    listed = _by_email(out)
    assert {p[n].email for n in ("site_admin", "ws_admin", "it_member", "site_member", "area", "viewer")} <= set(listed)
    # Administrators of the installation with no route of their own here are named, not detailed.
    assert p["root"].email not in listed and p["root"].email in out["installation_administrators_only"]
    one = mcp_tools.workspace_access(db, ws, person=f"site_member-{lab['t']}")
    assert [x["email"] for x in one["people"]] == [p["site_member"].email]

    wha.set_viewer(wha.viewer_for(db, OidcIdentity(user=p["viewer"]), ws))
    mine = mcp_tools.workspace_access(db, ws, person=p["ws_admin"].email)
    assert mine["you"]["email"] == p["viewer"].email and "people" not in mine
    assert [r["source"] for r in mine["you"]["routes"]] == ["direct"]
    assert "not_shown" in mine and p["ws_admin"].email not in str(mine["you"])

    wha.set_viewer(None)
    assert mcp_tools.workspace_access(db, ws)["allowed"] is False


def test_the_lookup_is_offered_to_ask():
    assert "workspace_access" in {t["name"] for t in mcp_tools.catalogue()}
