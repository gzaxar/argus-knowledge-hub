"""Groups by e-mail domain: everyone signed in with a verified address in one of a group's domains is in it.

An installation that lets in several identity providers (INFN's, Google) can give the people of an organisation
some access without giving it to every account that can sign in: a role goes to a group whose domains are, say,
`infn.it` and `*.infn.it`, and whoever signs in with a verified `…@lnf.infn.it` address has it; a Gmail account
does not. The group is an ordinary local group in every other way — roles here and site-wide, access reviews,
"who has access" — and may have members added by hand as well.

Membership is kept as rows of source "domain", brought up to date at every sign-in and whenever a group's domains
change, so every place that reads group membership sees it. An address counts only when the identity provider says
it is verified (`email_verified`): an unverified one could be anybody's.
"""
import re
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.group import Group, GroupMember
from app.models.user import User

SOURCE = "domain"
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
PATTERN = re.compile(rf"^(\*\.)?{_LABEL}(?:\.{_LABEL})+$")


class DomainError(ValueError):
    pass


def normalise(patterns: Iterable[str]) -> list[str]:
    """The domains as stored: lower case, without `@`, each one checked; duplicates dropped, order kept."""
    out = []
    for raw in patterns:
        p = (raw or "").strip().lower().lstrip("@")
        if not p:
            continue
        if p.startswith("*@"):
            p = p[2:]
        if not PATTERN.match(p):
            raise DomainError(f"“{raw}” is not a domain: write infn.it for that domain, *.infn.it for its subdomains")
        if p.count(".") < 1 or p.startswith("*.") and p.count(".") < 2:
            raise DomainError(f"“{raw}” is too wide: name an organisation's domain")
        if p not in out:
            out.append(p)
    return out


def matches(email: Optional[str], patterns: Iterable[str]) -> bool:
    """Whether the address is in one of the domains: `infn.it` matches that domain exactly, `*.infn.it` any of its
    subdomains (`lnf.infn.it`, `pi.infn.it`), not the domain itself."""
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1].strip().lower()
    for p in patterns or ():
        if p.startswith("*."):
            if domain.endswith(p[1:]) and domain != p[2:]:
                return True
        elif domain == p:
            return True
    return False


def counts(user: User) -> bool:
    """Whether this person's address may be matched: verified by the identity provider, and the person not removed."""
    return bool(user.email_verified) and user.removed_at is None and bool(user.active)


def domain_groups(db: Session) -> list[Group]:
    return list(db.scalars(select(Group).where(Group.email_domains.isnot(None), Group.active.is_(True),
                                               Group.source == "local")))


def sync_user(db: Session, user: User, groups: Optional[list[Group]] = None) -> tuple[list[str], list[str]]:
    """Bring this person's domain memberships up to date. (groups joined, groups left)"""
    groups = domain_groups(db) if groups is None else groups
    have = {m.group_uid: m for m in db.scalars(select(GroupMember).where(GroupMember.user_id == user.id,
                                                                        GroupMember.source == SOURCE))}
    joined, left = [], []
    wanted = {g.uid for g in groups if counts(user) and matches(user.email, g.email_domains or [])}
    for uid in wanted - set(have):
        # Already a member by hand: that row stands, and leaving the domain does not take it away.
        if db.scalar(select(GroupMember.id).where(GroupMember.group_uid == uid, GroupMember.user_id == user.id)):
            continue
        db.add(GroupMember(group_uid=uid, user_id=user.id, source=SOURCE))
        joined.append(uid)
    for uid, row in have.items():
        if uid not in wanted:
            db.delete(row)
            left.append(uid)
    if joined or left:
        db.flush()
    return joined, left


def sync_group(db: Session, group: Group) -> dict:
    """Bring a group's domain members up to date with its domains (after they change). Who is in it by hand stays."""
    rows = {m.user_id: m for m in db.scalars(select(GroupMember).where(GroupMember.group_uid == group.uid,
                                                                       GroupMember.source == SOURCE))}
    by_hand = set(db.scalars(select(GroupMember.user_id).where(GroupMember.group_uid == group.uid,
                                                               GroupMember.source != SOURCE)))
    patterns = (group.email_domains or []) if group.active else []
    wanted = set()
    if patterns:
        for user in db.scalars(select(User).where(User.email_verified.is_(True), User.removed_at.is_(None),
                                                  User.active.is_(True))):
            if matches(user.email, patterns):
                wanted.add(user.id)
    added = [u for u in wanted - set(rows) - by_hand]
    for uid in added:
        db.add(GroupMember(group_uid=group.uid, user_id=uid, source=SOURCE))
    removed = [u for u in rows if u not in wanted]
    for uid in removed:
        db.delete(rows[uid])
    db.flush()
    return {"added": len(added), "removed": len(removed), "members": len(wanted - by_hand) + len(by_hand)}


def unverified(db: Session, patterns: list[str]) -> int:
    """People who signed in with an address in these domains that their identity provider did not say is verified:
    they are not counted, and an administrator should know why."""
    n = 0
    for user in db.scalars(select(User).where(User.removed_at.is_(None), User.active.is_(True),
                                              User.email_verified.isnot(True))):
        if user.last_login_at is not None and matches(user.email, patterns):
            n += 1
    return n
