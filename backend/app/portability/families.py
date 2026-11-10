"""The record families of an archive: an allow-list.

Every family names its table, its group, its key, whether it is authoritative, and how its rows
are chosen for a scope. A table with no family here never leaves ARGUS — API tokens, devices and
their push tokens, idempotency keys, upload sessions, model-provider and import configurations,
application settings, search indexes, notifications, queues.

Groups, in load order:

  catalogue   types (global ones included when a scope uses them) and their icons
  identity    people as historical references: uid, subject, directory name, display metadata
  access      the workspace definitions, memberships, role bindings and the roles they name
  governance  authority policies and rulesets
  records     domain records and their own histories: Positions, Equipment, Installations,
              Product Models, Locations (all assets), asserted relations, tickets, comments,
              watchers, links, documents, revisions, attachments, workflows, migration domains
  ledger      the append-only audit: streams, source revisions, claims, claim events, revision
              events, decisions, status, identity, record and conflict events, migration map,
              reconciliation reports
  projection  NOT authoritative: fact state, identity bindings, conflicts, derived relations and
              stream heads, carried only to compare with what the importer rebuilds

Sequenced families (`sequenced=True`) are append-only event tables. Their rows are chosen by the
ledger watermark window `(previous, W]` and get a new local `seq` on import; their identity across
instances is (origin, family, source seq), kept in the row map.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Callable, Optional

from sqlalchemy import Date, DateTime, and_, or_, select
from sqlalchemy.orm import Session

from app.models.asset import Asset, Relation
from app.models.asset_subresources import AssetComment, AssetHistory, AssetLabel, AssetTicket
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.models.icon import Icon
from app.models.issue import Issue, IssueComment, IssueHistory, IssueLink
from app.models.ledger import (Claim, ClaimEvent, Conflict, ConflictEvent, Decision, FactState, IdentityBinding,
                               IdentityEvent, LedgerDomain, LedgerPolicy, LedgerRuleset, LedgerStream, MigrationMap,
                               RecordEvent, ReconciliationReport, RevisionEvent, SourceRevision, StatusEvent,
                               StreamHead, TicketLink)
from app.models.beam_model import BeamAssetBinding, BeamModelDocument, BeamModelValue
from app.models.equipment_class import EquipmentClass, EquipmentClassReview
from app.models.global_value import GlobalValue
from app.models.group import Group, GroupMember, GroupAdministrator
from app.models.membership import Membership
from app.models.role import Role, RoleBinding, SiteGroupRoleBinding
from app.models.schema import Schema
from app.models.user import User
from app.models.workflow import TicketWatcher, Workflow
from app.models.workspace import Workspace, SiteAdministrator

# Columns that describe this instance, not the history: never exported, set locally on import.
LOCAL_COLUMNS = ("recorded_at",)
# The append-only ledger families whose rows form the origin chain of an import.
ORIGIN_CHAIN = ("source_revisions", "claims", "claim_events", "revision_events", "decisions", "status_events",
                "identity_events", "record_events", "conflict_events", "migration_map", "reconciliation_reports")

# Watermarked tables: the ledger's append-only sequences.
SEQUENCED_TABLES = ("ledger_claim_events", "ledger_revision_events", "ledger_decisions", "ledger_status_events",
                    "ledger_identity_events", "ledger_record_events", "ledger_conflict_events", "ledger_rulesets")


@dataclass
class Scope:
    """What an export covers, and the watermark window of its sequenced families."""
    workspaces: list[str]
    watermark: dict                      # table -> high seq (inclusive)
    previous: dict = field(default_factory=dict)   # table -> high seq of the previous export (exclusive)
    excluded_uids: set = field(default_factory=set)     # restricted records left out
    hidden: dict = field(default_factory=dict)          # uid -> fields hidden by restriction
    excluded_claims: set = field(default_factory=set)
    external_refs: dict = field(default_factory=dict)   # uid -> dependency id (external reference)

    def assets(self):
        return select(Asset.uid).where(Asset.workspace_id.in_(self.workspaces))

    def issues(self):
        return select(Issue.uid).where(Issue.workspace_id.in_(self.workspaces))

    def documents(self):
        return select(Document.uid).where(Document.workspace_id.in_(self.workspaces))

    def streams(self):
        return select(LedgerStream.id).where(LedgerStream.workspace_id.in_(self.workspaces))

    def window(self, model, table: str):
        hi = self.watermark.get(table, 0)
        lo = self.previous.get(table, 0)
        return and_(model.seq > lo, model.seq <= hi)


@dataclass
class Family:
    name: str
    group: str
    model: type
    key: tuple
    select: Callable[[Session, Scope], object]
    sequenced: bool = False
    authoritative: bool = True
    exclude: tuple = ()                  # columns never exported (local or operational)
    blobs: dict = field(default_factory=dict)   # column -> "file" | "bytes"
    deferred: tuple = ()                 # columns set in a second pass (references within the family)
    subjects: tuple = ()                 # columns naming a record uid (restriction and closure)
    redact: bool = False                 # attributes filtered by restricted fields
    replace_set: bool = False            # a set without history: an increment states it whole
    table: Optional[str] = None

    def __post_init__(self):
        self.table = self.model.__table__.name

    @property
    def columns(self) -> list[str]:
        return [c.name for c in self.model.__table__.columns
                if c.name not in self.exclude and c.name not in LOCAL_COLUMNS]

    def key_of(self, row: dict) -> str:
        return "|".join(str(row.get(k)) for k in self.key)


def to_json(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, memoryview)):
        return {"$base64": base64.b64encode(bytes(value)).decode()}
    return value


def from_json(model, name: str, value):
    if value is None:
        return None
    col = model.__table__.columns[name]
    if isinstance(col.type, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value)
    if isinstance(col.type, Date) and isinstance(value, str):
        return date.fromisoformat(value)
    if isinstance(value, dict) and set(value) == {"$base64"}:
        return base64.b64decode(value["$base64"])
    return value


# --------------------------------------------------------------------------- selections

def _schemas(db: Session, sc: Scope):
    """The scope's own types, every type its records use, and their ancestors."""
    wanted = set(db.scalars(select(Schema.uid).where(Schema.workspace_id.in_(sc.workspaces))))
    for model, col in ((Asset, Asset.schema_uid), (Issue, Issue.schema_uid), (Document, Document.document_type_uid)):
        wanted |= {u for u in db.scalars(select(col).where(model.workspace_id.in_(sc.workspaces))) if u}
    frontier = set(wanted)
    while frontier:
        parents = {p for p in db.scalars(select(Schema.parent_schema_uid).where(Schema.uid.in_(frontier))) if p}
        frontier = parents - wanted
        wanted |= parents
    return select(Schema).where(Schema.uid.in_(wanted)).order_by(Schema.uid)


def _icons(db, sc):
    return select(Icon).where(Icon.uid.in_(select(Schema.icon_uid).where(
        Schema.uid.in_(_schemas(db, sc).with_only_columns(Schema.uid))))).order_by(Icon.uid)


def _ws(model, order):
    return lambda db, sc: select(model).where(model.workspace_id.in_(sc.workspaces)).order_by(*order)


def _by(model, col, sub, order):
    return lambda db, sc: select(model).where(getattr(model, col).in_(sub(sc))).order_by(*order)


def _claim_refs(sc):
    return select(Claim.source_ref).where(Claim.stream_id.in_(sc.streams()))


def _claims(db, sc):
    """Claims first seen in the window: referenced by a claim event of the window and by none before."""
    in_window = select(ClaimEvent.claim_id).where(ClaimEvent.stream_id.in_(sc.streams()),
                                                  sc.window(ClaimEvent, "ledger_claim_events"))
    before = select(ClaimEvent.claim_id).where(ClaimEvent.stream_id.in_(sc.streams()),
                                               ClaimEvent.seq <= sc.previous.get("ledger_claim_events", 0))
    return select(Claim).where(Claim.claim_id.in_(in_window), Claim.claim_id.not_in(before)).order_by(Claim.claim_id)


def _revisions(db, sc):
    """Source revisions first referenced in the window (by a revision or claim event)."""
    lo = sc.previous.get("ledger_revision_events", 0)
    in_window = select(RevisionEvent.revision_id).where(RevisionEvent.stream_id.in_(sc.streams()),
                                                        sc.window(RevisionEvent, "ledger_revision_events"))
    claim_window = select(ClaimEvent.revision_id).where(ClaimEvent.stream_id.in_(sc.streams()),
                                                        sc.window(ClaimEvent, "ledger_claim_events"))
    before = select(RevisionEvent.revision_id).where(RevisionEvent.stream_id.in_(sc.streams()), RevisionEvent.seq <= lo)
    before_c = select(ClaimEvent.revision_id).where(ClaimEvent.stream_id.in_(sc.streams()),
                                                    ClaimEvent.seq <= sc.previous.get("ledger_claim_events", 0))
    return (select(SourceRevision).where(or_(SourceRevision.id.in_(in_window), SourceRevision.id.in_(claim_window)),
                                         SourceRevision.id.not_in(before), SourceRevision.id.not_in(before_c))
            .order_by(SourceRevision.stream_id, SourceRevision.number))


def _seq(model, table, where):
    return lambda db, sc: select(model).where(sc.window(model, table), where(sc)).order_by(model.seq)


def _users(db, sc):
    """People named by what the scope exports: members, role holders, document authors and approvers."""
    ids = set(db.scalars(select(Membership.user_id).where(Membership.workspace_id.in_(sc.workspaces))))
    ids |= set(db.scalars(select(RoleBinding.subject_id).where(RoleBinding.workspace_id.in_(sc.workspaces),
                                                                RoleBinding.subject_type == "user")))
    ids |= {u for u in db.scalars(select(Document.owner_user_id).where(Document.workspace_id.in_(sc.workspaces))) if u}
    ids |= set(db.scalars(select(GroupMember.user_id).where(GroupMember.group_uid.in_(
        _groups(db, sc).with_only_columns(Group.uid)))))
    ids |= set(db.scalars(select(GroupAdministrator.user_id).where(GroupAdministrator.group_uid.in_(
        _groups(db, sc).with_only_columns(Group.uid)))))
    ids |= set(db.scalars(select(SiteAdministrator.user_id).where(SiteAdministrator.site_id.in_(sc.workspaces))))
    for col in ("authored_by", "approved_by"):
        ids |= {u for u in db.scalars(select(getattr(DocumentRevision, col)).where(
            DocumentRevision.document_uid.in_(sc.documents()))) if u}
    return select(User).where(User.id.in_(ids)).order_by(User.id)


def _groups(db, sc):
    """The groups the scope grants roles to, directly or site-wide (a grant to a group needs the group, and its
    members)."""
    return select(Group).where(Group.uid.in_(select(RoleBinding.subject_id).where(
        RoleBinding.workspace_id.in_(sc.workspaces), RoleBinding.subject_type == "group"))
        | Group.uid.in_(select(SiteGroupRoleBinding.group_uid).where(
            SiteGroupRoleBinding.site_id.in_(sc.workspaces)))).order_by(Group.uid)


def _roles(db, sc):
    return select(Role).where(Role.id.in_(select(RoleBinding.role_id).where(
        RoleBinding.workspace_id.in_(sc.workspaces)))).order_by(Role.id)


def _domains_reports(db, sc):
    return select(ReconciliationReport).where(ReconciliationReport.domain_id.in_(
        select(LedgerDomain.id).where(LedgerDomain.workspace_id.in_(sc.workspaces)))).order_by(ReconciliationReport.id)


FAMILIES: list[Family] = [
    # catalogue
    Family("icons", "catalogue", Icon, ("uid",), _icons, blobs={"storage_path": "file"}),
    Family("types", "catalogue", Schema, ("uid",), _schemas, deferred=("parent_schema_uid",)),
    # The installation's vocabulary for equipment with no type of its own, and its promotion reviews.
    Family("equipment_classes", "catalogue", EquipmentClass, ("name",),
           lambda db, sc: select(EquipmentClass).order_by(EquipmentClass.name)),
    Family("equipment_class_reviews", "catalogue", EquipmentClassReview, ("class_name", "opened_at"),
           lambda db, sc: select(EquipmentClassReview).order_by(EquipmentClassReview.id), exclude=("id",)),
    # identity: never credentials
    Family("identities", "identity", User, ("id",), _users,
           exclude=("last_login_at", "synced_at", "is_admin")),
    # access
    Family("workspaces", "access", Workspace, ("id",),
           lambda db, sc: select(Workspace).where(Workspace.id.in_(sc.workspaces)).order_by(Workspace.id),
           exclude=("import_state",)),
    Family("roles", "access", Role, ("id",), _roles),
    Family("groups", "access", Group, ("uid",), _groups),
    Family("group_members", "access", GroupMember, ("group_uid", "user_id"),
           lambda db, sc: select(GroupMember).where(GroupMember.group_uid.in_(
               _groups(db, sc).with_only_columns(Group.uid))).order_by(GroupMember.id),
           exclude=("id",), replace_set=True),
    Family("group_administrators", "access", GroupAdministrator, ("group_uid", "user_id"),
           lambda db, sc: select(GroupAdministrator).where(GroupAdministrator.group_uid.in_(
               _groups(db, sc).with_only_columns(Group.uid))).order_by(GroupAdministrator.id),
           exclude=("id",), replace_set=True),
    # A site's own grants travel with the site (a facility-only archive carries none: issue #26).
    Family("site_group_role_bindings", "access", SiteGroupRoleBinding, ("site_id", "group_uid", "role_id"),
           lambda db, sc: select(SiteGroupRoleBinding).where(SiteGroupRoleBinding.site_id.in_(sc.workspaces))
               .order_by(SiteGroupRoleBinding.id), exclude=("id",), replace_set=True),
    Family("site_administrators", "access", SiteAdministrator, ("site_id", "user_id"),
           lambda db, sc: select(SiteAdministrator).where(SiteAdministrator.site_id.in_(sc.workspaces))
               .order_by(SiteAdministrator.id), exclude=("id",), replace_set=True),
    # Shared value lists (statuses, priorities…) per workspace.
    Family("global_values", "access", GlobalValue, ("uid",), _ws(GlobalValue, (GlobalValue.uid,))),
    Family("memberships", "access", Membership, ("workspace_id", "user_id"), _ws(Membership, (Membership.id,)),
           exclude=("id",), replace_set=True),
    Family("role_bindings", "access", RoleBinding, ("workspace_id", "subject_type", "subject_id", "role_id"),
           _ws(RoleBinding, (RoleBinding.id,)), exclude=("id",), replace_set=True),
    # governance
    Family("policies", "governance", LedgerPolicy, ("version",),
           lambda db, sc: select(LedgerPolicy).order_by(LedgerPolicy.activated_at)),
    Family("rulesets", "governance", LedgerRuleset, ("seq",),
           _seq(LedgerRuleset, "ledger_rulesets", lambda sc: or_(LedgerRuleset.scope == "*",
                                                                 LedgerRuleset.scope.in_(sc.workspaces))),
           sequenced=True),
    # records
    Family("workflows", "records", Workflow, ("uid",), _ws(Workflow, (Workflow.uid,))),
    Family("assets", "records", Asset, ("uid",), _ws(Asset, (Asset.uid,)), deferred=("merged_into_uid",),
           subjects=("uid", "merged_into_uid"), redact=True),
    Family("relations", "records", Relation, ("workspace_id", "from_asset_uid", "relation_type", "to_asset_uid"),
           lambda db, sc: select(Relation).where(Relation.workspace_id.in_(sc.workspaces),
                                                 Relation.derivation.is_(None)).order_by(Relation.id),
           exclude=("id",), subjects=("from_asset_uid", "to_asset_uid"), replace_set=True),
    Family("asset_comments", "records", AssetComment, ("uid",), _by(AssetComment, "asset_uid", Scope.assets,
                                                                     (AssetComment.uid,)), subjects=("asset_uid",)),
    Family("asset_history", "records", AssetHistory, ("uid",), _by(AssetHistory, "asset_uid", Scope.assets,
                                                                   (AssetHistory.uid,)), subjects=("asset_uid",)),
    Family("asset_labels", "records", AssetLabel, ("uid",), _by(AssetLabel, "asset_uid", Scope.assets,
                                                                (AssetLabel.uid,)), subjects=("asset_uid",)),
    Family("asset_tickets", "records", AssetTicket, ("uid",), _by(AssetTicket, "asset_uid", Scope.assets,
                                                                  (AssetTicket.uid,)), subjects=("asset_uid",)),
    Family("tickets", "records", Issue, ("uid",), _ws(Issue, (Issue.uid,)), subjects=("uid", "asset_uid"),
           redact=True),
    Family("ticket_comments", "records", IssueComment, ("uid",),
           _by(IssueComment, "issue_uid", Scope.issues, (IssueComment.uid,)), subjects=("issue_uid",)),
    Family("ticket_history", "records", IssueHistory, ("uid",),
           _by(IssueHistory, "issue_uid", Scope.issues, (IssueHistory.uid,)), subjects=("issue_uid",)),
    Family("ticket_links", "records", IssueLink, ("from_issue_uid", "to_issue_uid", "relation_type"),
           _by(IssueLink, "from_issue_uid", Scope.issues, (IssueLink.id,)), exclude=("id",),
           subjects=("from_issue_uid", "to_issue_uid"), replace_set=True),
    Family("ticket_watchers", "records", TicketWatcher, ("issue_uid", "user"),
           _by(TicketWatcher, "issue_uid", Scope.issues, (TicketWatcher.id,)), exclude=("id",),
           subjects=("issue_uid",), replace_set=True),
    Family("documents", "records", Document, ("uid",), _ws(Document, (Document.uid,)),
           deferred=("current_revision_uid",), subjects=("responsible_service_asset_uid",)),
    Family("document_revisions", "records", DocumentRevision, ("uid",),
           _by(DocumentRevision, "document_uid", Scope.documents, (DocumentRevision.document_uid,
                                                                    DocumentRevision.revision_number)),
           deferred=("superseded_by_uid",)),
    Family("document_relations", "records", DocumentRelation, ("from_document_uid", "to_type", "to_uid",
                                                               "relation_type"),
           _ws(DocumentRelation, (DocumentRelation.id,)), exclude=("id",), replace_set=True),
    Family("attachments", "records", Attachment, ("uid",), _ws(Attachment, (Attachment.uid,)),
           blobs={"storage_path": "file"}, exclude=("backend_id", "backend_url"),
           subjects=("asset_uid", "issue_uid")),
    Family("migration_domains", "records", LedgerDomain, ("id",), _ws(LedgerDomain, (LedgerDomain.id,))),
    # The beam model (docs/beam-model.md): its documents (layout, definitions, datasets), the values along its
    # paths, and its components' bindings to assets. The beam elements themselves are assets, loaded before.
    Family("beam_model_documents", "records", BeamModelDocument, ("workspace_id", "model_id", "revision"),
           _ws(BeamModelDocument, (BeamModelDocument.id,)), exclude=("id",)),
    Family("beam_model_values", "records", BeamModelValue, ("dataset_uid", "subject_uid", "path_uid"),
           _ws(BeamModelValue, (BeamModelValue.id,)), exclude=("id",), subjects=("subject_uid",)),
    Family("beam_asset_bindings", "records", BeamAssetBinding, ("workspace_id", "model_id", "component_id",
                                                                "relation", "asset_uid"),
           _ws(BeamAssetBinding, (BeamAssetBinding.id,)), exclude=("id",), subjects=("asset_uid",)),
    # ledger: the authority
    Family("streams", "ledger", LedgerStream, ("id",), _ws(LedgerStream, (LedgerStream.id,))),
    Family("source_revisions", "ledger", SourceRevision, ("id",), _revisions, blobs={"content": "bytes"}),
    Family("claims", "ledger", Claim, ("claim_id",), _claims),
    Family("claim_events", "ledger", ClaimEvent, ("seq",),
           _seq(ClaimEvent, "ledger_claim_events", lambda sc: ClaimEvent.stream_id.in_(sc.streams())),
           sequenced=True),
    Family("revision_events", "ledger", RevisionEvent, ("seq",),
           _seq(RevisionEvent, "ledger_revision_events", lambda sc: RevisionEvent.stream_id.in_(sc.streams())),
           sequenced=True),
    Family("decisions", "ledger", Decision, ("seq",),
           _seq(Decision, "ledger_decisions", lambda sc: or_(Decision.workspace_id.in_(sc.workspaces),
                                                             Decision.subject_uid.in_(sc.assets()))),
           sequenced=True, subjects=("subject_uid",)),
    Family("status_events", "ledger", StatusEvent, ("seq",),
           _seq(StatusEvent, "ledger_status_events", lambda sc: StatusEvent.subject_uid.in_(sc.assets())),
           sequenced=True, subjects=("subject_uid",)),
    Family("identity_events", "ledger", IdentityEvent, ("seq",),
           _seq(IdentityEvent, "ledger_identity_events",
                lambda sc: or_(IdentityEvent.uid.in_(sc.assets()), IdentityEvent.source_ref.in_(_claim_refs(sc)))),
           sequenced=True, subjects=("uid",)),
    Family("record_events", "ledger", RecordEvent, ("seq",),
           _seq(RecordEvent, "ledger_record_events", lambda sc: RecordEvent.uid.in_(sc.assets())),
           sequenced=True, subjects=("uid",)),
    Family("conflict_events", "ledger", ConflictEvent, ("seq",),
           _seq(ConflictEvent, "ledger_conflict_events", lambda sc: ConflictEvent.subject_uid.in_(sc.assets())),
           sequenced=True, subjects=("subject_uid",)),
    Family("migration_map", "ledger", MigrationMap, ("legacy_uid", "new_uid", "role"),
           lambda db, sc: select(MigrationMap).where(or_(MigrationMap.new_uid.in_(sc.assets()),
                                                         MigrationMap.legacy_uid.in_(sc.assets())))
           .order_by(MigrationMap.id), exclude=("id",)),
    Family("reconciliation_reports", "ledger", ReconciliationReport, ("id",), _domains_reports),
    # projections: compared, never loaded
    Family("p_fact_state", "projection", FactState, ("subject_uid", "predicate", "member", "contributor"),
           _by(FactState, "subject_uid", Scope.assets, (FactState.subject_uid, FactState.predicate, FactState.member,
                                                        FactState.contributor)),
           authoritative=False, exclude=("id",), subjects=("subject_uid",)),
    Family("p_identity_bindings", "projection", IdentityBinding, ("source_ref",),
           lambda db, sc: select(IdentityBinding).where(or_(IdentityBinding.uid.in_(sc.assets()),
                                                            IdentityBinding.source_ref.in_(_claim_refs(sc))))
           .order_by(IdentityBinding.source_ref), authoritative=False, subjects=("uid",)),
    Family("p_conflicts", "projection", Conflict, ("conflict_id",), _ws(Conflict, (Conflict.conflict_id,)),
           authoritative=False, exclude=("opened_seq",), subjects=("subject_uid",)),
    Family("p_derived_relations", "projection", Relation,
           ("workspace_id", "from_asset_uid", "relation_type", "to_asset_uid", "derivation"),
           lambda db, sc: select(Relation).where(Relation.workspace_id.in_(sc.workspaces),
                                                 Relation.derivation.isnot(None))
           .order_by(Relation.from_asset_uid, Relation.relation_type, Relation.to_asset_uid),
           authoritative=False, exclude=("id",), subjects=("from_asset_uid", "to_asset_uid")),
    # A ticket's record links are derived from the ticket and the Installations (app.ledger.tickets).
    Family("p_ticket_links", "projection", TicketLink, ("ticket_uid", "asset_uid", "role"),
           lambda db, sc: select(TicketLink).where(TicketLink.workspace_id.in_(sc.workspaces))
           .order_by(TicketLink.ticket_uid, TicketLink.asset_uid, TicketLink.role),
           authoritative=False, exclude=("id",), subjects=("ticket_uid", "asset_uid")),
    Family("p_stream_heads", "projection", StreamHead, ("stream_id",),
           _by(StreamHead, "stream_id", Scope.streams, (StreamHead.stream_id,)), authoritative=False),
]

BY_NAME = {f.name: f for f in FAMILIES}
GROUP_ORDER = ("catalogue", "identity", "access", "governance", "records", "ledger", "projection")
