"""Import issues from a Jira issue tracker (issues.infn.it) as tickets.

Distinct from jira_import, which reads Insight/Assets *objects*. This
reads the issue tracker: work, not equipment. The two meet where a ticket
names an asset — an Insight object referenced from an issue becomes a
link between the ticket and the object already imported here.
"""
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.asset import Asset
from app.models.asset_subresources import AssetTicket
from app.models.import_job import ImportJob
from app.models.issue import Issue, IssueComment, IssueHistory, IssueLink
from app.services.import_merge import effective_strategy, should_write
from app.services.ticket_types import (
    ensure_ticket_kinds,
    migrate_legacy_attributes,
)
from app.services.jira_import import (
    _TimeoutSession,
    _author_display_name,
    _describe_error,
    _parse_jira_dt,
    _record_diagnostic,
    _set_progress,
)

PAGE_SIZE = 100

# Jira lets every project invent its own workflow, so the specific status
# names can't be relied on. Every status does carry a statusCategory, which
# Jira itself constrains to three values — that is the part worth mapping.
_CATEGORY_TO_STATE = {
    "new": "new",
    "undefined": "new",
    "indeterminate": "in_progress",
    "done": "resolved",
}

# Where a status name is unambiguous, it beats the category: "Closed" and
# "Pending" are both meaningful distinctions that the three categories flatten
# away ("done" and "indeterminate" respectively).
_NAME_TO_STATE = {
    "closed": "closed",
    "chiuso": "closed",
    "done": "closed",
    "resolved": "resolved",
    "risolto": "resolved",
    "pending": "pending",
    "in attesa": "pending",
    "waiting": "pending",
    "waiting for customer": "pending",
    "waiting for support": "pending",
    "on hold": "pending",
    "sospeso": "pending",
    "in progress": "in_progress",
    "in corso": "in_progress",
    "open": "new",
    "aperto": "new",
    "to do": "new",
    "new": "new",
    "nuovo": "new",
}

# Jira ships two priority schemes depending on the project template, and
# INFN's tracker may use either.
_PRIORITY_MAP = {
    "blocker": "blocker", "bloccante": "blocker",
    "critical": "critical", "critico": "critical", "highest": "critical",
    "major": "high", "high": "high", "alta": "high", "alto": "high",
    "medium": "medium", "normal": "medium", "media": "medium", "normale": "medium",
    "minor": "low", "low": "low", "bassa": "low", "basso": "low",
    "trivial": "low", "lowest": "low",
}


def map_state(status: dict) -> str:
    """Jira status -> one of our five ticket states."""
    name = (status.get("name") or "").strip().lower()
    if name in _NAME_TO_STATE:
        return _NAME_TO_STATE[name]
    category = ((status.get("statusCategory") or {}).get("key") or "").strip().lower()
    return _CATEGORY_TO_STATE.get(category, "new")


def map_priority(priority: Optional[dict]) -> Optional[str]:
    if not priority:
        return None
    name = (priority.get("name") or "").strip().lower()
    return _PRIORITY_MAP.get(name)


def _person(value) -> Optional[str]:
    """A Jira user object down to something displayable. Deliberately the
    display name rather than an account id: these become ticket text, and a
    directory-backed assignee is a separate concern (the `user` attribute
    type) rather than something to guess at here."""
    if not value:
        return None
    return _author_display_name(value)


# Jira Server is commonly published under a context path rather than at the
# host root — INFN's is at https://issues.infn.it/jira — and the site root
# still serves a normal web page, so the mistake looks like a working URL
# right up until the API returns 404 for a reason it doesn't explain.
_CONTEXT_PATH_CANDIDATES = ("", "/jira")


def resolve_api_base(jira, base_url: str) -> str:
    """The base URL whose REST API actually answers.

    serverInfo needs no authentication, so this also distinguishes "wrong
    URL" from "wrong token" before the first real request: a 404 here is the
    address, a 401 later is the credential.
    """
    tried = []
    for suffix in _CONTEXT_PATH_CANDIDATES:
        candidate = f"{base_url}{suffix}"
        url = f"{candidate}/rest/api/2/serverInfo"
        tried.append(url)
        try:
            resp = jira.get(url)
        except Exception:
            continue
        if resp.status_code == 404:
            continue
        # Anything else means something is listening on the API: 200, or a
        # 401 from an instance that doesn't expose serverInfo anonymously.
        if resp.status_code < 500:
            return candidate
    raise RuntimeError(
        "No Jira REST API found. Tried: " + ", ".join(tried) +
        ". Check the server URL — Jira is often published under a context "
        "path such as https://issues.infn.it/jira rather than the site root."
    )


# Agile fields have no fixed id: "Sprint" is customfield_10007 on one Jira
# and customfield_10112 on the next, so they're found by name.
_AGILE_FIELD_NAMES = {
    "epic link": "argus_epic",
    "epic name": "argus_epic_name",
    "sprint": "argus_sprint",
    "story points": "argus_story_points",
    "story point estimate": "argus_story_points",
}


def discover_agile_fields(jira, base_url: str) -> dict[str, str]:
    """custom field id -> our attribute key, for the agile fields this Jira
    happens to define. Missing ones simply don't appear."""
    try:
        resp = jira.get(f"{base_url}/rest/api/2/field")
        resp.raise_for_status()
        fields = resp.json()
    except Exception:
        # Not fatal: the import proceeds without epic/sprint/points.
        return {}
    out: dict[str, str] = {}
    for field in fields:
        name = (field.get("name") or "").strip().lower()
        key = _AGILE_FIELD_NAMES.get(name)
        if key and field.get("id"):
            out[field["id"]] = key
    return out


def _sprint_names(value) -> list[str]:
    """Jira Server returns sprints either as objects or as the toString of a
    Java bean — "...,name=Sprint 4,startDate=..." — depending on version."""
    out = []
    for entry in value if isinstance(value, list) else [value]:
        if isinstance(entry, dict):
            if entry.get("name"):
                out.append(entry["name"])
        elif isinstance(entry, str):
            match = re.search(r"name=([^,\]]+)", entry)
            out.append(match.group(1) if match else entry)
    return out


def _agile_attributes(fields: dict, agile_fields: dict[str, str]) -> dict:
    out: dict = {}
    for field_id, key in agile_fields.items():
        value = fields.get(field_id)
        if value in (None, "", []):
            continue
        if key == "argus_sprint":
            out[key] = _sprint_names(value)
        elif key == "argus_story_points":
            out[key] = value
        else:
            out[key] = value.get("name") if isinstance(value, dict) else value
    return out


def _search_issues(jira, base_url: str, jql: str, start_at: int, extra_fields: tuple = ()) -> dict:
    resp = jira.get(
        f"{base_url}/rest/api/2/search",
        params={
            "jql": jql,
            "startAt": start_at,
            "maxResults": PAGE_SIZE,
            # Naming the fields keeps the payload to what is actually mapped;
            # a Jira issue with every field expanded is enormous.
            "fields": ",".join([
                "summary", "description", "status", "priority", "assignee",
                "reporter", "labels", "duedate", "resolutiondate", "created",
                "updated", "issuetype", "project", "components",
                # The rest of what a standard issue view shows.
                "resolution", "fixVersions", "versions", "votes", "watches",
                "environment", "parent", "timeoriginalestimate", "timespent",
                "attachment",
                *extra_fields,
            ]),
        },
    )
    resp.raise_for_status()
    return resp.json()


def _names(values) -> list[str]:
    return [v.get("name") for v in (values or []) if isinstance(v, dict) and v.get("name")]


# Jira issue type -> the ARGUS category it means. Only the unambiguous
# ones: a "Task" says nothing about whether it was a fault or an upgrade,
# so it is left for a person to classify rather than guessed at.
_TYPE_TO_CATEGORY = {
    "bug": "fault",
    "fault": "fault",
    "guasto": "fault",
    "incident": "fault",
    "maintenance": "maintenance",
    "manutenzione": "maintenance",
    "improvement": "upgrade",
    "new feature": "upgrade",
    "service request": "request",
    "support": "request",
    "richiesta": "request",
}


def _issue_attributes(base_url: str, jira_key: str, fields: dict) -> dict:
    """One Jira issue mapped onto the ARGUS ticket fields.

    Jira is a source, not the model: what it called a field is recorded as
    provenance (argus_source_*), and its values land on the ARGUS keys that
    mean the same thing. Fields ARGUS has and Jira doesn't — impact, root
    cause, downtime — are left empty for a person to fill rather than
    invented here.
    """
    parent = fields.get("parent") or {}
    issue_type = (fields.get("issuetype") or {}).get("name")
    out = {
        "argus_source": "jira",
        "argus_source_key": jira_key,
        "argus_source_url": f"{base_url}/browse/{jira_key}",
        "argus_project": (fields.get("project") or {}).get("key"),
        "argus_source_status": (fields.get("status") or {}).get("name"),
        "argus_source_type": issue_type,
        "argus_source_created": fields.get("created"),
        "argus_source_updated": fields.get("updated"),
        # Jira reports an unresolved issue as a null resolution; saying so is
        # more useful in a list than an empty cell.
        "argus_resolution": (fields.get("resolution") or {}).get("name") or "Unresolved",
        "argus_components": _names(fields.get("components")),
        "argus_fix_versions": _names(fields.get("fixVersions")),
        "argus_affects_versions": _names(fields.get("versions")),
        "argus_reporter": _person(fields.get("reporter")),
        "argus_votes": (fields.get("votes") or {}).get("votes"),
        "argus_watchers": (fields.get("watches") or {}).get("watchCount"),
        "argus_environment": fields.get("environment"),
        "argus_parent": parent.get("key"),
        "argus_time_spent": fields.get("timespent"),
        "argus_time_estimate": fields.get("timeoriginalestimate"),
    }
    category = _TYPE_TO_CATEGORY.get((issue_type or "").strip().lower())
    if category:
        out["argus_category"] = category
    return out


def _import_attachments(jira, workspace_id: str, issue: Issue, fields: dict, db: Session,
                        job: ImportJob, seen: set) -> int:
    """Attachment metadata rides along in the search payload, so the files
    are fetched without asking Jira what exists first."""
    from app.models.attachment import Attachment
    from app.services.jira_import import _download_attachment

    added = 0
    for att in fields.get("attachment") or []:
        content_url = att.get("content")
        if not content_url:
            continue
        backend_id = f"jira-issue:{att.get('id')}"
        existing = db.scalar(
            select(Attachment).where(
                Attachment.workspace_id == workspace_id,
                Attachment.backend_id == backend_id,
            )
        )
        if existing is not None:
            continue
        try:
            row = _download_attachment(
                jira, workspace_id, content_url,
                filename=att.get("filename") or backend_id,
                mime_type=att.get("mimeType"),
                backend_id=backend_id,
            )
        except Exception as e:
            _record_diagnostic(job, seen, "issue_attachments", _describe_error(e, None))
            continue
        # Attachments hang off assets in this model; an issue's file is kept
        # with the object the ticket is about when there is one, and
        # otherwise stands alone in the workspace.
        # The ticket owns its files; linking to the object as well would
        # scatter a fault screenshot into the equipment record.
        row.issue_uid = issue.uid
        db.add(row)
        added += 1
    return added


def _import_history(jira, base_url: str, issue: Issue, jira_key: str, db: Session,
                    job: ImportJob, seen: set) -> int:
    """Jira's changelog, so an imported ticket doesn't look like it sprang
    into being at import time."""
    try:
        resp = jira.get(
            f"{base_url}/rest/api/2/issue/{jira_key}",
            params={"expand": "changelog", "fields": "created"},
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        _record_diagnostic(job, seen, "history", _describe_error(e, None))
        return 0

    existing = {
        h.backend_id
        for h in db.scalars(select(IssueHistory).where(IssueHistory.issue_uid == issue.uid))
        if h.backend_id
    }
    added = 0
    for entry in ((payload.get("changelog") or {}).get("histories") or []):
        author = _person(entry.get("author")) or "unknown"
        when = _parse_jira_dt(entry.get("created"))
        for item in entry.get("items") or []:
            backend_id = f"{entry.get('id')}:{item.get('field')}"
            if backend_id in existing:
                continue
            existing.add(backend_id)
            db.add(IssueHistory(
                uid=f"{issue.uid}-h{backend_id}",
                issue_uid=issue.uid,
                type="updated",
                author=author,
                field=item.get("field"),
                from_value=item.get("fromString"),
                to_value=item.get("toString"),
                timestamp=when or datetime.now(timezone.utc),
                backend_id=backend_id,
            ))
            added += 1
    return added


def _import_comments(jira, base_url: str, issue: Issue, jira_key: str, db: Session,
                     job: ImportJob, seen: set) -> int:
    try:
        resp = jira.get(f"{base_url}/rest/api/2/issue/{jira_key}/comment")
        resp.raise_for_status()
        comments = resp.json().get("comments") or []
    except Exception as e:
        _record_diagnostic(job, seen, "comments", _describe_error(e, None))
        return 0

    existing = {
        c.uid for c in db.scalars(select(IssueComment).where(IssueComment.issue_uid == issue.uid))
    }
    added = 0
    for c in comments:
        uid = f"{issue.uid}-c{c.get('id')}"
        if uid in existing:
            continue
        db.add(IssueComment(
            uid=uid,
            issue_uid=issue.uid,
            author=_person(c.get("author")) or "unknown",
            body=c.get("body") or "",
        ))
        added += 1
    return added


# An Insight/Jira object key: letters and digits, a hyphen, then digits —
# "LNFT2-145356". Matched as whole words so a longer identifier that merely
# contains one isn't mistaken for it.
_KEY_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]*-\d+\b")


def _link_mentioned_assets(
    db: Session, issue: Issue, text: str, key_to_asset: dict[str, str]
) -> int:
    """A ticket that names an asset key gets linked to that object.

    Jira's own Insight link fields are a paid add-on and not on every
    project, but the key ("LNFT2-145356") is routinely written into the
    summary or description — enough to connect work to equipment, which is
    the point of having both in one place.

    Candidate keys are pulled out of the text and looked up, rather than
    testing every asset against every ticket: with 3561 assets that second
    shape is millions of comparisons per import.
    """
    if not text:
        return 0
    jira_key = (issue.attributes or {}).get("argus_source_key") or issue.uid
    linked = 0
    for candidate in set(_KEY_PATTERN.findall(text)):
        asset_uid = key_to_asset.get(candidate)
        if asset_uid is None:
            continue
        exists = db.scalar(
            select(AssetTicket).where(
                AssetTicket.asset_uid == asset_uid,
                AssetTicket.ticket_key == jira_key,
            )
        )
        if exists is None:
            now = datetime.now(timezone.utc)
            db.add(AssetTicket(
                uid=str(uuid.uuid4()),
                asset_uid=asset_uid,
                ticket_key=jira_key,
                summary=issue.title,
                type=(issue.attributes or {}).get("argus_source_type") or "Task",
                status=issue.state,
                created=now,
                updated=now,
                backend_url=(issue.attributes or {}).get("argus_source_url"),
            ))
            linked += 1
        # The ticket's own asset_uid points at the first object named; the
        # rest are recorded as links, since a ticket has one subject but may
        # mention several.
        if issue.asset_uid is None:
            issue.asset_uid = asset_uid
    return linked


# Which attribute holds a key pointing at another ticket, and what the edge
# between them means.
_TICKET_KEY_RELATIONS = (("argus_epic", "epic"), ("argus_parent", "parent"))


def _link_related_tickets(db: Session, workspace_id: str) -> int:
    """Turn the epic/parent keys into edges.

    Run after every page, because an epic is often imported after the
    stories that name it — resolving as each ticket is written would miss
    exactly the forward references that matter.
    """
    issues = db.scalars(select(Issue).where(Issue.workspace_id == workspace_id)).all()
    by_source_key = {
        (i.attributes or {}).get("argus_source_key"): i.uid
        for i in issues
        if (i.attributes or {}).get("argus_source_key")
    }
    existing = {
        (link.from_issue_uid, link.to_issue_uid, link.relation_type)
        for link in db.scalars(select(IssueLink))
    }
    now = datetime.now(timezone.utc)
    created = 0
    for issue in issues:
        attributes = issue.attributes or {}
        for key_attribute, relation in _TICKET_KEY_RELATIONS:
            target_key = attributes.get(key_attribute)
            target_uid = by_source_key.get(target_key) if target_key else None
            # A key naming a ticket outside this import stays as the
            # attribute value — a dangling edge would be worse than none.
            if not target_uid or target_uid == issue.uid:
                continue
            triple = (issue.uid, target_uid, relation)
            if triple in existing:
                continue
            existing.add(triple)
            db.add(IssueLink(
                from_issue_uid=issue.uid, to_issue_uid=target_uid,
                relation_type=relation, created_at=now,
            ))
            created += 1
    db.commit()
    return created


def run_jira_issue_import(
    job_uid: str,
    workspace_id: str,
    base_url: str,
    pat: str,
    jql: str,
    merge_strategy: str = "override",
    schema_uid: Optional[str] = None,
    link_assets: bool = True,
) -> None:
    db = SessionLocal()
    job = db.get(ImportJob, job_uid)
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    db.commit()

    seen_diagnostics: set = set()
    base_url = base_url.rstrip("/")

    try:
        jira = _TimeoutSession()
        jira.headers.update({"Authorization": f"Bearer {pat}", "Accept": "application/json"})

        resolved_base = resolve_api_base(jira, base_url)
        if resolved_base != base_url:
            _set_progress(db, job, f"Jira API found at {resolved_base}")
        base_url = resolved_base

        merge_strategy, retired = effective_strategy(merge_strategy)
        if retired:
            _set_progress(db, job, retired)

        # Built once: the importer resolves asset keys mentioned in ticket
        # text, and rebuilding this per issue would dominate the run.
        key_to_asset = dict(
            db.execute(
                select(Asset.key, Asset.uid).where(Asset.workspace_id == workspace_id)
            ).all()
        ) if link_assets else {}

        type_uids: dict[str, str] = {}
        agile_fields = discover_agile_fields(jira, base_url)
        if agile_fields:
            _set_progress(db, job, f"Found {len(agile_fields)} agile field(s)")

        _set_progress(db, job, "Searching Jira")
        start_at = 0
        total = None
        imported = comments_imported = links = attachments_imported = 0
        history_imported = 0

        while True:
            try:
                page = _search_issues(
                    jira, base_url, jql, start_at, tuple(agile_fields)
                )
            except Exception as e:
                raise RuntimeError(f"Jira search failed: {_describe_error(e, None)}") from e

            if total is None:
                total = page.get("total", 0)
                _set_progress(db, job, f"{total} issue(s) match")

            # Seeded from what this page actually contains, so a project of
            # only Tasks doesn't acquire empty Bug and Story types.
            page_types = {
                ((i.get("fields") or {}).get("issuetype") or {}).get("name")
                for i in (page.get("issues") or [])
            }
            new_types = page_types - set(type_uids)
            if new_types:
                type_uids.update(
                    ensure_ticket_kinds(db, workspace_id, page_types | set(type_uids))
                )
                db.commit()

            issues = page.get("issues") or []
            if not issues:
                break

            for jira_issue in issues:
                jira_key = jira_issue.get("key")
                if not jira_key:
                    continue
                fields = jira_issue.get("fields") or {}

                uid = f"{workspace_id}:{jira_key}"
                issue = db.get(Issue, uid)
                is_new = issue is None
                if is_new:
                    issue = Issue(uid=uid, workspace_id=workspace_id)

                if not should_write(
                    merge_strategy, is_new,
                    None if is_new else issue.updated_at,
                    _parse_jira_dt(fields.get("updated")),
                ):
                    continue

                issue.title = fields.get("summary") or jira_key
                issue.description = fields.get("description")
                issue.state = map_state(fields.get("status") or {})
                issue.priority = map_priority(fields.get("priority"))
                issue.assignee = _person(fields.get("assignee"))
                issue.created_by = _person(fields.get("reporter"))
                issue.labels = list(fields.get("labels") or [])
                issue.due_date = _parse_jira_dt(fields.get("duedate"))
                issue.closed_at = _parse_jira_dt(fields.get("resolutiondate"))
                # What Jira knows that our columns don't, kept rather than
                # discarded: the key is what a person searches for, and the
                # rest explains where the ticket came from.
                # Anything still under a Jira-era key is moved onto the
                # ARGUS one first, so a re-import updates a ticket rather
                # than leaving two spellings of the same field behind.
                attributes = migrate_legacy_attributes(issue.attributes)
                attributes.update(_issue_attributes(base_url, jira_key, fields))
                attributes.update(_agile_attributes(fields, agile_fields))
                issue.attributes = attributes
                issue_type_name = (fields.get("issuetype") or {}).get("name")
                if issue_type_name and issue_type_name in type_uids:
                    issue.schema_uid = type_uids[issue_type_name]
                elif schema_uid:
                    issue.schema_uid = schema_uid

                # One savepoint per issue: a bad row is skipped without
                # discarding the rest of the page, which a bare rollback here
                # would do — the page's earlier issues are uncommitted too.
                try:
                    with db.begin_nested():
                        db.add(issue)
                        db.flush()
                        comments = _import_comments(
                            jira, base_url, issue, jira_key, db, job, seen_diagnostics
                        )
                        attachments = _import_attachments(
                            jira, workspace_id, issue, fields, db, job, seen_diagnostics
                        )
                        history = _import_history(
                            jira, base_url, issue, jira_key, db, job, seen_diagnostics
                        )
                        asset_links = 0
                        if link_assets:
                            asset_links = _link_mentioned_assets(
                                db, issue, f"{issue.title}\n{issue.description or ''}",
                                key_to_asset,
                            )
                        db.flush()
                except Exception as e:
                    _set_progress(
                        db, job, f"Skipped {jira_key}: {_describe_error(e, None)}", errors=1
                    )
                    continue

                imported += 1
                comments_imported += comments
                attachments_imported += attachments
                history_imported += history
                links += asset_links

                if imported % 25 == 0:
                    db.commit()
                    _set_progress(db, job, f"{imported} of {total} issue(s)")

            db.commit()
            start_at += len(issues)
            if start_at >= (total or 0):
                break

        # Epic and parent arrive as keys, and the ticket they name may not
        # have existed yet when the row was written — so they become edges
        # once every page is in.
        ticket_links = _link_related_tickets(db, workspace_id)
        if ticket_links:
            _set_progress(db, job, f"Linked {ticket_links} ticket(s) to their epic or parent")

        _set_progress(
            db, job, f"Imported {imported} ticket(s)",
            tickets=imported, comments=comments_imported, asset_links=links,
            attachments=attachments_imported, history=history_imported,
            ticket_links=ticket_links,
        )

        job.status = "succeeded"
        job.progress = "Import complete"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        db.rollback()
        job = db.get(ImportJob, job_uid)
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
