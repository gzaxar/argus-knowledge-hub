"""What a workspace bundle carries: every table of the database, placed (docs/workspace-bundle.md).

`FAMILIES` are carried, in load order: each names its table, how its rows are chosen for a workspace, its files,
the columns left out (row numbers the target gives itself; secrets), the columns set after all rows exist (a
reference to a row loaded later, or to its own table), and what it needs (`people`: applied only when the
administrator asks; `upsert`: a package installing in the new workspace may have made the row already — the
bundle's version replaces it).

`NOT_CARRIED` names every other table with the reason it is not, and `REBUILT` those the import makes again. A
test checks that every table of the database is in exactly one of them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.activity import Activity, ActivitySeries, ActivityWorkspace
from app.models.asset import Asset, Relation
from app.models.asset_subresources import AssetComment, AssetHistory, AssetLabel, AssetTicket
from app.models.attachment import Attachment
from app.models.beam_model import BeamAssetBinding, BeamModelDocument, BeamModelValue
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.models.document_template import DocumentGeneration, DocumentTemplate, DocumentTemplateVersion
from app.models.global_value import GlobalValue
from app.models.icon import Icon
from app.models.indoor import FloorPlan, IndoorPlacement, PlaceLevel
from app.models.issue import Issue, IssueComment, IssueHistory, IssueLink
from app.models.membership import Membership
from app.models.package import WorkspacePackage
from app.models.role import Role, RoleBinding
from app.models.schema import Schema
from app.models.spatial import LocationObservation, SpatialFeature
from app.models.user import User
from app.models.workflow import TicketWatcher, Workflow
from app.models.workspace import Workspace


@dataclass
class Family:
    name: str
    model: type
    select: Callable[[Session, str, "Selection"], list]
    files: tuple[str, ...] = ()            # columns holding a stored file's path
    drop: tuple[str, ...] = ()             # columns never exported
    deferred: tuple[str, ...] = ()         # set after every row is loaded
    people: bool = False                   # applied only with "apply people's access"
    upsert: bool = False                   # a package may have made the row in the new workspace
    note: Optional[str] = None             # shown in the preview

    @property
    def table(self) -> str:
        return self.model.__tablename__

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.model.__table__.primary_key.columns)

    @property
    def numbered(self) -> bool:
        """Keyed by a row number the target gives itself: the key is not exported."""
        cols = list(self.model.__table__.primary_key.columns)
        return len(cols) == 1 and cols[0].autoincrement in (True, "auto") and cols[0].type.python_type is int


@dataclass
class Selection:
    """What is carried for one workspace, built family by family (later families select by earlier ones)."""
    workspace_id: str
    uids: dict[str, set] = field(default_factory=dict)

    def of(self, family: str) -> set:
        return self.uids.get(family, set())


def _ws(model, order=None):
    def pick(db: Session, ws: str, sel: Selection):
        q = select(model).where(model.workspace_id == ws)
        return list(db.scalars(q.order_by(*(order or [c for c in model.__table__.primary_key.columns]))))
    return pick


def _by(model, column: str, family: str):
    def pick(db: Session, ws: str, sel: Selection):
        keys = sel.of(family)
        if not keys:
            return []
        col = getattr(model, column)
        return list(db.scalars(select(model).where(col.in_(keys)).order_by(
            *[c for c in model.__table__.primary_key.columns])))
    return pick


def _workspace(db, ws, sel):
    w = db.get(Workspace, ws)
    return [w] if w is not None else []


def _icons(db, ws, sel):
    return list(db.scalars(select(Icon).where(Icon.workspace_id == ws).order_by(Icon.uid)))


def _schemas(db, ws, sel):
    return list(db.scalars(select(Schema).where(Schema.workspace_id == ws).order_by(Schema.uid)))


USER_COLUMNS = {
    "activities": ("owner_user_id", "assignee_user_id"), "activity_series": ("owner_user_id", "assignee_user_id"),
    "documents": ("owner_user_id",), "document_revisions": ("authored_by", "approved_by"),
    "document_templates": ("owner_user_id",), "memberships": ("user_id",),
    "notification_subscriptions": ("user_id",), "record_watchers": ("user_id",),
}


def _roles(db, ws, sel):
    ids = {b.role_id for b in db.scalars(select(RoleBinding).where(RoleBinding.workspace_id == ws))}
    return list(db.scalars(select(Role).where(Role.id.in_(ids), Role.is_system.is_(False)).order_by(Role.id))) if ids else []


def _relations(db, ws, sel):
    return list(db.scalars(select(Relation).where(Relation.workspace_id == ws).order_by(Relation.id)))


def _issue_links(db, ws, sel):
    keys = sel.of("issues")
    return list(db.scalars(select(IssueLink).where(IssueLink.from_issue_uid.in_(keys)).order_by(IssueLink.id))) if keys else []


def _watchers(db, ws, sel):
    from app.models.workflow import RecordWatcher
    keys = sel.of("assets") | sel.of("documents")
    return list(db.scalars(select(RecordWatcher).where(RecordWatcher.subject_uid.in_(keys))
                           .order_by(RecordWatcher.id))) if keys else []


def _activity_workspaces(db, ws, sel):
    acts, series = sel.of("activities"), sel.of("activity_series")
    conds = []
    if acts:
        conds.append(ActivityWorkspace.activity_uid.in_(acts))
    if series:
        conds.append(ActivityWorkspace.series_uid.in_(series))
    if not conds:
        return []
    return list(db.scalars(select(ActivityWorkspace).where(or_(*conds)).order_by(ActivityWorkspace.id)))


def _llm(db, ws, sel):
    from app.models.llm_config import LLMConfig
    c = db.get(LLMConfig, ws)
    return [c] if c is not None else []


def _model(dotted: str):
    module, name = dotted.rsplit(".", 1)
    import importlib
    return getattr(importlib.import_module(module), name)


def build() -> list[Family]:
    from app.models.equipment_class import EquipmentClassRequest  # noqa: F401 — may be absent in old schemas
    from app.models.import_config import ImportConfig
    from app.models.llm_config import LLMConfig
    from app.models.workflow import NotificationSubscription, RecordWatcher, TicketEscalation
    AiSuggestion = _model("app.models.ai_suggestion.AISuggestion")
    AccessReview = _model("app.models.access_review.AccessReview")
    ReviewEscalation = _model("app.models.ledger.ReviewEscalation")
    GoldenIncident = _model("app.models.legacy_migration.GoldenIncident")
    ImportSnapshot = _model("app.models.import_snapshot.ImportSnapshot")
    return [
        Family("workspace", Workspace, _workspace),
        Family("workspace_packages", WorkspacePackage, _ws(WorkspacePackage), drop=("installed_at", "installed_by"),
               note="installed again in the new workspace, at these versions"),
        Family("icons", Icon, _icons, files=("storage_path",), upsert=True),
        Family("types", Schema, _schemas, deferred=("parent_schema_uid",), upsert=True,
               note="the workspace's types: those its packages make, with the workspace's changes, and its own"),
        Family("global_values", GlobalValue, _ws(GlobalValue), upsert=True),
        Family("ticket_workflows", Workflow, _ws(Workflow), upsert=True),
        Family("roles", Role, _roles, upsert=True, people=True),
        Family("assets", Asset, _ws(Asset), deferred=("merged_into_uid",)),
        Family("asset_comments", AssetComment, _by(AssetComment, "asset_uid", "assets")),
        Family("asset_history", AssetHistory, _by(AssetHistory, "asset_uid", "assets")),
        Family("asset_labels", AssetLabel, _by(AssetLabel, "asset_uid", "assets")),
        Family("asset_tickets", AssetTicket, _by(AssetTicket, "asset_uid", "assets")),
        Family("import_snapshots", ImportSnapshot, _by(ImportSnapshot, "asset_uid", "assets")),
        Family("relations", Relation, _relations),
        Family("tickets", Issue, _ws(Issue)),
        Family("ticket_comments", IssueComment, _by(IssueComment, "issue_uid", "tickets")),
        Family("ticket_history", IssueHistory, _by(IssueHistory, "issue_uid", "tickets")),
        Family("ticket_links", IssueLink, _issue_links),
        Family("ticket_escalations", TicketEscalation, _by(TicketEscalation, "issue_uid", "tickets")),
        Family("documents", Document, _ws(Document), deferred=("current_revision_uid", "superseded_by_uid")),
        Family("document_revisions", DocumentRevision, _by(DocumentRevision, "document_uid", "documents"),
               deferred=("superseded_by_uid",)),
        Family("document_relations", DocumentRelation, _ws(DocumentRelation)),
        Family("attachments", Attachment, _ws(Attachment), files=("storage_path",)),
        Family("document_templates", DocumentTemplate, _ws(DocumentTemplate)),
        Family("document_template_versions", DocumentTemplateVersion,
               _by(DocumentTemplateVersion, "template_uid", "document_templates")),
        Family("document_generations", DocumentGeneration, _ws(DocumentGeneration)),
        Family("activity_series", ActivitySeries, _ws(ActivitySeries)),
        Family("activities", Activity, _ws(Activity)),
        Family("activity_workspaces", ActivityWorkspace, _activity_workspaces),
        Family("location_observations", LocationObservation, _ws(LocationObservation)),
        Family("spatial_features", SpatialFeature, _ws(SpatialFeature)),
        Family("place_levels", PlaceLevel, _ws(PlaceLevel)),
        Family("floor_plans", FloorPlan, _ws(FloorPlan), files=("storage_path", "source_path")),
        Family("indoor_placements", IndoorPlacement, _ws(IndoorPlacement)),
        Family("beam_model_documents", BeamModelDocument, _ws(BeamModelDocument)),
        Family("beam_model_values", BeamModelValue, _ws(BeamModelValue)),
        Family("beam_asset_bindings", BeamAssetBinding, _ws(BeamAssetBinding)),
        Family("equipment_class_requests", EquipmentClassRequest, _ws(EquipmentClassRequest)),
        Family("ai_suggestions", AiSuggestion, _ws(AiSuggestion)),
        Family("access_reviews", AccessReview, _ws(AccessReview)),
        Family("review_escalations", ReviewEscalation, _ws(ReviewEscalation)),
        Family("golden_incidents", GoldenIncident, _ws(GoldenIncident)),
        Family("llm_configs", LLMConfig, _llm, drop=("encrypted_secret", "last_checked_at", "last_check_error"),
               note="the AI endpoint, without its key: switched off until the key is given and it is checked"),
        Family("import_configs", ImportConfig, _ws(ImportConfig),
               drop=("encrypted_secret", "last_import_job_uid", "running_since", "next_run_at", "scheduled_by"),
               note="saved imports, without their credentials and with their schedules off"),
        Family("memberships", Membership, _ws(Membership), people=True),
        Family("role_bindings", RoleBinding, _ws(RoleBinding), people=True),
        Family("notification_subscriptions", NotificationSubscription, _ws(NotificationSubscription), people=True),
        Family("record_watchers", RecordWatcher, _watchers, people=True),
        Family("ticket_watchers", TicketWatcher, _by(TicketWatcher, "issue_uid", "tickets"), people=True),
    ]


# The people a bundle's rows name, carried as references (never credentials or login identities).
PEOPLE = User
PEOPLE_COLUMNS = ("id", "email", "name", "username")

REBUILT = {
    "users": "the people the records name are carried as references (e-mail, name) and matched or created",
    "package_installations": "the packages are installed again: the new workspace's installation history",
    "ledger_ticket_links": "the links between tickets and the equipment they name are derived again from the tickets",
    "asset_key_counters": "the next free key is found again: a counter skips the keys the imported records hold",
}

LEDGER = ("the evidence ledger keeps the source installation's sequence and proof; a bundle carries the records' "
          "current state and history — move the ledger with the signed portable archive")
NOT_CARRIED = {
    **{t: LEDGER for t in (
        "ledger_streams", "ledger_source_revisions", "ledger_claims", "ledger_claim_events", "ledger_revision_events",
        "ledger_decisions", "ledger_status_events", "ledger_identity_events", "ledger_record_events",
        "ledger_conflict_events", "ledger_fact_state", "ledger_identity_bindings", "ledger_conflicts",
        "ledger_stream_heads", "ledger_migration_map", "ledger_reconciliation_reports", "ledger_domains",
        "ledger_policies", "ledger_rulesets", "ledger_bulk_changes", "ledger_audit_digests",
        "ledger_derive_requests", "ledger_job_runs")},
    **{t: "a record of a migration run on the source installation; its results are the records themselves"
       for t in ("catalogue_mappings", "catalogue_mapping_items", "legacy_migration_plans", "legacy_migration_items",
                 "transfer_jobs", "import_jobs")},
    **{t: "assistant conversations and their feedback are personal, and stay where they were held"
       for t in ("ask_conversations", "ask_messages", "ask_actions", "ask_feedback")},
    **{t: "evaluations and runs of the source installation's AI models: evaluate the models again where they run"
       for t in ("intake_runs", "intake_outcomes", "intake_profiles")},
    **{t: "secret or runtime state of the source installation"
       for t in ("api_tokens", "devices", "uploads", "idempotency_records", "notifications", "notification_preferences",
                 "usage_llm", "usage_requests", "usage_presence", "usage_storage", "app_settings")},
    **{t: "the signed portable archive's own records"
       for t in ("portability_chain", "portability_download_tokens", "portability_events", "portability_exports",
                 "portability_imports", "portability_jobs", "portability_origin_records", "portability_repositories",
                 "portability_row_map", "portability_schedules", "portability_signing_keys", "portability_stores",
                 "portability_tags_seen", "portability_trusted_keys")},
    **{t: "instance-wide catalogue state, not one workspace's: the target installation keeps its own"
       for t in ("equipment_classes", "equipment_class_reviews", "package_snapshots")},
    "groups": "directory groups belong to the installation's directory: role bindings to a group need it there",
    "group_members": "directory groups belong to the installation's directory",
    "alembic_version": "the database's own schema revision",
    "spatial_ref_sys": "PostGIS's catalogue of coordinate systems, the same in every installation",
    **{t: "the meaning-search index is built from the records with the target's own embedding model "
          "(Administration → AI → index), never copied"
       for t in ("knowledge_chunks", "knowledge_index_runs")},
}

# Workspaces of a bundle that the not-carried tables hold rows for are named in the export's `not_reproduced`.
COUNTED = ("ledger_claims", "ledger_decisions", "ask_conversations", "import_jobs", "api_tokens", "intake_runs")
