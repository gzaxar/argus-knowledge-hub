"""People given access by their e-mail address, before they have ever signed in.

An administrator of a workspace types the addresses; each person who is not known yet is added, gets the role in
that workspace, and is told by e-mail when asked. Their first sign-in with that address claims the account and
the access that waits on it (auth._resolve_oidc_user), whatever the case of the letters.
"""
import re
import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.role import Role, RoleBinding
from app.models.user import User
from app.models.workspace import Workspace

ADDRESS = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")
MAX_AT_ONCE = 200


class InviteError(ValueError):
    pass


def addresses(text: str) -> tuple[list[str], list[str]]:
    """(the addresses, what is not one) in a list pasted from anywhere: commas, semicolons, new lines,
    `Name <address>`."""
    found, bad = [], []
    for part in re.split(r"[,;\n]+", text or ""):
        part = part.strip()
        if not part:
            continue
        m = re.search(r"<([^>]+)>", part)
        address = (m.group(1) if m else part).strip().strip('"').lower()
        (found if ADDRESS.match(address) else bad).append(address if ADDRESS.match(address) else part)
    return list(dict.fromkeys(found)), bad


def person(db: Session, email: str) -> tuple[User, bool]:
    """The person with this address, or a new one waiting for their first sign-in. (user, made now)"""
    user = db.scalar(select(User).where(func.lower(User.email) == email)
                     .order_by(User.oidc_sub.isnot(None), User.created_at).limit(1))
    if user is not None:
        return user, False
    user = User(id=str(uuid.uuid4()), email=email, source="oidc", active=True)
    db.add(user)
    db.flush()
    return user, True


def invitation(workspace: Workspace, role: Optional[Role], email: str, inviter: Optional[str], note: Optional[str],
               link: str, group=None) -> tuple[str, str]:
    by = inviter or "An administrator"
    if group is not None:
        what = f"{by} added you to the group \u201c{group.name}\u201d"
        what += (f", which has the {role.name} role in the ARGUS workspace \u201c{workspace.name}\u201d."
                 if role else f" in ARGUS (workspace \u201c{workspace.name}\u201d).")
    else:
        what = f"{by} gave you the {role.name} role in the ARGUS workspace \u201c{workspace.name}\u201d."
    lines = [what, ""]
    if note and note.strip():
        lines += [note.strip(), ""]
    lines += [f"Open ARGUS and sign in with this address, {email}:", link or "(ask for the address of ARGUS)", "",
              "Signing in with a different address does not give you this access: if you use another one, ask "
              f"{by} to invite that one instead."]
    return f"[ARGUS] You have access to {workspace.name}", "\n".join(lines) + "\n"


def invite(db: Session, workspace_id: str, text: str, role_id: Optional[str], *, created_by: Optional[str],
           inviter: Optional[str], send_email: bool, note: Optional[str] = None, group=None) -> dict:
    """Add each address not known yet, grant it the role here, and e-mail it when asked. The caller commits.
    What happened to each address is said, and an address that is not one stops nothing else.

    With a `group`, each person joins it instead, and the role (when given) goes to the group once: everyone in
    it, now or later, has it here."""
    from datetime import datetime, timezone
    from app.services import notify
    from app.services.roles import ensure_system_roles
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise InviteError("No such workspace.")
    ensure_system_roles(db)
    role = db.get(Role, role_id) if role_id else None
    if role is None and (role_id or group is None):
        raise InviteError("No such role.")
    found, bad = addresses(text)
    if not found:
        raise InviteError("No e-mail address in what was given." + (f" Not addresses: {', '.join(bad[:5])}." if bad else ""))
    if len(found) > MAX_AT_ONCE:
        raise InviteError(f"At most {MAX_AT_ONCE} addresses at a time.")
    link = f"{notify.web_url()}/?ws={workspace_id}" if notify.web_url() else ""

    def grant(subject_type: str, subject_id: str) -> bool:
        if role is None:
            return False
        new = db.scalar(select(RoleBinding.id).where(
            RoleBinding.workspace_id == workspace_id, RoleBinding.subject_type == subject_type,
            RoleBinding.subject_id == subject_id, RoleBinding.role_id == role.id)) is None
        if new:
            db.add(RoleBinding(workspace_id=workspace_id, subject_type=subject_type, subject_id=subject_id,
                               role_id=role.id, created_at=datetime.now(timezone.utc), created_by=created_by))
        return new

    group_granted = grant("group", group.uid) if group is not None else False
    results = []
    for email in found:
        user, made = person(db, email)
        if group is not None:
            joined = add_member(db, group, user)
            granted = joined
        else:
            joined = False
            granted = grant("user", user.id)
        row = {"email": email, "user_id": user.id, "added": made, "granted": granted, "joined": joined,
               "signed_in": user.oidc_sub is not None or user.last_login_at is not None, "emailed": False, "error": None}
        if send_email:
            subject, body = invitation(workspace, role, email, inviter, note, link, group)
            try:
                notify.send_plain(email, subject, body)
                row["emailed"] = True
            except notify.MailError as e:
                row["error"] = str(e)
        results.append(row)
    db.flush()
    return {"workspace_id": workspace_id, "role_id": role.id if role else None, "role_name": role.name if role else None,
            "group_uid": group.uid if group else None, "group_name": group.name if group else None,
            "group_granted": group_granted, "people": results, "not_addresses": bad}


def add_member(db: Session, group, user: User) -> bool:
    """`user` into a local group; False when already in it."""
    from app.models.group import GroupMember
    if db.scalar(select(GroupMember.id).where(GroupMember.group_uid == group.uid, GroupMember.user_id == user.id)):
        return False
    db.add(GroupMember(group_uid=group.uid, user_id=user.id, source="local"))
    db.flush()
    return True
