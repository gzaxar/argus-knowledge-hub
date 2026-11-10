"""Site-owned groups and site-wide group grants (issue #26): one grant for a site reaches the site and its current
facilities, never by copying; direct grants still work; nothing broadens access by surprise."""
import secrets

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.auth import OidcIdentity
from app.db import SessionLocal
from app.models.group import Group, GroupMember
from app.models.role import RoleBinding
from app.models.user import User
from app.models.workspace import SiteAdministrator, Workspace
from app.routers import groups, roles, sites
from app.schemas.group import GroupCreate
from app.schemas.role import RoleBindingCreate
from app.services import sites as site_service
from app.services.permissions import effective_permissions
from app.services.roles import ensure_system_roles


@pytest.fixture()
def lab():
    t = secrets.token_hex(4)
    db = SessionLocal()
    ensure_system_roles(db)
    ids = {"site": f"lnf-{t}", "sparc": f"sparc-{t}", "btf": f"btf-{t}", "new": f"newfac-{t}", "other": f"else-{t}",
           "other_site": f"lnl-{t}"}
    db.add_all([Workspace(id=ids["site"], name="LNF", role="site"), Workspace(id=ids["other_site"], name="LNL", role="site")])
    db.flush()
    db.add_all([Workspace(id=ids["sparc"], name="SPARC", site_id=ids["site"]),
                Workspace(id=ids["btf"], name="BTF", site_id=ids["site"]),
                Workspace(id=ids["new"], name="New facility"), Workspace(id=ids["other"], name="Elsewhere")])
    people = {n: User(id=f"{n}-{t}", email=f"{n}-{t}@infn.it", active=True)
              for n in ("site_admin", "ws_admin", "member", "outsider")}
    db.add_all(people.values())
    db.flush()
    db.add(SiteAdministrator(site_id=ids["site"], user_id=people["site_admin"].id))
    ops = Group(uid=f"ops-{t}", name=f"Operations {t}", source="local", active=True, home_site_id=ids["site"])
    db.add(ops)
    db.flush()
    db.add(GroupMember(group_uid=ops.uid, user_id=people["member"].id, source="local"))
    from datetime import datetime, timezone
    db.add(RoleBinding(workspace_id=ids["btf"], subject_type="user", subject_id=people["ws_admin"].id,
                       role_id="workspace_admin", created_at=datetime.now(timezone.utc)))
    db.commit()
    yield {"db": db, "ids": ids, "people": people, "ops": ops, "t": t}
    db.rollback()
    for w in ("sparc", "btf", "new", "other", "site", "other_site"):
        ws = db.get(Workspace, ids[w])
        if ws is not None:
            from app.ledger.audit import allow_purge
            allow_purge(db)
            db.delete(ws)
            db.commit()
    db.close()


def as_(user):
    return OidcIdentity(user=user)


def grant(lab, role="reporter", who="site_admin", group=None):
    return sites.create_site_group_grant(lab["ids"]["site"], sites.SiteGroupGrantIn(
        group_uid=(group or lab["ops"]).uid, role_id=role), identity=as_(lab["people"][who]), db=lab["db"])


def can(lab, who, ws, action="create", resource="tickets"):
    return action in effective_permissions(lab["db"], lab["people"][who], lab["ids"][ws])[resource]


def test_one_site_grant_reaches_the_site_and_its_facilities_without_copies(lab):
    db = lab["db"]
    before = db.scalar(select(func.count()).select_from(RoleBinding))
    assert not can(lab, "member", "sparc")
    out = grant(lab)
    assert out["role_id"] == "reporter" and out["group_name"] == lab["ops"].name
    assert all(can(lab, "member", w) for w in ("site", "sparc", "btf"))
    assert not can(lab, "member", "other") and not can(lab, "member", "other_site")
    assert db.scalar(select(func.count()).select_from(RoleBinding)) == before, "nothing copied into facilities"
    assert not can(lab, "outsider", "sparc"), "only the group's members"


def test_a_facility_joining_inherits_at_once_and_one_leaving_loses_it_at_once(lab):
    db, ids = lab["db"], lab["ids"]
    grant(lab)
    assert not can(lab, "member", "new")
    site_service.set_site(db, ids["new"], ids["site"])
    db.commit()
    assert can(lab, "member", "new")
    inherited = roles.inherited_grants(ids["new"], identity=as_(lab["people"]["site_admin"]), db=db)
    assert [(g["group_name"], g["role_id"], g["site_id"]) for g in inherited] == [(lab["ops"].name, "reporter", ids["site"])]
    site_service.set_site(db, ids["sparc"], None)
    db.commit()
    assert not can(lab, "member", "sparc")
    admin = as_(User(id="admin", email="admin@infn.it", is_admin=True))
    assert roles.inherited_grants(ids["sparc"], identity=admin, db=db) == []
    with pytest.raises(HTTPException):               # and its old site's administrator no longer manages it
        roles.inherited_grants(ids["sparc"], identity=as_(lab["people"]["site_admin"]), db=db)


def test_direct_and_inherited_grants_add_up_and_a_deactivated_group_gives_nothing(lab):
    db, ids = lab["db"], lab["ids"]
    grant(lab, "viewer")
    roles.create_binding(ids["btf"], RoleBindingCreate(subject_type="group", subject_id=lab["ops"].uid,
                                                       role_id="contributor"),
                         identity=as_(lab["people"]["ws_admin"]), db=db)
    assert can(lab, "member", "btf", "create", "objects"), "the direct Contributor grant in BTF"
    assert not can(lab, "member", "sparc", "create", "objects") and can(lab, "member", "sparc", "read", "objects")
    lab["ops"].active = False
    db.commit()
    assert not can(lab, "member", "btf", "read", "objects") and not can(lab, "member", "sparc", "read", "objects")


def test_only_general_roles_are_given_site_wide(lab):
    for role in ("owner", "workspace_admin"):
        with pytest.raises(HTTPException) as e:
            grant(lab, role)
        assert e.value.status_code == 422


def test_a_workspace_administrator_cannot_touch_site_grants(lab):
    out = grant(lab)
    with pytest.raises(HTTPException) as e:
        grant(lab, "viewer", who="ws_admin")
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        sites.revoke_site_group_grant(lab["ids"]["site"], out["id"], identity=as_(lab["people"]["ws_admin"]), db=lab["db"])
    assert e.value.status_code == 403
    sites.revoke_site_group_grant(lab["ids"]["site"], out["id"], identity=as_(lab["people"]["site_admin"]), db=lab["db"])
    assert not can(lab, "member", "sparc")


def test_a_site_group_has_direct_roles_only_inside_its_site(lab):
    db, ids = lab["db"], lab["ids"]
    with pytest.raises(HTTPException) as e:
        roles.create_binding(ids["other"], RoleBindingCreate(subject_type="group", subject_id=lab["ops"].uid,
                                                             role_id="viewer"), identity=as_(User(id="x", email="x", is_admin=True)), db=db)
    assert e.value.status_code == 422 and "belongs to the site" in e.value.detail
    with pytest.raises(HTTPException):
        sites.create_site_group_grant(ids["other_site"], sites.SiteGroupGrantIn(group_uid=lab["ops"].uid, role_id="viewer"),
                                      identity=as_(User(id="x", email="x", is_admin=True)), db=db)


def test_who_makes_a_site_group(lab):
    db, ids, t = lab["db"], lab["ids"], lab["t"]
    made = groups.create_group(GroupCreate(name=f"Shift {t}", home_site_id=ids["site"]), workspace_id=ids["btf"],
                               identity=as_(lab["people"]["site_admin"]), db=db)
    assert made.home_site_id == ids["site"] and made.workspaces == [] and made.site_grants == []
    with pytest.raises(HTTPException) as e:
        groups.create_group(GroupCreate(name=f"Sneaky {t}", home_site_id=ids["site"]), workspace_id=ids["btf"],
                            identity=as_(lab["people"]["ws_admin"]), db=db)
    assert e.value.status_code == 403


def test_a_preview_names_who_and_where_and_changes_nothing(lab):
    db, ids = lab["db"], lab["ids"]
    p = sites.preview_site_group_grant(ids["site"], sites.SiteGroupGrantIn(group_uid=lab["ops"].uid, role_id="reporter"),
                                       identity=as_(lab["people"]["site_admin"]), db=db)
    assert [x["email"] for x in p["people"]] == [lab["people"]["member"].email]
    assert set(p["workspaces"]) == {ids["site"], ids["sparc"], ids["btf"]}
    assert not can(lab, "member", "sparc")


def test_a_site_with_grants_or_groups_keeps_its_role_until_they_are_settled(lab):
    db, ids = lab["db"], lab["ids"]
    for f in ("sparc", "btf"):
        site_service.set_site(db, ids[f], None)
    out = grant(lab)
    with pytest.raises(site_service.SiteProblem, match="site-wide"):
        site_service.set_role(db, ids["site"], False)
    sites.revoke_site_group_grant(ids["site"], out["id"], identity=as_(lab["people"]["site_admin"]), db=db)
    with pytest.raises(site_service.SiteProblem, match="groups belong"):
        site_service.set_role(db, ids["site"], False)


def test_a_facility_cannot_leave_while_it_gives_roles_to_its_sites_groups(lab):
    db, ids = lab["db"], lab["ids"]
    roles.create_binding(ids["btf"], RoleBindingCreate(subject_type="group", subject_id=lab["ops"].uid, role_id="viewer"),
                         identity=as_(lab["people"]["ws_admin"]), db=db)
    with pytest.raises(site_service.SiteProblem, match="Operations"):
        site_service.set_site(db, ids["btf"], ids["other_site"])
    db.rollback()
    assert db.get(Workspace, ids["btf"]).site_id == ids["site"]


def test_a_directory_group_can_be_granted_site_wide_and_stays_read_only(lab):
    db, t = lab["db"], lab["t"]
    ldap = Group(uid=f"ldap-{t}", dn=f"cn={t},dc=infn", name=f"LDAP {t}", source="ldap", active=True)
    db.add(ldap)
    db.add(GroupMember(group_uid=ldap.uid, user_id=lab["people"]["outsider"].id, source="ldap"))
    db.commit()
    grant(lab, "viewer", group=ldap)
    assert can(lab, "outsider", "btf", "read", "objects")
    from app.schemas.group import GroupMembersIn
    with pytest.raises(HTTPException) as e:
        groups.add_group_members(ldap.uid, GroupMembersIn(emails=f"z-{t}@infn.it"), workspace_id=lab["ids"]["site"],
                                 identity=as_(lab["people"]["site_admin"]), db=db)
    assert e.value.status_code == 409
    db.delete(ldap)
    db.commit()


# --- second part: where rights come from, previews before moving, the record of changes, archives --------------

def test_my_permissions_say_where_each_right_comes_from(lab):
    db, ids = lab["db"], lab["ids"]
    grant(lab, "reporter")
    roles.create_binding(ids["btf"], RoleBindingCreate(subject_type="user", subject_id=lab["people"]["member"].id,
                                                       role_id="viewer"), identity=as_(lab["people"]["ws_admin"]), db=db)
    out = roles.my_permissions(ids["btf"], identity=as_(lab["people"]["member"]), db=db)
    kinds = {(s["source"], s.get("role")) for s in out.sources}
    assert ("direct", "Viewer") in kinds and ("site", "Reporter") in kinds
    site = next(s for s in out.sources if s["source"] == "site")
    assert site["site"] == ids["site"] and site["group"] == lab["ops"].name and "site-wide" in site["label"]


def test_an_access_review_names_site_wide_grants(lab):
    from app.services import access_review
    grant(lab, "reporter")
    snap = access_review.snapshot(lab["db"], lab["ids"]["btf"])
    member = next(p for p in snap["people"] if p["user"] == lab["people"]["member"].id)
    assert any("site-wide" in r for r in member["roles"])
    assert any(g.get("site_wide_from") == lab["ids"]["site"] for g in snap["groups"])


def test_moving_a_facility_previews_who_loses_and_gains_before_anything_changes(lab):
    db, ids = lab["db"], lab["ids"]
    grant(lab, "reporter")
    admin = as_(User(id=f"adm-{lab['t']}", email="adm@infn.it", is_admin=True))
    out = sites.set_site(ids["sparc"], sites.SiteIn(site_id=ids["other_site"]), identity=admin, db=db)
    assert out["preview"] and out["access"]["to_site"] == ids["other_site"]
    [lost] = out["access"]["loses"]
    assert lost["group_name"] == lab["ops"].name and lost["people"] == [lab["people"]["member"].email]
    assert db.get(Workspace, ids["sparc"]).site_id == ids["site"], "a preview changes nothing"
    done = sites.set_site(ids["sparc"], sites.SiteIn(site_id=ids["other_site"], confirm=True), identity=admin, db=db)
    assert done["site_id"] == ids["other_site"] and not can(lab, "member", "sparc")


def test_every_change_to_access_is_recorded(lab):
    db, ids = lab["db"], lab["ids"]
    out = grant(lab, "reporter")
    roles.create_binding(ids["btf"], RoleBindingCreate(subject_type="group", subject_id=lab["ops"].uid, role_id="viewer"),
                         identity=as_(lab["people"]["ws_admin"]), db=db)
    sites.revoke_site_group_grant(ids["site"], out["id"], identity=as_(lab["people"]["site_admin"]), db=db)
    events = roles.access_events(ids["btf"], identity=as_(lab["people"]["ws_admin"]), db=db)
    kinds = [e["kind"] for e in events]
    assert kinds[:3] == ["site_role.revoked", "role.granted", "site_role.granted"]
    assert events[0]["actor"] == lab["people"]["site_admin"].email and events[0]["subject"] == lab["ops"].name


def test_a_group_moves_to_a_site_only_when_its_grants_fit_and_back_only_by_an_instance_administrator(lab):
    db, ids, t = lab["db"], lab["ids"], lab["t"]
    from app.schemas.group import GroupHomeIn
    loose = Group(uid=f"loose-{t}", name=f"Loose {t}", source="local", active=True)
    db.add(loose)
    db.commit()
    admin = as_(User(id=f"adm-{t}", email="adm@infn.it", is_admin=True))
    roles.create_binding(ids["other"], RoleBindingCreate(subject_type="group", subject_id=loose.uid, role_id="viewer"),
                         identity=admin, db=db)
    blocked = groups.move_group(loose.uid, GroupHomeIn(home_site_id=ids["site"], confirm=True), workspace_id=None,
                                identity=admin, db=db)
    assert blocked["preview"] and blocked["blocked"] == [{"kind": "direct", "workspace_id": ids["other"], "role_id": "viewer"}]
    assert db.get(Group, loose.uid).home_site_id is None
    with pytest.raises(HTTPException) as e:
        groups.move_group(lab["ops"].uid, GroupHomeIn(home_site_id=None, confirm=True), workspace_id=None,
                          identity=as_(lab["people"]["site_admin"]), db=db)
    assert e.value.status_code == 403
    moved = groups.move_group(lab["ops"].uid, GroupHomeIn(home_site_id=None, confirm=True), workspace_id=None,
                              identity=admin, db=db)
    assert not moved["preview"] and db.get(Group, lab["ops"].uid).home_site_id is None
    db.delete(db.get(Group, loose.uid))
    db.commit()


def test_a_facility_only_archive_keeps_its_inherited_access_as_a_dependency(lab):
    from app.portability import exporter
    grant(lab, "reporter")
    deps = exporter._site_dependencies(lab["db"], type("Scope", (), {"workspaces": [lab["ids"]["btf"]]})())
    assert deps == [{"workspace": lab["ids"]["btf"], "site": lab["ids"]["site"],
                     "inherited": [{"group": lab["ops"].name, "group_uid": lab["ops"].uid, "role": "reporter"}]}]
    both = exporter._site_dependencies(lab["db"], type("Scope", (), {"workspaces": [lab["ids"]["btf"], lab["ids"]["site"]]})())
    assert both == [], "with its site in the archive, the grant itself travels"
