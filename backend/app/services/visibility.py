"""Which objects a workspace can see.

Two different things are shared, and they are not the same thing:

  types      A global *type* (a schema) can be used from every workspace: it is
             how one catalogue defines "Camera" or "Product Model" once for every
             beamline. That is about the definition.
  objects    An object is visible outside the workspace that owns it only if it is
             itself flagged global. Being of a global type does not do it.

The two used to be the same rule, so every camera of every beamline was visible
in every other one, and a workspace's own list drowned in the others'. What is
meant to be shared — a product model, a vendor, a person, a company, an
inventory document — is flagged; a beamline's own cameras and pumps are not, and
stay in the beamline that has them. Anything created in a global workspace is
flagged when it is made, the way its types and documents already are.

Restricted classes (asset-model-revision §4.3, I-ACL-1)
--------------------------------------------------------
A record (object or ticket) whose `classification` attribute is
`restricted:<class>` — costs, personnel, security incidents, safety
investigations, sensitive designs — is visible only to a viewer granted that
class. The grants travel with the request (`current_grants()`); a helper can
also be given them explicitly. Outside a request nothing restricted is seen.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

from sqlalchemy import and_, not_, or_, select

from app.models.asset import Asset
from app.models.issue import Issue

RESTRICTED_PREFIX = "restricted:"
RESTRICTED_CLASSES = ("costs", "personnel", "security_incident", "safety_investigation", "sensitive_design")


def restricted_classes() -> dict[str, str]:
    """Every restricted class: ARGUS's own, and those the shipped template packages declare
    (`restricted_classes:` — confidential contract terms, unpublished inventions…). id -> description."""
    from app.packages import defaults
    from app.packages.loader import available
    out = {c: "" for c in RESTRICTED_CLASSES}
    for pid in defaults.ordered():
        for c in available()[pid].section("restricted_classes") or []:
            out.setdefault(str(c["id"]), str(c.get("description") or ""))
    return out


class Grants(frozenset):
    """The restricted classes a viewer may see. `Grants.all()` for admins."""
    everything = False

    @classmethod
    def all(cls) -> "Grants":
        g = cls()
        g.everything = True
        return g

    def allows(self, cls_name: Optional[str]) -> bool:
        return cls_name is None or self.everything or cls_name in self


NONE = Grants()
# Set once per request by app.auth.bind_grants, so every read path — routers,
# the hub, the graph, MCP tools — filters by the same viewer without each
# call site having to pass it.
_CURRENT: ContextVar[Grants] = ContextVar("restricted_grants", default=NONE)


def current_grants() -> Grants:
    return _CURRENT.get()


def set_current_grants(grants: Grants) -> None:
    _CURRENT.set(grants)


def restricted_class(record) -> Optional[str]:
    value = ((getattr(record, "attributes", None) or {}).get("classification") or "")
    if isinstance(value, str) and value.startswith(RESTRICTED_PREFIX):
        return value[len(RESTRICTED_PREFIX):]
    return None


def can_see(record, grants: Optional[Grants] = None) -> bool:
    return (grants if grants is not None else current_grants()).allows(restricted_class(record))


def _restriction_clause(model, grants: Optional[Grants]):
    grants = grants if grants is not None else current_grants()
    if grants.everything:
        return None
    cls = model.attributes["classification"].astext
    allowed = [cls.is_(None), not_(cls.like(f"{RESTRICTED_PREFIX}%"))]
    if grants:
        allowed.append(cls.in_([f"{RESTRICTED_PREFIX}{g}" for g in grants]))
    return or_(*allowed)


def asset_visible_in(asset: Asset, workspace_id: str, grants: Optional[Grants] = None) -> bool:
    return (asset.workspace_id == workspace_id or bool(asset.is_global)) and can_see(asset, grants)


def visible_assets_clause(workspace_id: str, grants: Optional[Grants] = None):
    base = or_(Asset.workspace_id == workspace_id, Asset.is_global.is_(True))
    extra = _restriction_clause(Asset, grants)
    return base if extra is None else and_(base, extra)


def visible_issues_clause(grants: Optional[Grants] = None):
    """Only the restriction part: tickets are workspace-scoped by their callers."""
    extra = _restriction_clause(Issue, grants)
    return extra if extra is not None else Issue.uid.isnot(None)


def restriction_clause(model, grants: Optional[Grants] = None):
    """Just the restricted-class filter for `model` (Asset or Issue)."""
    extra = _restriction_clause(model, grants)
    return extra if extra is not None else model.uid.isnot(None)


# --------------------------------------------------------------------------- field level

def restricted_fields(db, schema_uid: Optional[str]) -> dict[str, str]:
    """attribute key -> restricted class, from the type and its ancestors
    (an attribute definition with `"restricted": "<class>"`)."""
    from app.models.schema import Schema
    out: dict[str, str] = {}
    seen: set = set()
    uid = schema_uid
    while uid and uid not in seen:
        seen.add(uid)
        schema = db.get(Schema, uid)
        if schema is None:
            break
        for attr in schema.attributes or []:
            key = attr.get("key") or attr.get("name")
            if key and attr.get("restricted"):
                out.setdefault(key, str(attr["restricted"]))
        uid = schema.parent_schema_uid
    return out


def hidden_fields(db, record, grants: Optional[Grants] = None) -> set[str]:
    grants = grants if grants is not None else current_grants()
    if grants.everything:
        return set()
    return {k for k, cls in restricted_fields(db, getattr(record, "schema_uid", None)).items()
            if not grants.allows(cls)}


def redacted_attributes(db, record, grants: Optional[Grants] = None) -> dict:
    """The record's attributes without the fields the viewer may not see."""
    hidden = hidden_fields(db, record, grants)
    return {k: v for k, v in (record.attributes or {}).items() if k not in hidden}


def visible_uids(db, uids, grants: Optional[Grants] = None) -> list[str]:
    """Those of these asset uids the viewer may see — for relation lists, so
    a restricted neighbour is not even named by uid."""
    uids = list(uids or [])
    if not uids:
        return []
    grants = grants if grants is not None else current_grants()
    if grants.everything:
        return uids
    shown = set(db.scalars(select(Asset.uid).where(Asset.uid.in_(uids), restriction_clause(Asset, grants))))
    missing = set(uids) - set(db.scalars(select(Asset.uid).where(Asset.uid.in_(uids))))
    return [u for u in uids if u in shown or u in missing]
