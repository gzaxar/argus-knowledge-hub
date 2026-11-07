"""Historical identifiers (asset-model-revision §17.7 Lookup, A40).

Every Jira key, old Jira URL, Insight key and objectId that was migrated
resolves to the ARGUS record it became: through the ticket's source key,
the record's key, its `former_key` / `former_uid` / alias labels, or the
identity binding of the Insight object. A merged record resolves to its
survivor. An identifier that was never migrated returns its archive
location instead.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import parse_qs, unquote, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.asset_subresources import AssetLabel
from app.models.issue import Issue
from app.models.ledger import IdentityBinding, LedgerDomain

ALIAS_LABELS = ("former_key", "former_uid", "alias", "jiraObjectId")
# Labels whose value is matched exactly as scanned: a QR code and the aliases that a printed code may carry.
EXACT_LABELS = ("qrcode",) + ALIAS_LABELS
JIRA_BROWSE = re.compile(r"/browse/([A-Z][A-Z0-9_]+-\d+)")


def parse(identifier: str) -> dict:
    """What an identifier is: a Jira key, a URL naming one, or a key/id."""
    raw = unquote(identifier.strip())
    if raw.startswith(("http://", "https://")):
        url = urlparse(raw)
        m = JIRA_BROWSE.search(url.path)
        if m:
            return {"key": m.group(1), "source": "jira-url"}
        qs = parse_qs(url.query)
        if "selectedIssue" in qs:
            return {"key": qs["selectedIssue"][0], "source": "jira-url"}
        if "objectId" in qs:
            return {"object_id": qs["objectId"][0], "source": "insight-url"}
        if "id" in qs and url.path.endswith("ShowObject.jspa"):
            return {"object_id": qs["id"][0], "source": "insight-url"}
        return {"key": url.path.rstrip("/").rsplit("/", 1)[-1], "source": "url"}
    return {"key": raw, "source": "key"}


def _survivor(db: Session, asset: Optional[Asset]) -> Optional[Asset]:
    seen = set()
    while asset is not None and asset.merged_into_uid and asset.uid not in seen:
        seen.add(asset.uid)
        asset = db.get(Asset, asset.merged_into_uid)
    return asset


def _asset_hit(db: Session, asset: Optional[Asset], via: str) -> Optional[dict]:
    asset = _survivor(db, asset)
    if asset is None:
        return None
    return {"kind": "asset", "uid": asset.uid, "key": asset.key, "name": asset.name, "type": asset.type,
            "workspace_id": asset.workspace_id, "path": f"/assets/{asset.uid}", "via": via}


def resolve(db: Session, identifier: str, workspace_ids: Optional[Iterable[str]] = None, *,
            by_object_id: bool = False) -> Optional[dict]:
    """The ARGUS record an identifier became, among these workspaces."""
    ws = list(workspace_ids) if workspace_ids is not None else None
    parsed = {"object_id": identifier, "source": "objectId"} if by_object_id else parse(identifier)

    def in_scope(workspace_id: str) -> bool:
        return ws is None or workspace_id in ws

    # A label's value exactly as printed (a QR code of a web address, an alias that is a whole link, a number)
    # is what was scanned: a QR code first, then the aliases a printed code may carry — before the identifier
    # is taken apart, and before a number is read as an Insight objectId.
    whole = identifier.strip()
    if not by_object_id and whole:
        for label_type in EXACT_LABELS:
            for label in db.scalars(select(AssetLabel).where(AssetLabel.value == whole, AssetLabel.type == label_type)):
                hit = _asset_hit(db, db.get(Asset, label.asset_uid), label.type)
                if hit and in_scope(hit["workspace_id"]):
                    return hit
    object_id = parsed.get("object_id")
    key = parsed.get("key")
    if object_id is None and key and key.isdigit():
        object_id = key
    if object_id is not None:
        b = db.get(IdentityBinding, f"insight:object:{object_id}")
        hit = _asset_hit(db, db.get(Asset, b.uid), "objectId") if b else None
        if hit and in_scope(hit["workspace_id"]):
            return hit
    if not key:
        return None
    q = select(Issue).where(Issue.attributes["argus_source_key"].astext == key)
    for issue in db.scalars(q):
        if in_scope(issue.workspace_id):
            return {"kind": "ticket", "uid": issue.uid, "key": key, "name": issue.title,
                    "workspace_id": issue.workspace_id, "path": f"/tickets/{issue.uid}", "via": "jira key"}
    issue = db.get(Issue, key) or db.scalar(select(Issue).where(Issue.key == key))
    if issue is not None and in_scope(issue.workspace_id):
        return {"kind": "ticket", "uid": issue.uid, "key": key, "name": issue.title,
                "workspace_id": issue.workspace_id, "path": f"/tickets/{issue.uid}", "via": "uid"}
    for asset in db.scalars(select(Asset).where(Asset.key == key)):
        hit = _asset_hit(db, asset, "key")
        if hit and in_scope(hit["workspace_id"]):
            return hit
    for label in db.scalars(select(AssetLabel).where(AssetLabel.value == key, AssetLabel.type.in_(ALIAS_LABELS))):
        hit = _asset_hit(db, db.get(Asset, label.asset_uid), label.type)
        if hit and in_scope(hit["workspace_id"]):
            return hit
    asset = db.get(Asset, key)
    if asset is not None:
        hit = _asset_hit(db, asset, "uid")
        if hit and in_scope(hit["workspace_id"]):
            return hit
    return None


def archive_location(db: Session, identifier: str, workspace_ids: Optional[Iterable[str]] = None) -> Optional[str]:
    """Where an identifier that was never migrated can still be read."""
    parsed = parse(identifier)
    key = parsed.get("key") or parsed.get("object_id")
    q = select(LedgerDomain).where(LedgerDomain.archive_url.isnot(None))
    if workspace_ids is not None:
        q = q.where(LedgerDomain.workspace_id.in_(list(workspace_ids)))
    for d in db.scalars(q):
        template = d.archive_url
        return template.format(key=key) if "{key}" in template else f"{template.rstrip('/')}/browse/{key}"
    return identifier if identifier.startswith(("http://", "https://")) else None
