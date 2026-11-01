"""What the field client needs from the server beyond the ordinary API
(asset-model-revision §24.3, flutter-app-design §3, §7).

* `/v1/devices`: register the device a person signs in on, list one's
  devices, revoke one. A revoked device's next request answers 401
  `revoked` and the client wipes itself (A71).
* `/v1/links/resolve`: the stable universal links (`/asset/<uid>`,
  `/position/<uid>`, `/installation/<uid>`, `/document/<uid>`,
  `/ticket/<key>`, `/review/<uid>`, `/lookup/<key>`) as the record they
  open, for the web application and the field client alike. A record the
  caller may not read answers exactly as a missing one (I-ACL-1).
"""
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.visibility import reachable_in
from app.auth import PatIdentity, get_grants, get_identity
from app.db import get_db
from app.models.asset import Asset
from app.models.device import Device

devices_router = APIRouter(prefix="/v1/devices", tags=["field client"])
links_router = APIRouter(prefix="/v1/links", tags=["field client"])


def principal_of(identity) -> str:
    if isinstance(identity, PatIdentity):
        return f"pat:{identity.workspace_id}"
    return identity.user.id


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DeviceIn(BaseModel):
    installation_id: str
    platform: str
    app_version: str
    name: Optional[str] = None


def _view(d: Device) -> dict:
    return {"id": d.id, "platform": d.platform, "app_version": d.app_version, "name": d.name,
            "registered_at": d.registered_at, "last_seen_at": d.last_seen_at, "last_sync_at": d.last_sync_at,
            "revoked_at": d.revoked_at, "revoked_by": d.revoked_by, "revoke_reason": d.revoke_reason}


@devices_router.post("", status_code=201)
def register_device(body: DeviceIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Register (or re-register) this installation for the signed-in person."""
    if not body.installation_id.strip() or not body.platform.strip():
        raise HTTPException(status_code=422, detail={"error": "installation_id and platform are required",
                                                     "code": "invalid"})
    who = principal_of(identity)
    d = db.scalar(select(Device).where(Device.principal == who, Device.installation_id == body.installation_id,
                                       Device.revoked_at.is_(None)))
    if d is None:
        d = Device(id=str(uuid.uuid4()), principal=who, installation_id=body.installation_id.strip(),
                   platform=body.platform.strip().lower(), app_version=body.app_version.strip(), name=body.name)
        db.add(d)
    else:
        d.app_version, d.name = body.app_version.strip(), body.name or d.name
    d.last_seen_at = _now()
    db.commit()
    return _view(d)


@devices_router.get("")
def my_devices(identity=Depends(get_identity), db: Session = Depends(get_db)):
    """The devices registered for the signed-in person (all of them, for an administrator)."""
    q = select(Device).order_by(Device.registered_at.desc())
    if isinstance(identity, PatIdentity) or not identity.user.is_admin:
        q = q.where(Device.principal == principal_of(identity))
    return [_view(d) for d in db.scalars(q)]


class RevokeIn(BaseModel):
    reason: str


@devices_router.post("/{device_id}/revoke")
def revoke_device(device_id: str, body: RevokeIn, identity=Depends(get_identity), db: Session = Depends(get_db)):
    """Revoke a device: its next request answers 401 `revoked`, and it wipes itself."""
    d = db.get(Device, device_id)
    admin = not isinstance(identity, PatIdentity) and identity.user.is_admin
    if d is None or (d.principal != principal_of(identity) and not admin):
        raise HTTPException(status_code=404, detail={"error": "no such device", "code": "not_found"})
    if not body.reason.strip():
        raise HTTPException(status_code=422, detail={"error": "say why", "code": "invalid"})
    if d.revoked_at is None:
        d.revoked_at, d.revoked_by, d.revoke_reason = _now(), principal_of(identity), body.reason.strip()
    db.commit()
    return _view(d)


def device_refusal(db: Session, device_id: Optional[str]) -> Optional[dict]:
    """The 401 body when the request comes from a revoked device, else None. Marks it seen."""
    if not device_id:
        return None
    d = db.get(Device, device_id)
    if d is None:
        return None
    if d.revoked_at is not None:
        return {"error": "This device was signed out of ARGUS. Its local data has to be removed.",
                "code": "revoked"}
    now = _now()
    if d.last_seen_at is None or (now - d.last_seen_at).total_seconds() > 60:
        d.last_seen_at = now
        db.commit()
    return None


# --------------------------------------------------------------------------- universal links

KINDS = ("asset", "position", "installation", "document", "ticket", "review", "lookup")


def _not_found():
    raise HTTPException(status_code=404, detail={"error": "Not found, or not visible to you.", "code": "not_found"})


def _asset_link(db: Session, uid: str, workspace_id: str, grants, kind: str) -> dict:
    from app.intake.guide import nature
    from app.models.schema import Schema
    from app.services.visibility import asset_visible_in
    a = db.get(Asset, uid)
    if a is None or not asset_visible_in(a, workspace_id, grants):
        _not_found()
    schema = db.get(Schema, a.schema_uid)
    is_position = schema is not None and nature(db, schema) == "position"
    return {"kind": "position" if is_position else "asset", "uid": a.uid, "key": a.key, "name": a.name,
            "type": a.type, "workspace_id": a.workspace_id, "web_path": f"/assets/{a.uid}"}


@links_router.get("/resolve")
def resolve_link(path: str = Query(..., description="e.g. /asset/<uid> or https://host/ticket/SPARC-123"),
                 identity=Depends(get_identity), grants=Depends(get_grants), db: Session = Depends(get_db),
                 workspace_id: Optional[str] = Query(None)):
    """The record a universal link opens, if the caller may read it."""
    from urllib.parse import unquote, urlparse
    from app.routers.ledger import _readable_workspaces, _resolve_one
    # A label sent unencoded after /lookup/ (a web address with its ?id=…) is kept whole, not parsed as a URL.
    raw = path if path.lstrip("/").startswith("lookup/") else (urlparse(path).path if "://" in path else path)
    head, _, rest = raw.lstrip("/").partition("/")
    if head == "lookup" and rest:
        # A label value (a key, a web address on a printed code) is taken exactly as it was sent: splitting it
        # on "/" turned https:// into https:/, and the address no longer matched the label it is printed from.
        kind, ident = "lookup", unquote(rest)
    else:
        parts = [p for p in unquote(raw).split("/") if p]
        if len(parts) < 2 or parts[0] not in KINDS:
            raise HTTPException(status_code=422, detail={"error": "not an ARGUS link", "code": "invalid"})
        kind, ident = parts[0], "/".join(parts[1:])
    readable = _readable_workspaces(db, identity)
    ws = workspace_id if workspace_id in readable else (readable[0] if len(readable) == 1 else workspace_id)
    if kind in ("asset", "position"):
        a = db.get(Asset, ident)
        if a is None or not any(reachable_in(a, w) for w in readable):
            _not_found()
        return _asset_link(db, ident, a.workspace_id if a.workspace_id in readable else (ws or ""), grants, kind)
    if kind == "installation":
        from app.ledger import engine
        inst = db.get(Asset, ident)
        if inst is None or inst.type != engine.INSTALLATION or inst.workspace_id not in readable:
            _not_found()
        view = engine.installation_view(db, inst)
        return {"kind": "installation", "uid": inst.uid, "key": inst.key, "position_uid": view.get("position_uid"),
                "asset_uid": view.get("asset_uid"), "workspace_id": inst.workspace_id,
                "web_path": f"/assets/{view.get('position_uid') or inst.uid}"}
    if kind == "document":
        from app.models.document import Document
        d = db.get(Document, ident) or db.scalar(select(Document).where(Document.code == ident))
        if d is None or (d.workspace_id not in readable and not (d.is_global and d.confidentiality != "riservato")):
            _not_found()
        return {"kind": "document", "uid": d.uid, "key": d.code, "name": d.title, "workspace_id": d.workspace_id,
                "web_path": f"/documents/{d.uid}"}
    if kind == "ticket":
        from app.models.issue import Issue
        from app.services.visibility import can_see
        issue = db.get(Issue, ident)
        if issue is None:
            hit = _resolve_one(db, ident, readable)
            issue = db.get(Issue, hit.get("uid")) if hit.get("status") == "migrated" and hit.get("kind") == "ticket" else None
        if issue is None or issue.workspace_id not in readable or not can_see(issue) or issue.deleted_at is not None:
            _not_found()
        return {"kind": "ticket", "uid": issue.uid, "name": issue.title, "workspace_id": issue.workspace_id,
                "web_path": f"/tickets/{issue.uid}"}
    if kind == "review":
        from app.ledger import engine
        from app.models.ledger import Claim, Conflict
        subject = None
        c = db.get(Conflict, ident)
        if c is not None:
            subject = c.subject_uid
        else:
            claim = db.get(Claim, ident)
            subject = engine.resolve_ref(db, claim.source_ref) if claim is not None else None
        a = db.get(Asset, subject) if subject else None
        from app.services.visibility import can_see
        if a is None or a.workspace_id not in readable or not can_see(a):
            _not_found()
        return {"kind": "review", "uid": ident, "record_uid": a.uid, "workspace_id": a.workspace_id,
                "web_path": "/review"}
    # lookup: every record the value names — as a QR code, a key in any case, a former key, an alias (an old
    # Service Desk address), a label of any kind, a serial, an inventory number or an old Insight
    # identifier. A QR code is what a scan means, unless another record names the value as its former key
    # or alias (the record an old one was migrated to): then, as whenever several records carry the value,
    # they are offered to choose from. A Jira key opens the ticket it became.
    qr = _qr_holders(db, ident, readable, grants)
    successors = _alias_holders(db, ident, readable, grants)
    if len(qr) == 1 and all(a.uid == qr[0].uid for a in successors):
        a = qr[0]
        return _asset_link(db, a.uid, a.workspace_id if a.workspace_id in readable else (ws or ""), grants, "asset")
    hit = _resolve_one(db, ident, readable)
    if hit.get("status") == "migrated" and hit.get("kind") == "ticket":
        return resolve_link(f"/ticket/{hit['uid']}", identity, grants, db, workspace_id)
    holders = _merge(qr, successors, _label_holders(db, ident, readable, grants))
    if hit.get("status") == "migrated" and hit.get("kind") == "asset":
        found = db.get(Asset, hit["uid"])
        holders = _merge([found] if found is not None else [], holders)
    # Nothing carries the whole code: a piece of it (the serial inside a manufacturer's code). The answer says
    # so, for the app to offer remembering the whole code on the record, so the next scan finds it at once.
    parts: dict[str, str] = {}
    if not holders:
        holders, parts = _part_holders(db, ident, readable, grants)
    holders, via = _port_owners(db, holders, ident, readable, grants)
    if len(holders) == 1:
        a = holders[0]
        out = _asset_link(db, a.uid, a.workspace_id if a.workspace_id in readable else (ws or ""), grants, "asset")
        if a.uid in parts:
            out["matched"] = {"by": "part", "part": parts[a.uid], "code": ident}
        if a.uid in via:
            port = via[a.uid]
            out["via_port"] = {"uid": port.uid, "key": port.key, "name": port.name,
                               "mac": (port.attributes or {}).get("mac")}
        return out
    if len(holders) > 1:
        # A value held by two units (a serial, a key one has and the other had) opens neither: the person
        # chooses (A67).
        raise HTTPException(status_code=409, detail={
            "error": "This label matches more than one record. Choose the one in front of you.",
            "code": "ambiguous",
            "candidates": [{"uid": a.uid, "key": a.key, "name": a.name, "type": a.type,
                            "workspace_id": a.workspace_id,
                            "attributes": {k: (a.attributes or {}).get(k) for k in LABEL_FIELDS
                                           if (a.attributes or {}).get(k)}} for a in holders[:20]]})
    raise HTTPException(status_code=404, detail={"error": "Not found, or not visible to you.", "code": "not_found",
                                                 "archive": hit.get("archive")})


LABEL_FIELDS = ("serial", "inventory_number", "inventory", "mac", "manufacturer")


def _visible_holders(db: Session, stmt, readable: list[str], grants) -> list[Asset]:
    """Active records this person may see among those `stmt` selects; a merged record stands for its survivor."""
    from sqlalchemy import or_
    from app.ledger.identity import INACTIVE
    from app.ledger.lookup import _survivor
    from app.services.visibility import can_see
    seen, out = set(), []
    for a in db.scalars(stmt.order_by(Asset.key).limit(50)):
        a = _survivor(db, a) if a.merged_into_uid else a
        if a is None or a.uid in seen or a.deleted_at is not None or a.record_status in INACTIVE:
            continue
        if any(reachable_in(a, w) for w in readable) and can_see(a, grants):
            seen.add(a.uid)
            out.append(a)
    return out


def _qr_holders(db: Session, value: str, readable: list[str], grants) -> list[Asset]:
    """What carries this exact QR code."""
    from app.models.asset_subresources import AssetLabel
    v = value.strip()
    if not v:
        return []
    return _visible_holders(db, select(Asset).join(AssetLabel, AssetLabel.asset_uid == Asset.uid)
                            .where(AssetLabel.type == "qrcode", AssetLabel.value == v), readable, grants)


def _alias_holders(db: Session, value: str, readable: list[str], grants) -> list[Asset]:
    """What names this value as its former key, former uid or alias, ignoring case."""
    from sqlalchemy import func
    from app.ledger.lookup import ALIAS_LABELS
    from app.models.asset_subresources import AssetLabel
    v = value.strip().lower()
    if not v:
        return []
    return _visible_holders(db, select(Asset).join(AssetLabel, AssetLabel.asset_uid == Asset.uid)
                            .where(AssetLabel.type.in_(ALIAS_LABELS), func.lower(AssetLabel.value) == v),
                            readable, grants)


def _label_holders(db: Session, value: str, readable: list[str], grants) -> list[Asset]:
    """Records this person may see that carry the value, whole and ignoring case: as their key, as a label of
    any type (a QR code, a barcode, a former key, an alias, an inventory tag) or as their serial, inventory
    number or MAC. When nothing does, the value without what a nameplate prints around it ("S/N: 4711")."""
    from app.services.identifiers import exact_clause
    v = value.strip()
    if not v:
        return []
    from app.services.network_companions import normalise_mac
    found = _visible_holders(db, select(Asset).where(exact_clause(db, grants, v)), readable, grants)
    bare = _bare_label(v)
    if not found and bare != v:
        found = _visible_holders(db, select(Asset).where(exact_clause(db, grants, bare)), readable, grants)
    # A MAC in another spelling (0030.5337.8628, 003053378628) than the one recorded.
    mac = normalise_mac(bare)
    if not found and mac is not None and mac.lower() not in (v.lower(), bare.lower()):
        found = _visible_holders(db, select(Asset).where(exact_clause(db, grants, mac)), readable, grants)
    return found


def _parts(value: str) -> list[str]:
    """The pieces of a code that carries several fields — a manufacturer's DataMatrix ("P/N:… S/N:…"), a GS1
    string ("(01)…(21)…"), a web address with the serial in it (…?sn=4711) — each without what is printed
    around it: tried one by one when the whole code is no record's label."""
    from urllib.parse import parse_qsl, urlparse
    v = value.strip()
    if "://" in v:
        u = urlparse(v)
        pieces = [x for _, x in parse_qsl(u.query)] + [p for p in u.path.split("/") if p]
    else:
        pieces = re.split(r"[\s;,|\x1d\x1e]+", re.sub(r"\((\d{2,4})\)", r" (\1)", v))
    out: list[str] = []
    for p in pieces:
        b = _bare_label(re.sub(r"^\(\d{2,4}\)", "", p))
        if len(b) >= 4 and b.lower() != v.lower() and b not in out:
            out.append(b)
    return out[:16]


def _part_holders(db: Session, value: str, readable: list[str], grants) -> tuple[list[Asset], dict[str, str]]:
    """Records found by a piece of the code (_parts), and the piece each was found by."""
    found: list[Asset] = []
    by: dict[str, str] = {}
    for part in _parts(value):
        for a in _label_holders(db, part, readable, grants):
            if a.uid not in by:
                by[a.uid] = part
                found.append(a)
    return found, by


def _port_owners(db: Session, holders: list[Asset], value: str, readable: list[str],
                 grants) -> tuple[list[Asset], dict[str, Asset]]:
    """A network port found by its MAC stands for the unit it is the port of: a scanned MAC opens the unit (the
    MAC is recorded on its port, services/network_companions). Returns the records, and the port each unit was
    found through."""
    from app.models.asset import Relation
    from app.services import network_companions as nc
    mac = nc.normalise_mac(_bare_label(value))
    if mac is None:
        return holders, {}
    out: list[Asset] = []
    via: dict[str, Asset] = {}
    for a in holders:
        if a.type == nc.PORT_TYPE and nc.normalise_mac((a.attributes or {}).get("mac")) == mac:
            owner_uid = db.scalar(select(Relation.to_asset_uid).where(Relation.from_asset_uid == a.uid,
                                                                      Relation.relation_type == nc.PORT_VERB).limit(1))
            owner = _visible_holders(db, select(Asset).where(Asset.uid == owner_uid), readable, grants) if owner_uid else []
            if owner:
                via.setdefault(owner[0].uid, a)
                a = owner[0]
        out.append(a)
    return _merge(out), via


_LABEL_PREFIX = re.compile(
    r"^(?:\(21\)|\]C1|\]d2|\]Q3|(?:S\s*/\s*N|SN|SER(?:IAL)?(?:\s*(?:NO|NR|N°|NUMBER|#))?|MATR(?:ICOLA)?|P\s*/\s*N|"
    r"INV(?:ENTAR(?:Y|IO))?(?:\s*(?:NO|NR|N°|#))?|ASSET\s*TAG|MAC(?:\s*ADDR(?:ESS)?)?)\s*[.:#]?)\s*", re.I)


def _bare_label(value: str) -> str:
    """A scanned value without what is printed around it: "S/N: 4711" → "4711", a GS1 serial "(21)4711" →
    "4711"."""
    bare = _LABEL_PREFIX.sub("", value.strip(), count=1).strip()
    return bare or value.strip()


def _merge(*lists: list[Asset]) -> list[Asset]:
    seen, out = set(), []
    for rows in lists:
        for a in rows:
            if a.uid not in seen:
                seen.add(a.uid)
                out.append(a)
    return out
