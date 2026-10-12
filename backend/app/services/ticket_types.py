"""The application's own ticket types.

These are ARGUS types, not Jira ones. Jira is a source that maps onto
them, the same way a second tracker or an alarm system would — so the
field keys are argus_*, and what Jira happened to call a field is kept as
provenance rather than being the model.

One base type carries the fields every ticket has, with a child per kind
of work (Epic, Story, Task, Bug, Sub-task) inheriting them, so a project
can add a field to Bugs alone.

What a ticket is *about* is deliberately not an attribute. Objects and
documents are linked through their own tables — asset_tickets and
document_relations — because those are edges the knowledge graph has to
traverse from either end: "what broke this magnet" matters as much as
"what does this ticket affect", and an attribute holding a uid answers
only the second.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.schema import Schema

BASE_UID_SUFFIX = "argus-ticket"
BASE_TYPE_NAME = "Ticket"

# The kinds of work a ticket can be, and the fields every ticket carries: the core-facility package
# (backend/packages/core-facility/ticket_types.yaml). Close to what trackers use, so an import needs no
# mapping for the common case; the operational fields (category, impact, downtime) are what ARGUS reasons over.
def _definitions():
    from app.packages import defaults
    return defaults.ticket_types()


DEFAULT_ISSUE_TYPES = tuple(name for name, _, _ in _definitions().kinds)
BASE_DESCRIPTION = _definitions().base_description


def _options_of(key: str) -> list[dict]:
    for a in _definitions().base_attributes:
        if a["key"] == key:
            return [dict(o) for o in a.get("options") or []]
    return []


# The operational classifications, as the AI drafting reads them.
CATEGORY_OPTIONS = _options_of("argus_category")
IMPACT_OPTIONS = _options_of("argus_impact")
DETECTED_BY_OPTIONS = _options_of("argus_detected_by")

# Keys written while the model was still Jira's. Mapped rather than
# dropped: the tickets already imported hold real values under them.
LEGACY_KEY_MAP = {
    # The first importer's spelling.
    "jiraKey": "argus_source_key",
    "jiraUrl": "argus_source_url",
    "jiraProject": "argus_project",
    "jiraStatus": "argus_source_status",
    "jiraIssueType": "argus_source_type",
    "jiraComponents": "argus_components",
    # The Jira-shaped ticket type that replaced it.
    "jira_key": "argus_source_key",
    "jira_url": "argus_source_url",
    "jira_project": "argus_project",
    "jira_status": "argus_source_status",
    "jira_issue_type": "argus_source_type",
    "jira_resolution": "argus_resolution",
    "jira_components": "argus_components",
    "jira_fix_versions": "argus_fix_versions",
    "jira_affects_versions": "argus_affects_versions",
    "jira_reporter": "argus_reporter",
    "jira_votes": "argus_votes",
    "jira_watchers": "argus_watchers",
    "jira_created": "argus_source_created",
    "jira_updated": "argus_source_updated",
    "jira_environment": "argus_environment",
    "jira_parent": "argus_parent",
    "jira_time_spent": "argus_time_spent",
    "jira_time_estimate": "argus_time_estimate",
    "jira_epic": "argus_epic",
    "jira_epic_name": "argus_epic_name",
    "jira_sprint": "argus_sprint",
    "jira_story_points": "argus_story_points",
}


def base_attributes() -> list[dict]:
    return [dict(a) for a in _definitions().base_attributes]


def ensure_ticket_types(db: Session, workspace_id: str, issue_type_names: set[str]) -> dict:
    """Create (or refresh) the base ticket type and a child per kind of
    work. Returns name -> schema uid.

    Idempotent and safe on every import: the base type's field set is kept
    current so a release that adds a field reaches existing workspaces,
    while children are left alone once created, since a workspace may have
    added fields of its own to them.
    """
    base_uid = f"{workspace_id}:{BASE_UID_SUFFIX}"
    base = db.get(Schema, base_uid)
    if base is None:
        base = Schema(
            uid=base_uid,
            workspace_id=workspace_id,
            name=BASE_TYPE_NAME,
            description=BASE_DESCRIPTION,
            applies_to="tickets",
            is_concrete=False,
            attributes=base_attributes(),
            metadata_json={"source": "argus"},
        )
        db.add(base)
    else:
        base.attributes = base_attributes()
    db.flush()

    out: dict[str, str] = {}
    for name in sorted(n for n in issue_type_names if n):
        child_uid = f"{base_uid}:{name.lower().replace(' ', '-')}"
        child = db.get(Schema, child_uid)
        if child is None:
            child = Schema(
                uid=child_uid,
                workspace_id=workspace_id,
                name=name,
                applies_to="tickets",
                parent_schema_uid=base.uid,
                attributes=[],
                metadata_json={"source": "argus"},
            )
            db.add(child)
        out[name] = child_uid
    db.flush()
    # Each type its default icon, where it has none (catalogue_icons); never over one chosen or imported.
    from app.services import catalogue_icons
    # Every ticket type of the workspace, imported ones included (they take the base type's icon).
    from sqlalchemy import select as _select
    every = {s.name: s.uid for s in db.scalars(_select(Schema).where(Schema.workspace_id == workspace_id,
                                                                    Schema.applies_to == "tickets"))}
    catalogue_icons.apply(db, workspace_id, every, False, icon_of=catalogue_icons.ticket_icon)
    return out


def migrate_legacy_attributes(attributes: dict) -> dict:
    """Rewrite a ticket's attributes from the Jira-shaped keys onto the
    ARGUS ones, leaving anything else untouched. A value already under the
    ARGUS key wins, so this is safe to run twice."""
    out = dict(attributes or {})
    for legacy, current in LEGACY_KEY_MAP.items():
        if legacy not in out:
            continue
        value = out.pop(legacy)
        out.setdefault(current, value)
    return out


def existing_ticket_type_uids(db: Session, workspace_id: str) -> list[str]:
    base_uid = f"{workspace_id}:{BASE_UID_SUFFIX}"
    return list(
        db.scalars(
            select(Schema.uid).where(
                Schema.workspace_id == workspace_id,
                Schema.parent_schema_uid == base_uid,
            )
        )
    ) + [base_uid]
