"""How a person names a piece of equipment: what the scan lookup and the search boxes match.

A unit is known by its key, its name, every label it carries (a QR code, a barcode, a former key it had
before a rename or a merge, an alias such as an old Service Desk address) and the identifiers written on
it: serial, inventory number, MAC. The scan lookup matches a whole value; a search box matches part of
one. An identifier attribute the viewer may not see on a type is never matched there (I-ACL-1).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.asset_subresources import AssetLabel

# Attribute names that hold an identifier written on the unit, as imports and forms name them.
IDENTIFIER_ATTRS = ("serial", "serial_number", "inventory", "inventory_number", "mac", "asset_tag")


def _blocked_schemas(db: Session, grants, attr: str, restricted: Optional[dict] = None) -> Optional[list[str]]:
    """The types on which this attribute is restricted from the viewer; None when nothing is restricted.
    `restricted` is visibility.restricted_by_type(), when the caller already has it."""
    if grants is None or getattr(grants, "everything", False):
        return None
    if restricted is None:
        from app.services.visibility import restricted_by_type
        restricted = restricted_by_type(db)
    blocked = [uid for uid, fields in restricted.items()
               if attr in fields and not grants.allows(fields[attr])]
    return blocked or None


def attribute_match(db: Session, grants, match) -> object:
    """Any identifier attribute for which `match(column)` holds, where the viewer may see that attribute."""
    restricted = None
    if grants is not None and not getattr(grants, "everything", False):
        from app.services.visibility import restricted_by_type
        restricted = restricted_by_type(db)
    clauses = []
    for attr in IDENTIFIER_ATTRS:
        clause = match(Asset.attributes[attr].astext)
        blocked = _blocked_schemas(db, grants, attr, restricted)
        clauses.append(and_(clause, Asset.schema_uid.notin_(blocked)) if blocked else clause)
    return or_(*clauses)


def label_match(match) -> object:
    """Records carrying a label of any type for which `match(value)` holds."""
    return Asset.uid.in_(select(AssetLabel.asset_uid).where(match(AssetLabel.value)))


def text_clause(db: Session, grants, q: str) -> object:
    """A search box: the key, name, a label or an identifier contains `q`, ignoring case."""
    like = f"%{q.strip()}%"
    if not q.strip():
        return false()
    return or_(Asset.key.ilike(like), Asset.name.ilike(like), label_match(lambda c: c.ilike(like)),
               attribute_match(db, grants, lambda c: c.ilike(like)))


def exact_clause(db: Session, grants, value: str) -> object:
    """A scanned or typed identifier, whole, ignoring case: key, uid, any label, serial, inventory, MAC."""
    v = value.strip().lower()
    mac = v.replace("-", ":")
    return or_(func.lower(Asset.key) == v, Asset.uid == value.strip(),
               label_match(lambda c: func.lower(c) == v),
               attribute_match(db, grants, lambda c: or_(func.lower(c) == v, func.lower(c) == mac)))
