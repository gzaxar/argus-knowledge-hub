from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.asset import Asset, Relation
from app.models.schema import Schema
from app.models.user import User
from app.services.attribute_validation import (
    _descendant_schema_uids,
    _is_reference_visible,
    effective_attributes,
)
from app.services.relations import rebuild_asset_relations

REFERENCE_LIKE_TYPES = ("reference", "user")


def _resolve_reference(db: Session, value: str, allowed_schema_uids: set[str], workspace_id: str) -> bool:
    target = db.get(Asset, value)
    return bool(
        target is not None
        and target.schema_uid in allowed_schema_uids
        and _is_reference_visible(db, target, workspace_id)
    )


def _relink_reference(db: Session, value: str, allowed_schema_uids: set[str], workspace_id: str) -> Optional[str]:
    match = db.scalars(
        select(Asset).where(
            Asset.schema_uid.in_(allowed_schema_uids),
            or_(Asset.key == value, Asset.name == value),
        )
    ).first()
    if match is not None and _is_reference_visible(db, match, workspace_id):
        return match.uid
    return None


def _relink_user(db: Session, value: str) -> Optional[str]:
    match = db.scalars(select(User).where(or_(User.email == value, User.name == value))).first()
    return match.id if match else None


def relink_workspace(db: Session, workspace_id: str) -> dict:
    """Attempt to re-resolve every reference/user attribute value that
    doesn't currently point at a real target (matching by key/name for
    references, by email/name for users) — the common case being Jira
    imports whose values are the source system's display labels rather than
    our uids. Also materializes a Relation row for every resolved reference
    and resyncs every asset's relation cache. Never deletes anything; only
    rewrites values it can confidently match."""
    assets = db.scalars(select(Asset).where(Asset.workspace_id == workspace_id)).all()
    relinked_values = 0
    relinked_assets = 0

    # A resolved reference and a Relation row are two separate facts, and
    # only the second one feeds the Inbound/Outbound panel — an import that
    # could not match a reference key (or matched it across workspaces)
    # left the attribute looking fine while the object showed no relations
    # at all. Materializing them here is add-only, so hand-made relations
    # and ones whose attribute has since been cleared are left untouched.
    existing_relations = {
        (r.from_asset_uid, r.to_asset_uid, r.relation_type)
        for r in db.scalars(select(Relation).where(Relation.workspace_id == workspace_id))
    }
    relations_created = 0
    touched_uids: set[str] = set()

    for asset in assets:
        schema = db.get(Schema, asset.schema_uid) if asset.schema_uid else None
        asset_changed = False
        if schema is not None:
            attrs = dict(asset.attributes or {})
            for attr in effective_attributes(db, schema):
                attr_type = attr.get("type")
                if attr_type not in REFERENCE_LIKE_TYPES:
                    continue
                key = attr.get("key") or attr.get("name")
                if not key or key not in attrs or attrs[key] in (None, ""):
                    continue
                raw = attrs[key]
                is_list = isinstance(raw, list)
                values = raw if is_list else [raw]
                allowed_schema_uids: set[str] = set()
                if attr_type == "reference":
                    ref_schema_uid = attr.get("referenceSchemaUid")
                    if not ref_schema_uid:
                        continue
                    allowed_schema_uids = {ref_schema_uid}
                    if attr.get("includeChildren"):
                        allowed_schema_uids |= _descendant_schema_uids(db, ref_schema_uid)

                new_values = []
                row_changed = False
                for v in values:
                    if not isinstance(v, str) or v == "":
                        new_values.append(v)
                        continue
                    if attr_type == "reference":
                        if _resolve_reference(db, v, allowed_schema_uids, workspace_id):
                            new_values.append(v)
                            continue
                        resolved = _relink_reference(db, v, allowed_schema_uids, workspace_id)
                    else:
                        if db.get(User, v) is not None:
                            new_values.append(v)
                            continue
                        resolved = _relink_user(db, v)
                    if resolved:
                        new_values.append(resolved)
                        row_changed = True
                        relinked_values += 1
                    else:
                        new_values.append(v)
                if row_changed:
                    attrs[key] = new_values if is_list else new_values[0]
                    asset_changed = True

                # A reference the ledger turns into an edge itself (instance of, located in) gets no second,
                # field-named one here.
                from app.services.asset_types import REFERENCE_RELATIONS
                if attr_type == "reference" and key not in REFERENCE_RELATIONS:
                    relation_type = attr.get("name") or key
                    for v in new_values:
                        if not isinstance(v, str) or v == "":
                            continue
                        if not _resolve_reference(db, v, allowed_schema_uids, workspace_id):
                            continue
                        dedup_key = (asset.uid, v, relation_type)
                        if dedup_key in existing_relations:
                            continue
                        existing_relations.add(dedup_key)
                        db.add(Relation(
                            workspace_id=workspace_id,
                            from_asset_uid=asset.uid,
                            to_asset_uid=v,
                            relation_type=relation_type,
                        ))
                        relations_created += 1
                        touched_uids.add(asset.uid)
                        touched_uids.add(v)
            if asset_changed:
                asset.attributes = attrs
                relinked_assets += 1

    # Caches are rebuilt only after every relation exists, otherwise an
    # asset processed early would be cached before a later asset creates an
    # inbound edge to it. Targets in another workspace are included: a
    # cross-workspace reference gives them an inbound edge too.
    db.flush()
    for asset in assets:
        rebuild_asset_relations(db, asset.uid)
    for uid in touched_uids:
        target = db.get(Asset, uid)
        if target is not None and target.workspace_id != workspace_id:
            rebuild_asset_relations(db, uid)

    db.commit()
    return {
        "assets_scanned": len(assets),
        "assets_updated": relinked_assets,
        "values_relinked": relinked_values,
        "relations_created": relations_created,
    }


def generate_integrity_report(db: Session, workspace_id: str) -> dict:
    """Missing references (attribute values that resolve to nothing),
    dangling objects (relations this workspace created whose target still
    exists but is no longer visible — e.g. a global flag was turned off),
    and orphaned objects (assets with no inbound or outbound relation at
    all, from any workspace, placed in nothing and holding nothing, and with no document or ticket about them)."""
    assets = db.scalars(select(Asset).where(Asset.workspace_id == workspace_id)).all()
    asset_uids = {a.uid for a in assets}

    missing_references = []
    for asset in assets:
        schema = db.get(Schema, asset.schema_uid) if asset.schema_uid else None
        if schema is None:
            continue
        for attr in effective_attributes(db, schema):
            attr_type = attr.get("type")
            if attr_type not in REFERENCE_LIKE_TYPES:
                continue
            key = attr.get("key") or attr.get("name")
            if not key:
                continue
            value = (asset.attributes or {}).get(key)
            if value in (None, ""):
                continue
            allowed_schema_uids: set[str] = set()
            if attr_type == "reference":
                ref_schema_uid = attr.get("referenceSchemaUid")
                if ref_schema_uid:
                    allowed_schema_uids = {ref_schema_uid}
                    if attr.get("includeChildren"):
                        allowed_schema_uids |= _descendant_schema_uids(db, ref_schema_uid)
            for v in (value if isinstance(value, list) else [value]):
                if v in (None, ""):
                    continue
                if attr_type == "reference":
                    resolved = (
                        bool(allowed_schema_uids)
                        and isinstance(v, str)
                        and _resolve_reference(db, v, allowed_schema_uids, workspace_id)
                    )
                else:
                    resolved = isinstance(v, str) and db.get(User, v) is not None
                if not resolved:
                    missing_references.append({
                        "asset_uid": asset.uid, "asset_name": asset.name, "asset_key": asset.key,
                        "attribute_key": key, "attribute_name": attr.get("name", key),
                        "attribute_type": attr_type, "value": str(v),
                    })

    own_relations = db.scalars(select(Relation).where(Relation.workspace_id == workspace_id)).all()
    dangling_objects = []
    for r in own_relations:
        target = db.get(Asset, r.to_asset_uid)
        if target is not None and not _is_reference_visible(db, target, workspace_id):
            dangling_objects.append({
                "relation_id": r.id, "from_asset_uid": r.from_asset_uid,
                "to_asset_uid": r.to_asset_uid, "relation_type": r.relation_type,
                "reason": "target exists but is no longer visible from this workspace",
            })

    touching_relations = db.scalars(
        select(Relation).where(
            or_(Relation.workspace_id == workspace_id, Relation.to_asset_uid.in_(asset_uids))
        )
    ).all()
    connected_uids = set()
    for r in touching_relations:
        connected_uids.add(r.from_asset_uid)
        connected_uids.add(r.to_asset_uid)
    # Not only relations connect a record: a hall that rooms are placed inside, a room placed in it, the equipment a
    # document is about or a ticket is raised on. Offered for deletion as "orphaned", a building with its halls in it
    # was one click from going.
    from app.models.document import DocumentRelation
    from app.models.indoor import IndoorPlacement
    from app.models.issue import Issue
    for asset_uid, place_uid in db.execute(select(IndoorPlacement.asset_uid, IndoorPlacement.place_uid).where(
            IndoorPlacement.state == "confirmed", or_(IndoorPlacement.asset_uid.in_(asset_uids),
                                                      IndoorPlacement.place_uid.in_(asset_uids)))):
        connected_uids.update(u for u in (asset_uid, place_uid) if u)
    connected_uids.update(db.scalars(select(DocumentRelation.to_uid).where(
        DocumentRelation.to_type == "asset", DocumentRelation.to_uid.in_(asset_uids))))
    connected_uids.update(db.scalars(select(Issue.asset_uid).where(Issue.asset_uid.in_(asset_uids))))
    orphaned_objects = [
        {"asset_uid": a.uid, "name": a.name, "key": a.key}
        for a in assets if a.uid not in connected_uids
    ]

    return {
        "missing_references": missing_references,
        "dangling_objects": dangling_objects,
        "orphaned_objects": orphaned_objects,
        "counts": {
            "assets_scanned": len(assets),
            "missing_references": len(missing_references),
            "dangling_objects": len(dangling_objects),
            "orphaned_objects": len(orphaned_objects),
        },
    }


def cleanup_workspace(db: Session, workspace_id: str, options: dict) -> dict:
    """Applies only the requested remediations, computed fresh (never off a
    possibly-stale report the caller might be holding)."""
    report = generate_integrity_report(db, workspace_id)
    result = {"cleared_references": 0, "deleted_orphaned_objects": 0, "removed_dangling_relations": 0}

    if options.get("clear_missing_references"):
        by_asset: dict[str, list[dict]] = {}
        for item in report["missing_references"]:
            by_asset.setdefault(item["asset_uid"], []).append(item)
        for asset_uid, items in by_asset.items():
            asset = db.get(Asset, asset_uid)
            if asset is None:
                continue
            attrs = dict(asset.attributes or {})
            for item in items:
                key = item["attribute_key"]
                current = attrs.get(key)
                if isinstance(current, list):
                    attrs[key] = [v for v in current if str(v) != item["value"]]
                else:
                    attrs[key] = None
                result["cleared_references"] += 1
            asset.attributes = attrs
        db.commit()

    if options.get("delete_orphaned_objects"):
        for item in report["orphaned_objects"]:
            asset = db.get(Asset, item["asset_uid"])
            if asset is not None:
                db.delete(asset)
                result["deleted_orphaned_objects"] += 1
        db.commit()

    if options.get("remove_dangling_relations"):
        for item in report["dangling_objects"]:
            relation = db.get(Relation, item["relation_id"])
            if relation is not None:
                db.delete(relation)
                result["removed_dangling_relations"] += 1
        db.commit()

    return result
