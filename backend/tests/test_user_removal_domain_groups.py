"""Removing a person from ARGUS, and groups by e-mail domain (docs/dangerous-actions.md, docs/domain-groups.md).

Signing in goes through the real identity code with the identity provider's check replaced by a table of claims."""
import secrets
import uuid
from urllib.parse import quote

import jwt
import pytest
from fastapi.testclient import TestClient

import app.auth as auth
from app.db import SessionLocal
from app.main import app
from app.models.api_token import ApiToken
from app.models.group import Group, GroupMember
from app.models.issue import Issue
from app.models.role import RoleBinding
from app.models.user import User
from app.models.workspace import Workspace
from app.services import domain_groups
from app.services.roles import ensure_system_roles
from app.models.role import Role

client = TestClient(app)


@pytest.fixture
def idp(monkeypatch):
    """Sign-in tokens: "Bearer <key>" stands for the claims registered under <key>."""
    claims: dict = {}
    monkeypatch.setattr(auth, "oidc_configured", lambda: True)
    def verify(raw):
        if raw not in claims:
            raise jwt.InvalidTokenError("not a sign-in token")
        return dict(claims[raw])
    monkeypatch.setattr(auth, "verify_oidc_token", verify)

    def person(email, verified=True, iss="https://idp.test/other"):
        key = secrets.token_hex(8)
        claims[key] = {"sub": f"sub-{key}", "iss": iss, "email": email, "name": email.split("@")[0],
                       **({"email_verified": verified} if verified is not None else {})}
        return {"Authorization": f"Bearer {key}"}
    return person


@pytest.fixture
def world():
    t = secrets.token_hex(3)
    db = SessionLocal()
    ensure_system_roles(db)
    ws = Workspace(id=f"dom-{t}", name=f"Domain test {t}")
    admin = User(id=str(uuid.uuid4()), email=f"admin-{t}@argus.test", is_admin=True, active=True)
    db.add_all([ws, admin])
    db.commit()
    out = {"t": t, "ws": ws.id, "admin": admin.id, "admin_email": admin.email}
    db.close()
    yield out
    db = SessionLocal()
    db.query(GroupMember).filter(GroupMember.user_id.in_(
        db.query(User.id).filter(User.email.like(f"%{t}%")))).delete(synchronize_session=False)
    db.query(Group).filter(Group.name.like(f"%{t}%")).delete(synchronize_session=False)
    db.query(User).filter(User.email.like(f"%{t}%")).delete(synchronize_session=False)
    if db.get(Workspace, f"dom-{t}") is not None:
        db.delete(db.get(Workspace, f"dom-{t}"))
    db.commit()
    db.close()


def as_admin(monkeypatch, w):
    from app.auth import OidcIdentity, get_identity
    db = SessionLocal()
    user = db.get(User, w["admin"])
    db.expunge(user)
    db.close()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=user, claims={})
    return lambda: app.dependency_overrides.pop(get_identity, None)


# ------------------------------------------------------------------ domains

def test_domains_are_checked_and_matched_as_written():
    assert domain_groups.normalise(["INFN.it", "@lnf.infn.it", "*.infn.it", "infn.it"]) == \
        ["infn.it", "lnf.infn.it", "*.infn.it"]
    for bad in ("gmail", "*.it", "*", "infn .it", "http://infn.it"):
        with pytest.raises(domain_groups.DomainError):
            domain_groups.normalise([bad])
    assert domain_groups.matches("a@infn.it", ["infn.it"])
    assert not domain_groups.matches("a@lnf.infn.it", ["infn.it"])          # exact: not its subdomains
    assert domain_groups.matches("a@lnf.infn.it", ["*.infn.it"])
    assert not domain_groups.matches("a@infn.it", ["*.infn.it"])            # subdomains only
    assert not domain_groups.matches("a@notinfn.it", ["*.infn.it", "infn.it"])
    assert not domain_groups.matches("a@gmail.com", ["*.infn.it", "infn.it"])


def test_a_group_by_domain_lets_in_verified_infn_addresses_and_not_gmail(world, idp, monkeypatch):
    t = world["t"]
    db = SessionLocal()
    group = Group(uid=str(uuid.uuid4()), name=f"INFN people {t}", source="local", active=True)
    db.add(group)
    viewer = db.scalar(__import__("sqlalchemy").select(Role).where(Role.name == "Viewer"))
    db.add(RoleBinding(workspace_id=world["ws"], subject_type="group", subject_id=group.uid, role_id=viewer.id,
                       created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)))
    db.commit()
    gid = group.uid
    db.close()

    infn, lnf, gmail, unverified = (idp(f"rossi-{t}@infn.it"), idp(f"bianchi-{t}@lnf.infn.it"),
                                    idp(f"verdi-{t}@gmail.com"), idp(f"neri-{t}@pi.infn.it", verified=False))
    for h in (infn, lnf, gmail, unverified):                       # each signs in once before the rule exists
        assert client.get("/v1/me", headers=h).status_code == 200
    ws = {"X-Workspace-Id": world["ws"]}
    assert client.get("/v1/schemas", headers={**infn, **ws}).status_code == 403

    done = as_admin(monkeypatch, world)
    try:
        r = client.put(f"/v1/groups/{gid}/domains", json={"domains": ["infn.it", "*.infn.it"]})
        assert r.status_code == 200 and r.json()["preview"] is True
        assert r.json()["would_be_in_it"] == 2 and r.json()["unverified"] == 1    # Neri: not verified
        db = SessionLocal()
        assert db.get(Group, gid).email_domains is None                            # a preview changes nothing
        db.close()
        r = client.put(f"/v1/groups/{gid}/domains", json={"domains": ["infn.it", "*.infn.it"], "confirm": True})
        assert r.status_code == 200 and r.json()["added"] == 2
        assert client.delete(f"/v1/groups/{gid}/members/{_uid(f'rossi-{t}@infn.it')}",
                             headers=ws).status_code == 409            # in it by address: not removed by hand
    finally:
        done()

    assert client.get("/v1/schemas", headers={**infn, **ws}).status_code == 200      # Viewer, through the group
    assert client.get("/v1/schemas", headers={**lnf, **ws}).status_code == 200
    assert client.get("/v1/schemas", headers={**gmail, **ws}).status_code == 403     # Gmail: nothing
    assert client.get("/v1/schemas", headers={**unverified, **ws}).status_code == 403

    # A new person from the domain is in it from their first sign-in; one who moves to Gmail leaves it.
    newcomer = idp(f"gialli-{t}@lngs.infn.it")
    assert client.get("/v1/schemas", headers={**newcomer, **ws}).status_code == 200

    # The rule taken away: everyone in it by address is out.
    done = as_admin(monkeypatch, world)
    try:
        r = client.put(f"/v1/groups/{gid}/domains", json={"domains": [], "confirm": True})
        assert r.status_code == 200 and r.json()["removed"] == 3
    finally:
        done()
    assert client.get("/v1/schemas", headers={**infn, **ws}).status_code == 403


def test_only_an_administrator_signed_in_sets_a_groups_domains(world, idp):
    t = world["t"]
    db = SessionLocal()
    group = Group(uid=str(uuid.uuid4()), name=f"G {t}", source="local", active=True)
    db.add(group)
    db.commit()
    gid = group.uid
    db.close()
    someone = idp(f"someone-{t}@infn.it")
    r = client.put(f"/v1/groups/{gid}/domains", headers=someone, json={"domains": ["infn.it"], "confirm": True})
    assert r.status_code == 403


def _uid(email):
    db = SessionLocal()
    uid = db.scalar(__import__("sqlalchemy").select(User.id).where(User.email == email))
    db.close()
    return uid


# ------------------------------------------------------------------ removal

def test_removing_a_person_takes_away_everything_that_lets_them_in_and_keeps_their_name(world, idp, monkeypatch):
    t = world["t"]
    them = idp(f"leaving-{t}@infn.it")
    assert client.get("/v1/me", headers=them).status_code == 200
    uid = _uid(f"leaving-{t}@infn.it")
    db = SessionLocal()
    contributor = db.scalar(__import__("sqlalchemy").select(Role).where(Role.name == "Contributor"))
    import datetime as dt
    db.add(RoleBinding(workspace_id=world["ws"], subject_type="user", subject_id=uid, role_id=contributor.id,
                       created_at=dt.datetime.now(dt.timezone.utc)))
    group = Group(uid=str(uuid.uuid4()), name=f"Team {t}", source="local", active=True)
    db.add(group)
    db.flush()
    db.add(GroupMember(group_uid=group.uid, user_id=uid, source="local"))
    db.add(Issue(uid=str(uuid.uuid4()), workspace_id=world["ws"], title=f"Open one {t}", state="new", assignee=uid))
    db.add(Issue(uid=str(uuid.uuid4()), workspace_id=world["ws"], title=f"Done one {t}", state="closed", assignee=uid))
    raw = secrets.token_urlsafe(12)
    db.add(ApiToken(kind="personal", user_id=uid, token_hash=auth.hash_token(raw)))
    db.commit()
    db.close()
    pat = {"Authorization": f"Bearer {raw}", "X-Workspace-Id": world["ws"]}
    assert client.get("/v1/schemas", headers=pat).status_code == 200

    # A token, even an administrator's personal one with every scope, cannot remove anybody.
    r = client.delete(f"/v1/admin/users/{uid}", headers={**pat, "X-Confirm-User": quote(f"leaving-{t}@infn.it")})
    assert r.status_code == 403

    done = as_admin(monkeypatch, world)
    try:
        p = client.get(f"/v1/admin/users/{uid}/removal").json()
        assert p["blocked"] is None and p["roles"] == [world["ws"]] and p["groups_left"] == [f"Team {t}"]
        assert p["personal_tokens"] == 1 and p["open_tickets_count"] == 1
        for typed in (None, "leaving", "someone@infn.it"):
            h = {"X-Confirm-User": quote(typed)} if typed else {}
            r = client.delete(f"/v1/admin/users/{uid}", headers=h)
            assert r.status_code == 428 and r.json()["detail"]["code"] == "confirm_user_email"
        r = client.delete(f"/v1/admin/users/{uid}", headers={"X-Confirm-User": quote(f" LEAVING-{t}@infn.it ")})
        assert r.status_code == 200, r.text
        # Not twice, not oneself, not the last administrator.
        assert client.delete(f"/v1/admin/users/{uid}", headers={"X-Confirm-User": quote(f"leaving-{t}@infn.it")}
                             ).status_code == 409
        assert client.get(f"/v1/admin/users/{world['admin']}/removal").json()["blocked"]
    finally:
        done()

    assert client.get("/v1/me", headers=them).status_code == 403                    # signing in is refused
    assert client.get("/v1/schemas", headers=pat).status_code == 401                 # the token is revoked
    db = SessionLocal()
    user = db.get(User, uid)
    assert user is not None and user.removed_at is not None and not user.active     # the row stays: history keeps it
    assert db.scalar(__import__("sqlalchemy").select(RoleBinding.id).where(RoleBinding.subject_id == uid)) is None
    assert db.scalar(__import__("sqlalchemy").select(GroupMember.id).where(GroupMember.user_id == uid)) is None
    issues = {i.title: i.assignee for i in db.scalars(__import__("sqlalchemy").select(Issue).where(
        Issue.workspace_id == world["ws"]))}
    assert issues[f"Open one {t}"] is None and issues[f"Done one {t}"] == uid       # open work released, history kept
    db.query(Issue).filter(Issue.workspace_id == world["ws"]).delete()
    db.query(ApiToken).filter(ApiToken.user_id == uid).delete()
    db.commit()
    db.close()


def test_a_removed_person_is_not_put_back_in_a_group_by_domain(world, idp, monkeypatch):
    t = world["t"]
    db = SessionLocal()
    group = Group(uid=str(uuid.uuid4()), name=f"Dom {t}", source="local", active=True, email_domains=["infn.it"])
    db.add(group)
    db.commit()
    gid = group.uid
    db.close()
    them = idp(f"gone-{t}@infn.it")
    assert client.get("/v1/me", headers=them).status_code == 200
    uid = _uid(f"gone-{t}@infn.it")
    done = as_admin(monkeypatch, world)
    try:
        assert client.delete(f"/v1/admin/users/{uid}", headers={"X-Confirm-User": quote(f"gone-{t}@infn.it")}
                             ).status_code == 200
        db = SessionLocal()
        domain_groups.sync_group(db, db.get(Group, gid))
        db.commit()
        assert db.scalar(__import__("sqlalchemy").select(GroupMember.id).where(GroupMember.user_id == uid)) is None
        db.close()
    finally:
        done()


def test_a_provider_that_gives_out_a_domains_addresses_vouches_for_them(world, idp, monkeypatch):
    """INFN AAI says email_verified false, but it gives out the INFN addresses: an address there that it signs in
    counts as verified. The same address from another provider that does not verify it does not; nor does an
    address of another domain from INFN AAI."""
    import app.auth_oidc as auth_oidc
    aai = "https://idp.test/realms/aai"
    monkeypatch.setattr(auth_oidc, "PROVIDERS", {
        aai: {"jwks_uri": "x", "audience": ("argus",), "email_domains": auth_oidc.email_domains_of("infn.it,*.infn.it")},
        "https://idp.test/other": {"jwks_uri": "y", "audience": ("argus",), "email_domains": ()}})
    t = world["t"]
    cases = {f"aai-{t}@lnf.infn.it": (aai, False, True), f"aai2-{t}@infn.it": (aai, None, True),
             f"other-{t}@infn.it": ("https://idp.test/other", False, False),
             f"elsewhere-{t}@cern.ch": (aai, False, False), f"gmail-{t}@gmail.com": ("https://idp.test/other", True, True)}
    for email, (iss, claim, _) in cases.items():
        assert client.get("/v1/me", headers=idp(email, verified=claim, iss=iss)).status_code == 200
    db = SessionLocal()
    got = {u.email: u.email_verified for u in db.scalars(__import__("sqlalchemy").select(User).where(
        User.email.in_(list(cases))))}
    db.close()
    assert got == {e: v for e, (_, _, v) in cases.items()}
    assert auth_oidc.email_domains_of("infn.it, *.it, not a domain") == ("infn.it",)      # invalid ones never trusted
