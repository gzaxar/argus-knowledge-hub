"""A Product Model's vendor is one fact: the Vendor record it points at (`vendor_ref`).

The type also keeps the company's name as text (`vendor`), which search, the facets and imports read. It follows the
reference and is never a second opinion. Every writer goes through the ledger's service, so it is settled there:

    - a reference given: the name is the record's;
    - the reference cleared: the name goes with it;
    - only a name given (an import, Ask ARGUS, an API client): it is linked to the Vendor of that name or alias, when
      exactly one has it. A name no Vendor has stays as text, with no reference.

A Vendor renamed takes the name of its models with it (app/ledger/service.py).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models.asset import Asset

MODEL = "Product Model"
VENDOR = "Vendor"


def find_vendor(db: Session, workspace_id: str, name: Optional[str]) -> Optional[Asset]:
    """The one live Vendor going by this name or alias: this workspace's first, then those shared with it. None when
    no one does, or several do: a company is not guessed."""
    from app.models.asset_subresources import AssetLabel
    from app.services.catalogue_mapping import norm
    key = norm(name)
    if not key:
        return None
    live = select(Asset).where(Asset.type == VENDOR, Asset.deleted_at.is_(None),
                               Asset.record_status.notin_(("Retired", "Merged")))
    for scope in (Asset.workspace_id == workspace_id, and_(Asset.workspace_id != workspace_id, Asset.is_global.is_(True))):
        vendors = {v.uid: v for v in db.scalars(live.where(scope))}
        named = {uid for uid, v in vendors.items() if norm(v.name) == key}
        if not named and vendors:
            named = {uid for uid, alias in db.execute(select(AssetLabel.asset_uid, AssetLabel.value).where(
                AssetLabel.asset_uid.in_(list(vendors)), AssetLabel.type == "alias")) if norm(alias) == key}
        if named:
            return vendors[next(iter(named))] if len(named) == 1 else None
    return None


def settle_new(db: Session, workspace_id: str, type_name: str, attributes: dict) -> dict:
    """A new record's attributes, with its vendor settled."""
    if type_name != MODEL:
        return attributes
    out = dict(attributes)
    ref = out.get("vendor_ref")
    if ref:
        vendor = db.get(Asset, ref) if isinstance(ref, str) else None
        if vendor is not None:
            out["vendor"] = vendor.name
    elif out.get("vendor"):
        vendor = find_vendor(db, workspace_id, out["vendor"])
        if vendor is not None:
            out["vendor"], out["vendor_ref"] = vendor.name, vendor.uid
    return out


def settle_changes(db: Session, record: Asset, changes: dict) -> dict:
    """An edit's changes (`attr:` predicates), with the record's vendor settled."""
    if record.type != MODEL or not ({"attr:vendor_ref", "attr:vendor"} & set(changes)):
        return changes
    out = dict(changes)
    current = record.attributes or {}
    if "attr:vendor_ref" in out:
        ref = out["attr:vendor_ref"]
        vendor = db.get(Asset, ref) if ref and isinstance(ref, str) else None
        if vendor is not None:
            out["attr:vendor"] = vendor.name
        elif not ref:
            out["attr:vendor"] = None
    else:
        text = out["attr:vendor"]
        vendor = find_vendor(db, record.workspace_id, text) if text else None
        if vendor is not None:
            out["attr:vendor"], out["attr:vendor_ref"] = vendor.name, vendor.uid
        elif current.get("vendor_ref"):
            out["attr:vendor_ref"] = None
    return {p: v for p, v in out.items() if p in changes or current.get(p[5:]) != v}


def models_of(db: Session, vendor: Asset) -> list[Asset]:
    """The vendor's models in its own workspace whose name for it is out of step."""
    return [m for m in db.scalars(select(Asset).where(
        Asset.workspace_id == vendor.workspace_id, Asset.type == MODEL, Asset.deleted_at.is_(None),
        Asset.attributes["vendor_ref"].astext == vendor.uid))
        if (m.attributes or {}).get("vendor") != vendor.name]


def ensure(db: Session, workspace_id: str, schema_uid: str, name: str, actor: str) -> tuple[Asset, bool]:
    """The catalogue's Vendor of this name or alias, or a new one under it."""
    import uuid
    from app.ledger import service as ledger_service
    from app.services import asset_keys
    from app.services.catalogue_mapping import norm
    name = (name or "").strip()
    if not norm(name):
        raise ValueError("a vendor needs a name")
    found = find_vendor(db, workspace_id, name)
    if found is not None:
        return found, False
    from app.models.schema import Schema
    schema = db.get(Schema, schema_uid)
    uid = str(uuid.uuid4())
    return ledger_service.create_record(db, workspace_id, actor, uid=uid, schema_uid=schema_uid,
                                        key=asset_keys.allocate(db, workspace_id, schema), name=name,
                                        type_name=VENDOR, attributes={}, is_global=True), True
