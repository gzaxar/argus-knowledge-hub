"""Sites: a laboratory workspace whose places — buildings, halls, rooms, their floors and plans — its facility
workspaces use (docs/sites.md).

* A workspace with role `site` owns the places; a facility workspace names it in `site_id`. One level: a site is
  at no site, the catalogue is neither a site nor at one, a workspace is not at itself — so no cycle can form.
* A site's record is **site-shared** (`assets.site_shared`) when it is a place — of type Location or a type
  below it — and neither it nor a place it is inside (the indoor *it is in* chain) is withheld
  (`assets.site_withheld`). Site-shared records are visible from the site's facilities and only from them
  (services/visibility.py); `is_global` is something else: every workspace.
* `refresh` keeps `site_shared` right. It is called when a place is created or retyped in a site (the flush
  guard below), placed inside another or taken out (services/indoor.py), withheld or released, moved by a
  transfer, and when a workspace's role or site changes.
"""
from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.schema import Schema
from app.models.workspace import Workspace

ROLE = "site"
PLACE_ROOT = "Location"


class SiteProblem(ValueError):
    pass


# --------------------------------------------------------------------------- the relationship

def site_of(db: Session, workspace_id: Optional[str]) -> Optional[str]:
    if not workspace_id:
        return None
    return db.scalar(select(Workspace.site_id).where(Workspace.id == workspace_id))


def facilities(db: Session, site_id: str) -> list[str]:
    return list(db.scalars(select(Workspace.id).where(Workspace.site_id == site_id).order_by(Workspace.id)))


def is_site(db: Session, workspace_id: Optional[str]) -> bool:
    return bool(workspace_id) and db.scalar(select(Workspace.role).where(Workspace.id == workspace_id)) == ROLE


def set_role(db: Session, workspace_id: str, site: bool) -> list[str]:
    """Make a workspace a site, or stop it being one. Returns the facility placements that end (rule 3)."""
    from app.catalogue.system import ROLE as CATALOGUE
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise SiteProblem(f"no workspace {workspace_id!r}")
    if site:
        if ws.role == CATALOGUE:
            raise SiteProblem(f"{workspace_id} is the installation's catalogue: it cannot be a site")
        if ws.site_id:
            raise SiteProblem(f"{workspace_id} is at the site {ws.site_id}: a site is at no site")
        ws.role = ROLE
        db.flush()
        refresh(db, workspace_id)
        return []
    if ws.role != ROLE:
        return []
    if facilities(db, workspace_id):
        raise SiteProblem(f"{workspace_id} has facilities ({', '.join(facilities(db, workspace_id))}): "
                          f"set them at another site, or at none, first")
    ws.role = None
    db.flush()
    return refresh(db, workspace_id)


def set_site(db: Session, workspace_id: str, site_id: Optional[str], *, actor: Optional[str] = None) -> list[str]:
    """Put a facility at a site, move it to another, or take it from its site. Returns the placements that end
    because places stop being shared with it."""
    from app.catalogue.system import ROLE as CATALOGUE
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise SiteProblem(f"no workspace {workspace_id!r}")
    if site_id:
        site = db.get(Workspace, site_id)
        if site is None:
            raise SiteProblem(f"no workspace {site_id!r}")
        if site_id == workspace_id:
            raise SiteProblem("a workspace is not at itself")
        if site.role != ROLE:
            raise SiteProblem(f"{site_id} is not a site: make it one first")
        if ws.role == ROLE:
            raise SiteProblem(f"{workspace_id} is a site: a site is at no site")
        if ws.role == CATALOGUE:
            raise SiteProblem(f"{workspace_id} is the installation's catalogue: it is at no site")
    before = ws.site_id
    ws.site_id = site_id or None
    db.flush()
    ended: list[str] = []
    if before and before != ws.site_id:
        ended = withdraw_placements(db, before, only_workspace=workspace_id, actor=actor,
                                    reason=f"{workspace_id} is no longer at the site {before}")
    return ended


# --------------------------------------------------------------------------- which records are places

def place_types(db: Session) -> set[str]:
    """The uids of the types that are places: Location, and every type below it, wherever they are kept."""
    rows = db.execute(select(Schema.uid, Schema.name, Schema.parent_schema_uid).where(Schema.applies_to == "objects")).all()
    children: dict = {}
    roots = []
    for uid, name, parent in rows:
        children.setdefault(parent, []).append(uid)
        if name == PLACE_ROOT:
            roots.append(uid)
    out, todo = set(), list(roots)
    while todo:
        uid = todo.pop()
        if uid not in out:
            out.add(uid)
            todo.extend(children.get(uid, []))
    return out


# --------------------------------------------------------------------------- keeping site_shared right

def _containers(db: Session, uids: Iterable[str]) -> dict[str, Optional[str]]:
    """record uid -> the place it is directly inside (its confirmed placement), for these records."""
    from app.models.indoor import IndoorPlacement
    uids = list(uids)
    if not uids:
        return {}
    return dict(db.execute(select(IndoorPlacement.asset_uid, IndoorPlacement.place_uid).where(
        IndoorPlacement.asset_uid.in_(uids), IndoorPlacement.state == "confirmed")).all())


def _shared_now(db: Session, site_id: str) -> dict[str, bool]:
    """Every record of the site -> whether it should be site-shared."""
    types = place_types(db)
    rows = db.execute(select(Asset.uid, Asset.schema_uid, Asset.site_withheld).where(
        Asset.workspace_id == site_id, Asset.deleted_at.is_(None))).all()
    withheld = {uid for uid, _, w in rows if w}
    inside = _containers(db, [uid for uid, _, _ in rows])
    memo: dict[str, bool] = {}

    def blocked(uid: str, depth: int = 0) -> bool:
        if uid in memo:
            return memo[uid]
        if uid in withheld:
            memo[uid] = True
            return True
        parent = inside.get(uid)
        memo[uid] = False                    # a cycle (never made by the indoor rules) stops here
        result = bool(parent) and depth < 16 and blocked(parent, depth + 1)
        memo[uid] = result
        return result

    return {uid: (schema in types and not blocked(uid)) for uid, schema, _ in rows}


def refresh(db: Session, site_id: Optional[str], *, actor: Optional[str] = None,
            reason: Optional[str] = None) -> list[str]:
    """Bring `site_shared` up to date for every record of a workspace (a site's places shared, everything else
    not); end the facility placements in what stops being shared. Returns the placements ended."""
    if not site_id:
        return []
    db.flush()                               # sessions here do not flush by themselves before a query
    site = is_site(db, site_id)
    wanted = _shared_now(db, site_id) if site else {}
    rows = db.scalars(select(Asset).where(Asset.workspace_id == site_id, Asset.site_shared.is_(True))).all() \
        if not site else db.scalars(select(Asset).where(Asset.workspace_id == site_id)).all()
    stopped = []
    for a in rows:
        should = wanted.get(a.uid, False)
        if a.site_shared != should:
            if a.site_shared and not should:
                stopped.append(a.uid)
            a.site_shared = should
    db.flush()
    if not stopped:
        return []
    return withdraw_placements(db, site_id, places=stopped, actor=actor,
                               reason=reason or "the site stopped sharing it")


def withdraw_placements(db: Session, site_id: str, *, places: Optional[list[str]] = None,
                        only_workspace: Optional[str] = None, actor: Optional[str] = None,
                        reason: str) -> list[str]:
    """End the placements of other workspaces' records in these places of the site (all of them when `places`
    is None), on their floors or on their plans (rule 3). The record keeps the position the plan gave it; its
    history says why. Returns the placements ended."""
    from app.models.indoor import FloorPlan, IndoorPlacement, PlaceLevel
    from app.services import indoor
    db.flush()
    if places is None:
        places = list(db.scalars(select(Asset.uid).where(Asset.workspace_id == site_id)))
    if not places:
        return []
    levels = set(db.scalars(select(PlaceLevel.uid).where(PlaceLevel.place_uid.in_(places))))
    plans = set(db.scalars(select(FloorPlan.uid).where(FloorPlan.place_uid.in_(places))))
    cond = IndoorPlacement.place_uid.in_(places)
    if levels:
        cond = cond | IndoorPlacement.level_uid.in_(levels)
    if plans:
        cond = cond | IndoorPlacement.plan_uid.in_(plans)
    q = select(IndoorPlacement).where(IndoorPlacement.state == "confirmed", IndoorPlacement.workspace_id != site_id, cond)
    if only_workspace:
        q = q.where(IndoorPlacement.workspace_id == only_workspace)
    ended = []
    at = indoor.now()
    for p in db.scalars(q):
        p.state, p.valid_until = "withdrawn", at
        record = db.get(Asset, p.asset_uid)
        place = db.get(Asset, p.place_uid) if p.place_uid else None
        if record is not None:
            indoor._history(db, record, f"No longer placed in {place.name if place else 'the place'}: {reason}",
                            actor, at)
        ended.append(p.uid)
    db.flush()
    return ended


def affected_by_withdrawal(db: Session, site_id: str, places: list[str],
                           only_workspace: Optional[str] = None) -> list[dict]:
    """The facility placements a withdrawal would end, for a preview: by workspace, with the record and place."""
    from app.models.indoor import FloorPlan, IndoorPlacement, PlaceLevel
    if not places:
        return []
    db.flush()
    levels = set(db.scalars(select(PlaceLevel.uid).where(PlaceLevel.place_uid.in_(places))))
    plans = set(db.scalars(select(FloorPlan.uid).where(FloorPlan.place_uid.in_(places))))
    cond = IndoorPlacement.place_uid.in_(places)
    if levels:
        cond = cond | IndoorPlacement.level_uid.in_(levels)
    if plans:
        cond = cond | IndoorPlacement.plan_uid.in_(plans)
    q = select(IndoorPlacement, Asset).join(Asset, Asset.uid == IndoorPlacement.asset_uid).where(
        IndoorPlacement.state == "confirmed", IndoorPlacement.workspace_id != site_id, cond)
    if only_workspace:
        q = q.where(IndoorPlacement.workspace_id == only_workspace)
    return [{"workspace_id": p.workspace_id, "record": {"uid": a.uid, "key": a.key, "name": a.name},
             "place_uid": p.place_uid, "plan_uid": p.plan_uid} for p, a in db.execute(q)]


def inside(db: Session, place_uid: str) -> list[str]:
    """A place and every place inside it, by the indoor *it is in* chain, in the place's workspace."""
    from app.models.indoor import IndoorPlacement
    db.flush()
    place = db.get(Asset, place_uid)
    if place is None:
        return []
    out, frontier = [place_uid], [place_uid]
    seen = {place_uid}
    while frontier:
        rows = db.scalars(select(IndoorPlacement.asset_uid).join(Asset, Asset.uid == IndoorPlacement.asset_uid).where(
            IndoorPlacement.place_uid.in_(frontier), IndoorPlacement.state == "confirmed",
            Asset.workspace_id == place.workspace_id)).all()
        frontier = [u for u in rows if u not in seen]
        seen.update(frontier)
        out.extend(frontier)
    return out


# --------------------------------------------------------------------------- the flush guard

def _on_flush(session, flush_context, instances) -> None:
    """A record created in a site, or retyped or moved into one, gets `site_shared` there and then; one that
    leaves a site stops being shared. Containment and withholding are kept by `refresh` where they change."""
    from sqlalchemy import inspect as sa_inspect
    touched = []
    for o in session.new:
        if isinstance(o, Asset):
            touched.append(o)
    for o in session.dirty:
        if isinstance(o, Asset):
            st = sa_inspect(o)
            if st.attrs.schema_uid.history.has_changes() or st.attrs.workspace_id.history.has_changes():
                touched.append(o)
    if not touched:
        return
    with session.no_autoflush:
        sites = set(session.scalars(select(Workspace.id).where(Workspace.role == ROLE)))
        if not sites and not any(o.site_shared for o in touched):
            return
        types = place_types(session) if any(o.workspace_id in sites for o in touched) else set()
        for o in touched:
            should = o.workspace_id in sites and o.schema_uid in types and not o.site_withheld
            if should and o.uid:
                parent = _containers(session, [o.uid]).get(o.uid)
                hops = 0
                while parent and hops < 16 and should:
                    p = session.get(Asset, parent)
                    if p is None:
                        break
                    if p.site_withheld:
                        should = False
                    parent = _containers(session, [parent]).get(parent)
                    hops += 1
            if o.site_shared != should:
                o.site_shared = should


def install_guard() -> None:
    from sqlalchemy import event
    from sqlalchemy.orm import Session as _Session
    if not event.contains(_Session, "before_flush", _on_flush):
        event.listen(_Session, "before_flush", _on_flush)


install_guard()
