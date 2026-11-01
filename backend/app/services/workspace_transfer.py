"""Copying or moving types and objects from one workspace to another.

A "type" is a Schema row (asset types, ticket types and document types are
all Schema rows, discriminated by applies_to). An "object" is an Asset,
Document or Issue instance.

Move reassigns workspace_id in place — cheap, and nothing needs a new
identity since Asset.key/Document.code are unique across the whole
installation already, not per workspace. Copy mints new rows with new uids
(and, where the column is globally unique, a new key/code), and only carries
a relation/link over when both of its endpoints are part of the same
transfer — anything left behind is dropped and counted into the job's
warnings rather than left dangling or blocking the transfer.

Reference-typed attribute values that happen to name another object by uid
or key are deliberately left untouched here: services.integrity.
relink_workspace already re-resolves those in a workspace, and duplicating
that logic for a second time in this file would only give it a second place
to drift out of sync.
"""
import os
import shutil
import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.asset import Asset, Relation
from app.models.asset_subresources import AssetComment, AssetHistory, AssetLabel, AssetTicket
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.models.icon import Icon
from app.models.issue import Issue, IssueComment, IssueHistory, IssueLink
from app.models.schema import Schema
from app.models.transfer_job import TransferJob
from app.services.asset_ticket_links import ticket_key_for
from app.services.document_codes import next_code
from app.services.relations import rebuild_asset_relations_with_neighbors

ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR", "/data/attachments")


def run_transfer(
    job_uid: str,
    source_workspace_id: str,
    target_workspace_id: str,
    mode: str,
    type_uids: list[str],
    include_instances: bool,
    asset_uids: list[str],
    document_uids: list[str],
    issue_uids: list[str],
    include_descendant_types: bool = False,
    force: bool = False,
) -> None:
    db = SessionLocal()
    job = db.get(TransferJob, job_uid)
    try:
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        schema_uids = _resolve_schema_set(db, source_workspace_id, type_uids, include_descendant_types)
        working_assets = set(asset_uids)
        working_documents = set(document_uids)
        working_issues = set(issue_uids)
        if include_instances and schema_uids:
            a, d, i = _resolve_instances(db, source_workspace_id, schema_uids)
            working_assets |= a
            working_documents |= d
            working_issues |= i

        if mode == "move":
            _block_on_type_name_conflicts(db, target_workspace_id, schema_uids)
            counts, warnings = _move(
                db, source_workspace_id, target_workspace_id,
                schema_uids, working_assets, working_documents, working_issues,
            )
        else:
            counts, warnings = _copy(
                db, source_workspace_id, target_workspace_id,
                schema_uids, working_assets, working_documents, working_issues, force,
            )

        db.commit()
        job.status = "succeeded"
        job.progress = "Transfer complete"
        job.counts = counts
        job.warnings = warnings
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        db.rollback()
        job = db.get(TransferJob, job_uid)
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


def _resolve_schema_set(
    db: Session, source_workspace_id: str, type_uids: list[str], include_descendant_types: bool = False,
) -> list[str]:
    """type_uids plus every non-global ancestor (always — a child type needs
    its parent to exist), ancestors first, deduped. Descendant types are
    only pulled in when `include_descendant_types` is set — moving/copying a
    base type doesn't have to drag everything built on it unless asked to.
    Descendants are appended breadth-first, after their own parent, so the
    schema map in _copy() can always resolve parent_schema_uid in order."""
    ordered: list[str] = []
    seen: set[str] = set()

    def visit_up(uid: str) -> None:
        if uid in seen:
            return
        seen.add(uid)
        schema = db.get(Schema, uid)
        if schema is None or schema.workspace_id != source_workspace_id:
            return
        if schema.parent_schema_uid:
            parent = db.get(Schema, schema.parent_schema_uid)
            if parent is not None and not parent.is_global and parent.workspace_id == source_workspace_id:
                visit_up(parent.uid)
        ordered.append(uid)

    for uid in type_uids:
        visit_up(uid)

    if include_descendant_types:
        frontier = list(ordered)
        while frontier:
            next_frontier: list[str] = []
            for uid in frontier:
                children = db.scalars(
                    select(Schema.uid).where(
                        Schema.parent_schema_uid == uid, Schema.workspace_id == source_workspace_id
                    )
                ).all()
                for child_uid in children:
                    if child_uid in seen:
                        continue
                    seen.add(child_uid)
                    ordered.append(child_uid)
                    next_frontier.append(child_uid)
            frontier = next_frontier

    return ordered


def _resolve_instances(db: Session, source_workspace_id: str, schema_uids: list[str]) -> tuple[set[str], set[str], set[str]]:
    if not schema_uids:
        return set(), set(), set()
    asset_uids = set(db.scalars(
        select(Asset.uid).where(Asset.workspace_id == source_workspace_id, Asset.schema_uid.in_(schema_uids))
    ))
    document_uids = set(db.scalars(
        select(Document.uid).where(Document.workspace_id == source_workspace_id, Document.document_type_uid.in_(schema_uids))
    ))
    issue_uids = set(db.scalars(
        select(Issue.uid).where(Issue.workspace_id == source_workspace_id, Issue.schema_uid.in_(schema_uids))
    ))
    return asset_uids, document_uids, issue_uids


# --------------------------------------------------------------------------
# Move
# --------------------------------------------------------------------------

def _move(
    db: Session, source: str, target: str,
    schema_uids: list[str], asset_uids: set[str], document_uids: set[str], issue_uids: set[str],
) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    counts = {
        "types": 0, "assets": 0, "documents": 0, "issues": 0,
        "relations_dropped": 0, "links_dropped": 0, "icons_dropped": 0,
    }

    for uid in schema_uids:
        schema = db.get(Schema, uid)
        if schema is None or schema.workspace_id != source:
            continue
        schema.workspace_id = target
        counts["types"] += 1
    counts["icons_dropped"] += _move_schema_icons(db, source, target, schema_uids)

    for uid in asset_uids:
        asset = db.get(Asset, uid)
        if asset is None or asset.workspace_id != source:
            continue
        asset.workspace_id = target
        counts["assets"] += 1

    for uid in document_uids:
        doc = db.get(Document, uid)
        if doc is None or doc.workspace_id != source:
            continue
        doc.workspace_id = target
        counts["documents"] += 1

    for uid in issue_uids:
        issue = db.get(Issue, uid)
        if issue is None or issue.workspace_id != source:
            continue
        issue.workspace_id = target
        counts["issues"] += 1
    db.flush()

    # Relations between two assets: keep (and re-stamp) only when both ends
    # moved together, otherwise the edge now crosses the boundary — drop it.
    if asset_uids:
        rebuild_uids: set[str] = set(asset_uids)
        crossing = db.scalars(
            select(Relation).where(
                or_(Relation.from_asset_uid.in_(asset_uids), Relation.to_asset_uid.in_(asset_uids))
            )
        ).all()
        for rel in crossing:
            if rel.from_asset_uid in asset_uids and rel.to_asset_uid in asset_uids:
                rel.workspace_id = target
                continue
            rebuild_uids.add(rel.from_asset_uid)
            rebuild_uids.add(rel.to_asset_uid)
            db.delete(rel)
            counts["relations_dropped"] += 1
        db.flush()
        for uid in rebuild_uids:
            rebuild_asset_relations_with_neighbors(db, uid)

    # Document relations: keep only when the document and its target moved
    # (or already lived in the target) together.
    if document_uids:
        counts["relations_dropped"] += _move_document_relations(db, target, document_uids, schema_uids, asset_uids, issue_uids)
        for uid in document_uids:
            doc = db.get(Document, uid)
            if doc and doc.responsible_service_asset_uid and doc.responsible_service_asset_uid not in asset_uids:
                asset = db.get(Asset, doc.responsible_service_asset_uid)
                if asset is None or asset.workspace_id != target:
                    doc.responsible_service_asset_uid = None
                    counts["links_dropped"] += 1

    # Ticket links: a ticket and its subject asset, or two linked tickets,
    # that don't move together.
    counts["links_dropped"] += _move_ticket_links(db, source, target, asset_uids, issue_uids)
    if issue_uids:
        links = db.scalars(
            select(IssueLink).where(
                or_(IssueLink.from_issue_uid.in_(issue_uids), IssueLink.to_issue_uid.in_(issue_uids))
            )
        ).all()
        for link in links:
            if link.from_issue_uid in issue_uids and link.to_issue_uid in issue_uids:
                continue
            db.delete(link)
            counts["links_dropped"] += 1

    # Attachments carry their own workspace_id, independent of their owner.
    moved_revision_uids = set(db.scalars(
        select(DocumentRevision.uid).where(DocumentRevision.document_uid.in_(document_uids))
    )) if document_uids else set()
    conditions = []
    if asset_uids:
        conditions.append(Attachment.asset_uid.in_(asset_uids))
    if moved_revision_uids:
        conditions.append(Attachment.document_revision_uid.in_(moved_revision_uids))
    if issue_uids:
        conditions.append(Attachment.issue_uid.in_(issue_uids))
    if conditions:
        for att in db.scalars(select(Attachment).where(or_(*conditions))).all():
            att.workspace_id = target

    # Indoors: the places' floors and plans go with them; placements are kept where still reachable
    # (services/indoor_transfer.py).
    from app.services import indoor_transfer
    inside = indoor_transfer.carry_move(db, source, target, set(asset_uids))
    counts.update({f"indoor_{k}": v for k, v in inside.items()})
    if inside["placements_ended"]:
        warnings.append(f"Ended {inside['placements_ended']} indoor placement(s) no longer reachable after the move.")

    if counts["relations_dropped"]:
        warnings.append(f"Dropped {counts['relations_dropped']} relation(s) crossing the workspace boundary.")
    if counts["links_dropped"]:
        warnings.append(f"Dropped {counts['links_dropped']} ticket/document link(s) crossing the workspace boundary.")
    if counts["icons_dropped"]:
        warnings.append(
            f"Unlinked {counts['icons_dropped']} icon(s) still used by a type left behind in the source workspace."
        )
    return counts, warnings


def _block_on_type_name_conflicts(db: Session, target: str, schema_uids: list[str]) -> None:
    """Moving a type into a workspace that already has one with the same
    name at the same level would produce two indistinguishable siblings —
    refuse rather than silently duplicate. Move has no force/merge escape
    hatch (unlike copy): merging here would mean deleting the moved schema
    out from under any of its own left-behind children, which is real data
    loss risk this doesn't take on."""
    conflicts: list[str] = []
    for uid in schema_uids:
        schema = db.get(Schema, uid)
        if schema is None:
            continue
        parent_clause = (
            (Schema.parent_schema_uid == schema.parent_schema_uid) if schema.parent_schema_uid
            else Schema.parent_schema_uid.is_(None)
        )
        existing = db.scalar(
            select(Schema.uid).where(
                Schema.workspace_id == target, Schema.name == schema.name,
                Schema.applies_to == schema.applies_to, parent_clause, Schema.uid != uid,
            )
        )
        if existing is not None:
            conflicts.append(schema.name)
    if conflicts:
        names = ", ".join(sorted(set(conflicts))[:20])
        raise ValueError(
            f"A type named {names} already exists in the target workspace at the same level — "
            "move doesn't merge. Copy with Force overwrite instead, or rename/remove it there first."
        )


def _move_schema_icons(db: Session, source: str, target: str, schema_uids: list[str]) -> int:
    """A non-global icon moves with the moved type(s) only if nothing left
    behind still needs it — otherwise it stays put and the moved type(s)
    lose the reference rather than leave a cross-workspace pointer that
    icons.py's visibility check would just 404 on anyway. A global icon
    needs no change either way: it's already visible from both sides."""
    dropped = 0
    handled: set[str] = set()
    for uid in schema_uids:
        schema = db.get(Schema, uid)
        if schema is None or not schema.icon_uid or schema.icon_uid in handled:
            continue
        icon = db.get(Icon, schema.icon_uid)
        if icon is None or icon.is_global:
            continue
        handled.add(schema.icon_uid)
        used_outside = db.scalar(
            select(Schema.uid).where(Schema.icon_uid == icon.uid, ~Schema.uid.in_(schema_uids))
        ) is not None
        if used_outside:
            for s in db.scalars(select(Schema).where(Schema.icon_uid == icon.uid, Schema.uid.in_(schema_uids))):
                s.icon_uid = None
                dropped += 1
        else:
            icon.workspace_id = target
    return dropped


def _move_document_relations(
    db: Session, target: str, document_uids: set[str],
    schema_uids: list[str], asset_uids: set[str], issue_uids: set[str],
) -> int:
    moved_by_type = {"asset": asset_uids, "document": document_uids, "issue": issue_uids, "schema": set(schema_uids)}
    dropped = 0
    rels = db.scalars(select(DocumentRelation).where(DocumentRelation.from_document_uid.in_(document_uids))).all()
    for rel in rels:
        if rel.to_uid in moved_by_type.get(rel.to_type, set()):
            rel.workspace_id = target
            continue
        db.delete(rel)
        dropped += 1

    incoming = db.scalars(
        select(DocumentRelation).where(
            DocumentRelation.to_type == "document", DocumentRelation.to_uid.in_(document_uids)
        )
    ).all()
    for rel in incoming:
        if rel.from_document_uid in document_uids:
            continue  # already handled above
        db.delete(rel)
        dropped += 1
    return dropped


def _move_ticket_links(db: Session, source: str, target: str, asset_uids: set[str], issue_uids: set[str]) -> int:
    if not asset_uids and not issue_uids:
        return 0
    ticket_key_to_issue: dict[str, str] = {}
    for issue in db.scalars(select(Issue).where(Issue.workspace_id.in_([source, target]))):
        ticket_key_to_issue[ticket_key_for(issue)] = issue.uid

    dropped = 0
    if asset_uids:
        for at in db.scalars(select(AssetTicket).where(AssetTicket.asset_uid.in_(asset_uids))).all():
            linked_issue_uid = ticket_key_to_issue.get(at.ticket_key)
            if linked_issue_uid is not None and linked_issue_uid in issue_uids:
                continue
            if linked_issue_uid is not None:
                issue = db.get(Issue, linked_issue_uid)
                if issue is not None and issue.asset_uid == at.asset_uid:
                    issue.asset_uid = None
            db.delete(at)
            dropped += 1

    for uid in issue_uids:
        issue = db.get(Issue, uid)
        if issue is None or not issue.asset_uid or issue.asset_uid in asset_uids:
            continue
        stale = db.scalar(
            select(AssetTicket).where(
                AssetTicket.asset_uid == issue.asset_uid, AssetTicket.ticket_key == ticket_key_for(issue)
            )
        )
        if stale is not None:
            db.delete(stale)
            dropped += 1
        issue.asset_uid = None
    return dropped


# --------------------------------------------------------------------------
# Copy
# --------------------------------------------------------------------------

def _unique_asset_key(db: Session, base_key: str, used: set[str]) -> str:
    candidate = f"{base_key}-copy"
    n = 2
    while candidate in used or db.scalar(select(Asset.uid).where(Asset.key == candidate)) is not None:
        candidate = f"{base_key}-copy-{n}"
        n += 1
    used.add(candidate)
    return candidate


def _copy_attachments_for(db: Session, target: str, column, old_id: str, new_id: str) -> dict[str, str]:
    """Returns old attachment uid -> new attachment uid, so a caller whose
    object points at one of these by uid (an asset's avatar) can follow it."""
    mapping: dict[str, str] = {}
    for att in db.scalars(select(Attachment).where(column == old_id)).all():
        new_uid = str(uuid.uuid4())
        new_path = os.path.join(ATTACHMENTS_DIR, new_uid)
        try:
            if os.path.exists(att.storage_path):
                shutil.copyfile(att.storage_path, new_path)
        except OSError:
            pass
        db.add(Attachment(
            uid=new_uid,
            workspace_id=target,
            asset_uid=new_id if column is Attachment.asset_uid else None,
            document_revision_uid=new_id if column is Attachment.document_revision_uid else None,
            issue_uid=new_id if column is Attachment.issue_uid else None,
            filename=att.filename,
            mime_type=att.mime_type,
            file_size=att.file_size,
            author=att.author,
            storage_path=new_path,
            backend_id=None,
            backend_url=att.backend_url,
        ))
        mapping[att.uid] = new_uid
    return mapping


def _copy(
    db: Session, source: str, target: str,
    schema_uids: list[str], asset_uids: set[str], document_uids: set[str], issue_uids: set[str],
    force: bool = False,
) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    counts = {
        "types": 0, "assets": 0, "documents": 0, "issues": 0,
        "relations_copied": 0, "relations_dropped": 0, "links_dropped": 0, "icons_dropped": 0,
        "types_overridden": 0, "assets_overridden": 0,
    }
    schema_map: dict[str, str] = {}
    asset_map: dict[str, str] = {}
    document_map: dict[str, str] = {}
    issue_map: dict[str, str] = {}
    used_keys: set[str] = set()
    overridden_assets: set[str] = set()
    type_conflicts: list[str] = []

    for uid in schema_uids:
        schema = db.get(Schema, uid)
        if schema is None or schema.workspace_id != source:
            continue
        new_parent = schema_map.get(schema.parent_schema_uid, schema.parent_schema_uid) if schema.parent_schema_uid else None
        parent_clause = (Schema.parent_schema_uid == new_parent) if new_parent else Schema.parent_schema_uid.is_(None)
        existing = db.scalar(
            select(Schema).where(
                Schema.workspace_id == target, Schema.name == schema.name,
                Schema.applies_to == schema.applies_to, parent_clause,
            )
        )
        # A private icon isn't duplicated — a copy in another workspace can't
        # see it, so it's dropped, not forked. A global one is already
        # visible from the target, so the copy just keeps pointing at it.
        new_icon_uid = None
        if schema.icon_uid:
            icon = db.get(Icon, schema.icon_uid)
            if icon is not None and icon.is_global:
                new_icon_uid = schema.icon_uid
            else:
                counts["icons_dropped"] += 1

        if existing is not None:
            type_conflicts.append(schema.name)
            if not force:
                schema_map[uid] = existing.uid  # only matters if we end up not raising after all
                continue
            existing.description = schema.description
            existing.is_concrete = schema.is_concrete
            existing.attributes = list(schema.attributes or [])
            existing.metadata_json = dict(schema.metadata_json or {})
            existing.version = schema.version
            existing.is_global = schema.is_global
            if new_icon_uid:
                existing.icon_uid = new_icon_uid
            schema_map[uid] = existing.uid
            counts["types_overridden"] += 1
            continue

        new_uid = str(uuid.uuid4())
        db.add(Schema(
            uid=new_uid, workspace_id=target, name=schema.name, description=schema.description,
            is_concrete=schema.is_concrete, parent_schema_uid=new_parent,
            attributes=list(schema.attributes or []), metadata_json=dict(schema.metadata_json or {}),
            version=schema.version, icon_uid=new_icon_uid, is_global=schema.is_global,
            applies_to=schema.applies_to,
        ))
        schema_map[uid] = new_uid
        counts["types"] += 1
    db.flush()

    if type_conflicts and not force:
        names = ", ".join(sorted(set(type_conflicts))[:20])
        raise ValueError(
            f"A type named {names} already exists in the target workspace at the same level. "
            "Copy again with Force overwrite to merge into it, or rename/remove it there first."
        )

    for uid in asset_uids:
        asset = db.get(Asset, uid)
        if asset is None or asset.workspace_id != source:
            continue
        # Asset.key is unique across the whole install, so a copy can never
        # share its source's own key — matching a previously-copied asset
        # for force-merge has to go by a provenance stamp instead, set the
        # first time this source asset was copied here.
        existing_asset = db.scalar(
            select(Asset).where(
                Asset.workspace_id == target, Asset.attributes["_copy_source_uid"].astext == uid
            )
        ) if force else None
        if existing_asset is not None:
            existing_asset.name = asset.name
            existing_asset.type = asset.type
            existing_asset.schema_uid = schema_map.get(asset.schema_uid, asset.schema_uid)
            existing_asset.attributes = {**dict(asset.attributes or {}), "_copy_source_uid": uid}
            existing_asset.is_global = asset.is_global
            asset_map[uid] = existing_asset.uid
            overridden_assets.add(uid)
            counts["assets_overridden"] += 1
            continue
        new_uid = str(uuid.uuid4())
        new_key = _unique_asset_key(db, asset.key, used_keys)
        db.add(Asset(
            uid=new_uid, workspace_id=target,
            schema_uid=schema_map.get(asset.schema_uid, asset.schema_uid),
            key=new_key, name=asset.name, type=asset.type, avatar_icon_uid=None,
            attributes={**dict(asset.attributes or {}), "_copy_source_uid": uid},
            inbound_relations=[], outbound_relations=[],
            deleted_at=None, is_global=asset.is_global,
        ))
        asset_map[uid] = new_uid
        counts["assets"] += 1
    db.flush()

    # Subresources (comments/history/labels/attachments) are only copied for
    # freshly-created assets — an overridden asset already has its own, and
    # re-copying them on every force re-run would just keep piling up.
    for old_uid, new_uid in asset_map.items():
        if old_uid in overridden_assets:
            continue
        for c in db.scalars(select(AssetComment).where(AssetComment.asset_uid == old_uid)):
            db.add(AssetComment(
                uid=str(uuid.uuid4()), asset_uid=new_uid, author=c.author, text=c.text,
                created=c.created, updated=c.updated, backend_id=None, backend_url=c.backend_url,
            ))
        for h in db.scalars(select(AssetHistory).where(AssetHistory.asset_uid == old_uid)):
            db.add(AssetHistory(
                uid=str(uuid.uuid4()), asset_uid=new_uid, type=h.type, author=h.author,
                details=h.details, timestamp=h.timestamp, backend_id=None,
            ))
        for lbl in db.scalars(select(AssetLabel).where(AssetLabel.asset_uid == old_uid)):
            db.add(AssetLabel(
                uid=str(uuid.uuid4()), asset_uid=new_uid, type=lbl.type, value=lbl.value,
                namespace=lbl.namespace, issuer=lbl.issuer, verified=lbl.verified,
                confidence=lbl.confidence, created_at=lbl.created_at, updated_at=lbl.updated_at,
                metadata_json=lbl.metadata_json,
            ))
        attachment_map = _copy_attachments_for(db, target, Attachment.asset_uid, old_uid, new_uid)
        old_asset = db.get(Asset, old_uid)
        if old_asset.avatar_icon_uid and old_asset.avatar_icon_uid in attachment_map:
            db.get(Asset, new_uid).avatar_icon_uid = attachment_map[old_asset.avatar_icon_uid]

    # Indoors: copies of the places' floors and plans, and the copied records' placements
    # (services/indoor_transfer.py).
    from app.services import indoor_transfer
    inside = indoor_transfer.carry_copy(db, target, {o: n for o, n in asset_map.items() if o not in overridden_assets})
    counts.update({f"indoor_{k}": v for k, v in inside.items()})
    if inside["placements_not_carried"]:
        warnings.append(f"{inside['placements_not_carried']} indoor placement(s) not carried: their place is not "
                        f"reachable from the target.")
    if inside["plan_files_missing"]:
        warnings.append(f"{inside['plan_files_missing']} floor plan(s) not copied: their file is missing.")

    if asset_map:
        existing_relations = {
            (r.from_asset_uid, r.to_asset_uid, r.relation_type)
            for r in db.scalars(
                select(Relation).where(Relation.from_asset_uid.in_(asset_map.values()))
            )
        }
        rels = db.scalars(select(Relation).where(Relation.from_asset_uid.in_(asset_map.keys()))).all()
        for rel in rels:
            if rel.to_asset_uid not in asset_map:
                counts["relations_dropped"] += 1
                continue
            key = (asset_map[rel.from_asset_uid], asset_map[rel.to_asset_uid], rel.relation_type)
            if key in existing_relations:
                continue  # already there from a previous force-copy of this same pair
            db.add(Relation(workspace_id=target, from_asset_uid=key[0], to_asset_uid=key[1], relation_type=key[2]))
            existing_relations.add(key)
            counts["relations_copied"] += 1
    db.flush()
    for new_uid in asset_map.values():
        rebuild_asset_relations_with_neighbors(db, new_uid)

    for uid in document_uids:
        doc = db.get(Document, uid)
        if doc is None or doc.workspace_id != source:
            continue
        new_uid = str(uuid.uuid4())
        new_type_uid = schema_map.get(doc.document_type_uid, doc.document_type_uid) if doc.document_type_uid else None
        new_responsible = asset_map.get(doc.responsible_service_asset_uid) if doc.responsible_service_asset_uid else None
        if doc.responsible_service_asset_uid and new_responsible is None:
            counts["links_dropped"] += 1
        new_code = next_code(db, target, new_type_uid)
        copy = Document(
            uid=new_uid, workspace_id=target, code=new_code, title=doc.title,
            document_type_uid=new_type_uid, owner_user_id=doc.owner_user_id,
            responsible_service_asset_uid=new_responsible, authority_level=doc.authority_level,
            confidentiality=doc.confidentiality, source=doc.source, current_revision_uid=None,
            is_global=doc.is_global,
        )
        db.add(copy)
        db.flush()

        if doc.current_revision_uid:
            rev = db.get(DocumentRevision, doc.current_revision_uid)
            if rev is not None:
                new_rev_uid = str(uuid.uuid4())
                db.add(DocumentRevision(
                    uid=new_rev_uid, document_uid=new_uid, revision_number=rev.revision_number,
                    state=rev.state, body_markdown=rev.body_markdown, steps=list(rev.steps or []),
                    attributes=dict(rev.attributes or {}), valid_from=rev.valid_from,
                    valid_until=rev.valid_until, next_review_due=rev.next_review_due,
                    authored_by=rev.authored_by, approved_by=rev.approved_by,
                    submitted_at=rev.submitted_at, approved_at=rev.approved_at,
                    published_at=rev.published_at, review_comment=rev.review_comment,
                    superseded_by_uid=None,
                ))
                db.flush()
                copy.current_revision_uid = new_rev_uid
                _copy_attachments_for(db, target, Attachment.document_revision_uid, rev.uid, new_rev_uid)

        document_map[uid] = new_uid
        counts["documents"] += 1
    db.flush()

    for uid in issue_uids:
        issue = db.get(Issue, uid)
        if issue is None or issue.workspace_id != source:
            continue
        new_uid = str(uuid.uuid4())
        new_asset_uid = asset_map.get(issue.asset_uid) if issue.asset_uid else None
        if issue.asset_uid and new_asset_uid is None:
            counts["links_dropped"] += 1
        db.add(Issue(
            uid=new_uid, workspace_id=target, asset_uid=new_asset_uid,
            schema_uid=schema_map.get(issue.schema_uid, issue.schema_uid) if issue.schema_uid else None,
            attributes=dict(issue.attributes or {}), title=issue.title, description=issue.description,
            state=issue.state, priority=issue.priority, assignee=issue.assignee,
            labels=list(issue.labels or []), due_date=issue.due_date, closed_at=issue.closed_at,
            created_by=issue.created_by, version=1, deleted_at=None,
        ))
        for c in db.scalars(select(IssueComment).where(IssueComment.issue_uid == uid)):
            db.add(IssueComment(uid=str(uuid.uuid4()), issue_uid=new_uid, author=c.author, body=c.body))
        for h in db.scalars(select(IssueHistory).where(IssueHistory.issue_uid == uid)):
            db.add(IssueHistory(
                uid=str(uuid.uuid4()), issue_uid=new_uid, type=h.type, author=h.author,
                field=h.field, from_value=h.from_value, to_value=h.to_value,
                details=h.details, timestamp=h.timestamp, backend_id=None,
            ))
        _copy_attachments_for(db, target, Attachment.issue_uid, uid, new_uid)
        issue_map[uid] = new_uid
        counts["issues"] += 1
    db.flush()

    if issue_map:
        links = db.scalars(select(IssueLink).where(IssueLink.from_issue_uid.in_(issue_map.keys()))).all()
        for link in links:
            if link.to_issue_uid in issue_map:
                db.add(IssueLink(
                    from_issue_uid=issue_map[link.from_issue_uid], to_issue_uid=issue_map[link.to_issue_uid],
                    relation_type=link.relation_type, created_at=link.created_at,
                ))
            else:
                counts["links_dropped"] += 1

    if document_map:
        rels = db.scalars(select(DocumentRelation).where(DocumentRelation.from_document_uid.in_(document_map.keys()))).all()
        target_maps = {"asset": asset_map, "document": document_map, "issue": issue_map, "schema": schema_map}
        for rel in rels:
            mapped_to = target_maps.get(rel.to_type, {}).get(rel.to_uid)
            if mapped_to is not None:
                db.add(DocumentRelation(
                    workspace_id=target, from_document_uid=document_map[rel.from_document_uid],
                    to_type=rel.to_type, to_uid=mapped_to, relation_type=rel.relation_type,
                ))
            else:
                counts["links_dropped"] += 1

    if asset_map or issue_map:
        for old_asset_uid, new_asset_uid in asset_map.items():
            tickets = db.scalars(select(AssetTicket).where(AssetTicket.asset_uid == old_asset_uid)).all()
            if not tickets:
                continue
            ticket_key_to_new_issue = {}
            for old_issue_uid, new_issue_uid in issue_map.items():
                issue = db.get(Issue, old_issue_uid)
                if issue is not None:
                    ticket_key_to_new_issue[ticket_key_for(issue)] = new_issue_uid
            for at in tickets:
                if at.ticket_key not in ticket_key_to_new_issue:
                    counts["links_dropped"] += 1
                    continue
                db.add(AssetTicket(
                    uid=str(uuid.uuid4()), asset_uid=new_asset_uid, ticket_key=at.ticket_key,
                    summary=at.summary, type=at.type, status=at.status, created=at.created,
                    updated=at.updated, backend_id=None, backend_url=at.backend_url,
                ))

    if counts["relations_dropped"]:
        warnings.append(f"Dropped {counts['relations_dropped']} relation(s) to an object outside the transfer.")
    if counts["links_dropped"]:
        warnings.append(f"Dropped {counts['links_dropped']} ticket/document link(s) to an object outside the transfer.")
    if counts["icons_dropped"]:
        warnings.append(
            f"Didn't copy {counts['icons_dropped']} private icon(s) — mark them global first if you want "
            "copies to keep using them."
        )
    if counts["relations_copied"] or counts["assets"]:
        warnings.append(
            "Reference-typed attribute values still point at the source workspace's objects — "
            "run Integrity → Relink in the target workspace to re-resolve them."
        )
    if counts["types_overridden"] or counts["assets_overridden"]:
        warnings.append(
            f"Force overwrite merged {counts['types_overridden']} existing type(s) and "
            f"{counts['assets_overridden']} existing object(s) in place instead of duplicating them."
        )
    return counts, warnings
