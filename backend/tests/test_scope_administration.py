"""Delegated access administration must stay within the assigned scope."""
import secrets
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.auth import OidcIdentity, TokenScope
from app.db import SessionLocal
from app.routers import groups, roles, sites, workspaces
from app.models.group import Group
from app.models.role import RoleBinding
from app.models.user import User
from app.models.workspace import Workspace, SiteAdministrator
from app.services.permissions import effective_permissions
from app.services.roles import ensure_system_roles
from app.schemas.group import GroupAdministratorIn, GroupMembersIn, GroupUpdate
from app.schemas.role import RoleBindingCreate


def test_site_administrator_manages_only_current_site_facilities():
    suffix = secrets.token_hex(4)
    site_id, facility_id, other_id = (f"admin-site-{suffix}", f"admin-fac-{suffix}", f"admin-other-{suffix}")
    db = SessionLocal()
    site = Workspace(id=site_id, name="Laboratory", role="site")
    facility = Workspace(id=facility_id, name="Linac", site_id=site_id)
    other = Workspace(id=other_id, name="Elsewhere")
    site_admin = User(id=f"site-admin-{suffix}", email=f"site-admin-{suffix}@example.org", active=True)
    workspace_admin = User(id=f"workspace-admin-{suffix}", email=f"workspace-admin-{suffix}@example.org", active=True)
    db.add_all([site, facility, other, site_admin, workspace_admin])
    db.flush()
    db.add(SiteAdministrator(site_id=site_id, user_id=site_admin.id))
    db.commit()
    try:
        identity = OidcIdentity(user=site_admin)
        listed = workspaces.list_my_workspaces(identity=identity, db=db)
        ids = {w.id for w in listed}        # beside any workspace open to everyone that other tests left
        assert {site_id, facility_id} <= ids and other_id not in ids
        assert "manage_members" in effective_permissions(db, site_admin, facility_id)["workspace"]
        assert not effective_permissions(db, site_admin, other_id)["workspace"]
        grant = RoleBindingCreate(subject_type="user", subject_id=site_admin.id, role_id="viewer")
        assert roles.create_binding(facility_id, grant, identity=identity, db=db).role_id == "viewer"
        manager = roles.create_binding(facility_id, RoleBindingCreate(
            subject_type="user", subject_id=workspace_admin.id, role_id="workspace_admin"), identity=identity, db=db)
        assert manager.role_id == "workspace_admin"
        assert "manage_members" in effective_permissions(db, workspace_admin, facility_id)["workspace"]
        assert "manage_members" not in effective_permissions(db, workspace_admin, site_id)["workspace"]
        with pytest.raises(HTTPException) as denied:
            roles.create_binding(other_id, grant, identity=identity, db=db)
        assert denied.value.status_code == 403
        second = sites.add_site_administrator(site_id, sites.SiteAdministratorIn(
            email=f"second-site-{suffix}@example.org"), identity=identity, db=db)
        assert second["email"] == f"second-site-{suffix}@example.org"
        assert len(sites.list_site_administrators(site_id, identity=identity, db=db)) == 2
        with pytest.raises(HTTPException) as token_denied:
            sites.add_site_administrator(site_id, sites.SiteAdministratorIn(
                email=f"forbidden-{suffix}@example.org"), identity=OidcIdentity(
                    user=site_admin, token=TokenScope(scopes=frozenset({"read"}))), db=db)
        assert token_denied.value.status_code == 403
        facility.site_id = None
        db.commit()
        assert "manage_members" not in effective_permissions(db, site_admin, facility_id)["workspace"]
    finally:
        db.close()


def test_group_administrator_manages_members_without_workspace_authority():
    suffix = secrets.token_hex(4)
    a, b = f"admin-a-{suffix}", f"admin-b-{suffix}"
    db = SessionLocal()
    db.add_all([Workspace(id=a, name="A"), Workspace(id=b, name="B")])
    global_admin = User(id=f"global-{suffix}", email=f"global-{suffix}@example.org", active=True, is_admin=True)
    group_admin = User(id=f"group-admin-{suffix}", email=f"group-admin-{suffix}@example.org", active=True)
    db.add_all([global_admin, group_admin])
    ensure_system_roles(db)
    group = Group(uid=f"group-{suffix}", name=f"Crew {suffix}", source="local", active=True)
    db.add(group)
    db.flush()
    for workspace_id in (a, b):
        db.add(RoleBinding(workspace_id=workspace_id, subject_type="group", subject_id=group.uid,
                           role_id="viewer", created_at=datetime.now(timezone.utc), created_by=global_admin.id))
    db.commit()
    try:
        appointed = groups.add_group_administrator(group.uid, GroupAdministratorIn(email=group_admin.email),
                                                    workspace_id=a, identity=OidcIdentity(user=global_admin), db=db)
        assert appointed.user_id == group_admin.id
        identity = OidcIdentity(user=group_admin)
        assert groups.my_groups(identity=identity, db=db)[0].uid == group.uid
        assert groups.list_group_members(group.uid, workspace_id=None, identity=identity, db=db) == []
        added = groups.add_group_members(group.uid, GroupMembersIn(
            emails=f"new-{suffix}@example.org", send_email=False), workspace_id=a, identity=identity, db=db)
        assert added["people"][0]["joined"]
        new_user = db.scalar(select(User).where(User.email == f"new-{suffix}@example.org"))
        assert new_user is not None
        assert "read" in effective_permissions(db, new_user, a)["objects"]
        assert "read" in effective_permissions(db, new_user, b)["objects"]
        with pytest.raises(HTTPException) as metadata:
            groups.update_group(group.uid, GroupUpdate(name="Changed"), workspace_id=a, identity=identity, db=db)
        assert metadata.value.status_code == 403
        with pytest.raises(HTTPException) as grant:
            roles.create_binding(a, RoleBindingCreate(
                subject_type="user", subject_id=group_admin.id, role_id="owner"), identity=identity, db=db)
        assert grant.value.status_code == 403
        group.active = False
        db.commit()
        assert "read" not in effective_permissions(db, new_user, a)["objects"]
    finally:
        db.close()


def test_group_administrator_can_add_members_before_a_workspace_role():
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    group = Group(uid=f"unbound-{suffix}", name=f"New crew {suffix}", source="local", active=True)
    admin = User(id=f"unbound-admin-{suffix}", email=f"unbound-admin-{suffix}@example.org", active=True)
    db.add_all([group, admin])
    db.flush()
    from app.models.group import GroupAdministrator
    db.add(GroupAdministrator(group_uid=group.uid, user_id=admin.id))
    db.commit()
    try:
        out = groups.add_group_members(group.uid, GroupMembersIn(
            emails=f"early-{suffix}@example.org", send_email=False),
            workspace_id=None, identity=OidcIdentity(user=admin), db=db)
        assert out["people"][0]["joined"] and not out["group_granted"]
        assert len(groups.list_group_members(group.uid, workspace_id=None, identity=OidcIdentity(user=admin), db=db)) == 1
    finally:
        db.close()
