"""Workspaces, people and their roles, from the command line.

Run it through the wrapper from the repository root (it calls this inside the
api container):

    tools/argus-admin workspace list
    tools/argus-admin workspace create sparc --name SPARC
    tools/argus-admin workspace token sparc
    tools/argus-admin user add mario.rossi@lnf.infn.it --name "Mario Rossi" --password s3cret
    tools/argus-admin user admin mario.rossi@lnf.infn.it on
    tools/argus-admin role list
    tools/argus-admin grant mario.rossi@lnf.infn.it contributor sparc
    tools/argus-admin revoke mario.rossi@lnf.infn.it contributor sparc
    tools/argus-admin access mario.rossi@lnf.infn.it
    tools/argus-admin dev-setup

Every command is safe to repeat: what already exists is reported and left as
it is. A person is known here by email. Their account is created before they
ever sign in, and their first sign-in with that email lands on it, roles and
all (auth.py, _resolve_oidc_user).

`user add --password` also creates the login in the local Keycloak, for
development only. With INFN's own identity provider, people already have
their login there; add them here without --password.
"""
import argparse
import os
import runpy
import secrets
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, ".")

from sqlalchemy import select  # noqa: E402

from app.auth import hash_token  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models.api_token import ApiToken  # noqa: E402
from app.models.role import Role, RoleBinding  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services.roles import ensure_system_roles  # noqa: E402

# The workspaces the Keycloak test users are bound to (scripts/seed_dev_users.py).
DEV_WORKSPACES = [("sparc", "SPARC"), ("euaps", "EuAPS"), ("eli", "ELI"), ("btf", "BTF"),
                  ("accelerator-infn", "Accelerator-INFN")]


class Fail(Exception):
    """A mistake the person can fix; printed without a traceback."""


def _table(rows: list[tuple], header: tuple) -> None:
    if not rows:
        print("(none)")
        return
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    for r in [header, *rows]:
        print("  ".join(str(v).ljust(w) for v, w in zip(r, widths)).rstrip())


def _workspace(db, workspace_id: str) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        known = ", ".join(w.id for w in db.scalars(select(Workspace).order_by(Workspace.id))) or "none yet"
        raise Fail(f"No workspace '{workspace_id}'. Existing: {known}.\n"
                   f"Create it with: tools/argus-admin workspace create {workspace_id} --name \"...\"")
    return ws


def _user(db, email: str) -> User:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        raise Fail(f"No user {email}. Add them with: tools/argus-admin user add {email}")
    return user


def _role(db, role_id: str) -> Role:
    ensure_system_roles(db)
    db.flush()
    role = db.get(Role, role_id.lower())
    if role is None:
        known = ", ".join(r.id for r in db.scalars(select(Role).order_by(Role.rank)))
        raise Fail(f"No role '{role_id}'. Roles: {known}.")
    return role


# --- workspaces --------------------------------------------------------------

def workspace_list(db, _args) -> None:
    rows = []
    for ws in db.scalars(select(Workspace).order_by(Workspace.id)):
        people = len(db.scalars(select(RoleBinding).where(RoleBinding.workspace_id == ws.id)).all())
        rows.append((ws.id, ws.name, "yes" if ws.is_global else "", people))
    _table(rows, ("ID", "NAME", "GLOBAL", "GRANTS"))


def create_workspace(db, workspace_id: str, name: str, is_global: bool = False) -> bool:
    """Creates the workspace with the defaults the web UI gives one (global
    values, ticket and document types), or fills in missing defaults on an
    existing one. True when it was new."""
    ws = db.get(Workspace, workspace_id)
    created = ws is None
    if created:
        db.add(Workspace(id=workspace_id, name=name, is_global=is_global))
        db.flush()
    # The core-facility package, through the installer (recorded); unchanged on a workspace that has it.
    from app.packages.install import install
    install(db, workspace_id, ["core-facility"], actor="argus-admin")
    return created


def workspace_create(db, args) -> None:
    workspace_id = args.id.strip()
    if not workspace_id or any(c.isspace() for c in workspace_id):
        raise Fail("A workspace id has no spaces, e.g. 'sparc' or 'lnf-euaps'. Put the display name in --name.")
    created = create_workspace(db, workspace_id, args.name or workspace_id, args.is_global)
    db.commit()
    print(f"{'Created' if created else 'Already there, defaults checked:'} {workspace_id}")
    if created:
        print(f"Next: tools/argus-admin grant <email> owner {workspace_id}")


def workspace_token(db, args) -> None:
    _workspace(db, args.id)
    raw = secrets.token_urlsafe(32)
    db.add(ApiToken(workspace_id=args.id, token_hash=hash_token(raw), label=args.label))
    db.commit()
    print(f"API token for {args.id} (shown once; store it like a password):\n{raw}")


# --- people ------------------------------------------------------------------

def user_list(db, _args) -> None:
    rows = []
    for u in db.scalars(select(User).order_by(User.email)):
        grants = db.scalars(select(RoleBinding).where(RoleBinding.subject_type == "user",
                                                      RoleBinding.subject_id == u.id)).all()
        rows.append((u.email, u.name or "", "yes" if u.is_admin else "", "" if u.active else "no",
                     ", ".join(f"{b.role_id}@{b.workspace_id}" for b in grants)))
    _table(rows, ("EMAIL", "NAME", "ADMIN", "ACTIVE", "ROLES"))


def user_add(db, args) -> None:
    email = args.email.strip().lower()
    if "@" not in email:
        raise Fail(f"'{args.email}' is not an email address. People are known by their email.")
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(id=str(uuid.uuid4()), email=email, name=args.name, is_admin=args.admin,
                    source="oidc", active=True)
        db.add(user)
        print(f"Added {email}{' (admin)' if args.admin else ''}")
    else:
        if args.name:
            user.name = args.name
        if args.admin:
            user.is_admin = True
        print(f"Already there: {email}{' (now admin)' if args.admin else ''}")
    db.commit()
    if args.password:
        _keycloak_user(email, args.name or "", args.username or email.split("@")[0], args.password)
    if not user.is_admin:
        print(f"Next: tools/argus-admin grant {email} <role> <workspace>   (roles: tools/argus-admin role list)")


def user_admin(db, args) -> None:
    user = _user(db, args.email)
    user.is_admin = args.state == "on"
    db.commit()
    print(f"{user.email} is {'now an admin' if user.is_admin else 'no longer an admin'}")


def _keycloak_user(email: str, name: str, username: str, password: str) -> None:
    """The login itself, in the local development Keycloak."""
    import requests
    base = os.environ.get("KEYCLOAK_URL", "http://keycloak:8080").rstrip("/")
    realm = os.environ.get("KEYCLOAK_REALM", "argus-dev")
    try:
        tok = requests.post(f"{base}/realms/master/protocol/openid-connect/token", timeout=10, data={
            "client_id": "admin-cli", "grant_type": "password",
            "username": os.environ.get("KEYCLOAK_ADMIN", "admin"),
            "password": os.environ.get("KEYCLOAK_ADMIN_PASSWORD", "admin")})
        tok.raise_for_status()
    except requests.RequestException as exc:
        raise Fail(f"The hub account exists, but Keycloak at {base} could not be reached to create the login "
                   f"({exc}). Is the keycloak service running?")
    headers = {"Authorization": f"Bearer {tok.json()['access_token']}"}
    users = f"{base}/admin/realms/{realm}/users"
    found = requests.get(users, headers=headers, params={"email": email, "exact": "true"}, timeout=10).json()
    first, _, last = name.partition(" ")
    if found:
        uid = found[0]["id"]
        print(f"Keycloak login already there: {found[0]['username']}; password reset")
    else:
        r = requests.post(users, headers=headers, timeout=10, json={
            "username": username, "email": email, "emailVerified": True, "enabled": True,
            "firstName": first or username, "lastName": last or "-"})
        if r.status_code == 409:
            raise Fail(f"Keycloak already has the username '{username}' for another email. Choose one with --username.")
        r.raise_for_status()
        uid = r.headers["Location"].rsplit("/", 1)[-1]
        print(f"Keycloak login created: {username}")
    requests.put(f"{users}/{uid}/reset-password", headers=headers, timeout=10,
                 json={"type": "password", "value": password, "temporary": False}).raise_for_status()
    print(f"Sign in with 'INFN login' as {username} (or {email}).")


# --- roles -------------------------------------------------------------------

def role_list(db, _args) -> None:
    ensure_system_roles(db)
    db.commit()
    rows = []
    for r in db.scalars(select(Role).order_by(Role.rank, Role.id)):
        rows.append((r.id, r.description or "", "" if r.is_system else "custom"))
    _table(rows, ("ROLE", "WHAT IT ALLOWS", ""))


def grant(db, args) -> None:
    user, role, ws = _user(db, args.email), _role(db, args.role), _workspace(db, args.workspace)
    exists = db.scalar(select(RoleBinding).where(
        RoleBinding.workspace_id == ws.id, RoleBinding.subject_type == "user",
        RoleBinding.subject_id == user.id, RoleBinding.role_id == role.id))
    if exists is not None:
        print(f"{user.email} is already {role.id} on {ws.id}")
        return
    db.add(RoleBinding(workspace_id=ws.id, subject_type="user", subject_id=user.id, role_id=role.id,
                       created_at=datetime.now(timezone.utc), created_by="argus_admin.py"))
    db.commit()
    print(f"{user.email} is now {role.id} on {ws.id}")


def revoke(db, args) -> None:
    user, ws = _user(db, args.email), _workspace(db, args.workspace)
    binding = db.scalar(select(RoleBinding).where(
        RoleBinding.workspace_id == ws.id, RoleBinding.subject_type == "user",
        RoleBinding.subject_id == user.id, RoleBinding.role_id == args.role.lower()))
    if binding is None:
        print(f"{user.email} does not hold {args.role} on {ws.id}; nothing to do")
        return
    db.delete(binding)
    db.commit()
    print(f"{user.email} is no longer {args.role} on {ws.id}")


def access(db, args) -> None:
    user = _user(db, args.email)
    print(f"{user.email}{' — admin: everything, in every workspace' if user.is_admin else ''}")
    rows = [(b.workspace_id, b.role_id, b.created_by or "")
            for b in db.scalars(select(RoleBinding).where(RoleBinding.subject_type == "user",
                                                          RoleBinding.subject_id == user.id)
                                .order_by(RoleBinding.workspace_id))]
    _table(rows, ("WORKSPACE", "ROLE", "GRANTED BY"))


def dev_setup(db, _args) -> None:
    """The local development hub, ready for 'INFN login' with the test users."""
    for workspace_id, name in DEV_WORKSPACES:
        created = create_workspace(db, workspace_id, name)
        print(f"{'created' if created else 'exists '} workspace {workspace_id}")
    db.commit()
    db.close()
    runpy.run_path("scripts/seed_dev_users.py", run_name="__main__")


def main() -> None:
    p = argparse.ArgumentParser(prog="argus-admin", description="Workspaces, people and their roles.",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="examples:\n" + __doc__.split("\n\n")[2])
    sub = p.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    w = sub.add_parser("workspace", help="list, create, or make an API token for a workspace")
    wsub = w.add_subparsers(dest="action", required=True)
    wsub.add_parser("list", help="every workspace").set_defaults(fn=workspace_list)
    c = wsub.add_parser("create", help="create one, with the defaults the web UI gives it")
    c.add_argument("id", help="short id used in URLs and keys, e.g. sparc (cannot change later)")
    c.add_argument("--name", help="display name, e.g. 'SPARC Lab' (default: the id)")
    c.add_argument("--global", dest="is_global", action="store_true", help="shared with every workspace")
    c.set_defaults(fn=workspace_create)
    t = wsub.add_parser("token", help="make an API token for scripts and automation")
    t.add_argument("id")
    t.add_argument("--label", default="argus-admin")
    t.set_defaults(fn=workspace_token)

    u = sub.add_parser("user", help="list or add people, or make one an admin")
    usub = u.add_subparsers(dest="action", required=True)
    usub.add_parser("list", help="everyone, with their roles").set_defaults(fn=user_list)
    a = usub.add_parser("add", help="add a person by email")
    a.add_argument("email")
    a.add_argument("--name", help="full name, e.g. 'Mario Rossi'")
    a.add_argument("--admin", action="store_true", help="administrator of the whole hub")
    a.add_argument("--password", help="also create their login in the local dev Keycloak")
    a.add_argument("--username", help="Keycloak username (default: the part of the email before @)")
    a.set_defaults(fn=user_add)
    ad = usub.add_parser("admin", help="make someone an admin, or not")
    ad.add_argument("email")
    ad.add_argument("state", choices=["on", "off"])
    ad.set_defaults(fn=user_admin)

    r = sub.add_parser("role", help="the roles that can be granted")
    rsub = r.add_subparsers(dest="action", required=True)
    rsub.add_parser("list", help="every role and what it allows").set_defaults(fn=role_list)

    for name, fn, text in (("grant", grant, "give a person a role on a workspace"),
                           ("revoke", revoke, "take a role away")):
        g = sub.add_parser(name, help=text)
        g.add_argument("email")
        g.add_argument("role", help="e.g. viewer, contributor, curator, owner (see: role list)")
        g.add_argument("workspace")
        g.set_defaults(fn=fn)

    ac = sub.add_parser("access", help="what a person can do, and where")
    ac.add_argument("email")
    ac.set_defaults(fn=access)

    sub.add_parser("dev-setup", help="local development: test workspaces and the six Keycloak test users"
                   ).set_defaults(fn=dev_setup)

    args = p.parse_args()
    db = SessionLocal()
    try:
        args.fn(db, args)
    except Fail as exc:
        db.rollback()
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
