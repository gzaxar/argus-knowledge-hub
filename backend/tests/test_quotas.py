"""Quotas (services/quotas.py): defaults an administrator sets and per-workspace overrides; what would add past a
quota is refused wherever it is written (records, files, members), before a model call and past an API rate; an
instance administrator signed in is never stopped; one portability import at once."""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.app_setting import AppSetting
from app.models.asset import Asset
from app.models.membership import Membership
from app.models.role import RoleBinding
from app.models.usage import QuotaAIUsage
from app.models.user import User
from app.models.workspace import Workspace
from app.services import quotas, usage

client = TestClient(app)


@pytest.fixture
def world():
    db = SessionLocal()
    t = uuid.uuid4().hex[:6]
    saved = db.get(AppSetting, quotas.SETTING)
    saved = dict(saved.value) if saved is not None else None
    ws = Workspace(id=f"q-{t}", name=f"Quota {t}")
    admin = User(id=str(uuid.uuid4()), email=f"qa-{t}@argus.test", is_admin=True)
    eve = User(id=str(uuid.uuid4()), email=f"qe-{t}@argus.test", is_admin=False)
    db.add_all([ws, admin, eve])
    db.flush()
    db.add(Membership(workspace_id=ws.id, user_id=eve.id, can_read=True, can_create=True))
    db.commit()
    for o in (admin, eve):
        db.refresh(o)
        db.expunge(o)
    out = {"db": db, "ws": ws.id, "admin": admin, "eve": eve, "t": t}
    yield out
    app.dependency_overrides.pop(get_identity, None)
    db.rollback()
    row = db.get(AppSetting, quotas.SETTING)
    if saved is None and row is not None:
        db.delete(row)
    elif saved is not None:
        row.value = saved
    db.commit()
    quotas.forget_cache()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    db.query(QuotaAIUsage).filter(QuotaAIUsage.workspace_id == ws.id).delete()
    db.delete(db.get(Workspace, ws.id))
    for u in (admin, eve):
        db.delete(db.get(User, u.id))
    db.commit()
    db.close()


def as_(user):
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=user)


def asset(ws, name="Pump"):
    from app.ledger.engine import ensure_type
    db = SessionLocal()
    try:
        uid = str(uuid.uuid4())
        db.add(Asset(uid=uid, workspace_id=ws, key=f"Q-{uid[:6]}", name=name, type="Ion Pump",
                     schema_uid=ensure_type(db, ws, "Ion Pump").uid, attributes={}))
        db.commit()
        return uid
    finally:
        db.close()


def test_the_defaults_are_built_in_set_by_an_administrator_and_overridden_per_workspace(world):
    as_(world["admin"])
    defs = {q["key"]: q for q in client.get("/v1/admin/quotas").json()["quotas"]}
    assert defs["storage_bytes"]["builtin"] == 50 * 2 ** 30 and defs["file_bytes"]["builtin"] == 2 * 2 ** 30
    assert all(defs[k]["builtin"] is None for k in ("ai_tokens_5h", "ai_tokens_week", "assets", "documents",
                                                     "members", "api_ops_day", "api_ops_minute"))
    r = client.put("/v1/admin/quotas/defaults", json={"values": {"assets": 1000, "storage_bytes": None}})
    assert r.status_code == 200
    defs = {q["key"]: q for q in r.json()["quotas"]}
    assert defs["assets"]["default"] == 1000 and defs["storage_bytes"]["default"] is None   # unlimited
    r = client.put(f"/v1/admin/quotas/workspaces/{world['ws']}", json={"values": {"assets": 5}})
    rows = {q["key"]: q for q in r.json()["quotas"]}
    assert rows["assets"]["limit"] == 5 and rows["assets"]["source"] == "workspace"
    assert rows["storage_bytes"]["limit"] is None and rows["storage_bytes"]["source"] == "default"
    r = client.put(f"/v1/admin/quotas/workspaces/{world['ws']}", json={"reset": ["assets"]})
    assert {q["key"]: q for q in r.json()["quotas"]}["assets"]["limit"] == 1000
    client.put("/v1/admin/quotas/defaults", json={"reset": ["assets", "storage_bytes"]})
    assert {q["key"]: q for q in client.get("/v1/admin/quotas").json()["quotas"]}["storage_bytes"]["default"] == 50 * 2 ** 30
    assert client.put("/v1/admin/quotas/defaults", json={"values": {"assets": -1}}).status_code == 422
    assert client.put("/v1/admin/quotas/defaults", json={"values": {"nothing": 1}}).status_code == 422
    as_(world["eve"])
    assert client.get("/v1/admin/quotas").status_code == 403
    assert client.put("/v1/admin/quotas/defaults", json={"values": {"assets": 1}}).status_code == 403


def test_a_new_record_past_the_quota_is_refused_wherever_it_is_written_and_editing_still_works(world):
    db = world["db"]
    quotas.set_workspace(db, world["ws"], {"assets": 2})
    db.commit()
    first, _second = asset(world["ws"]), asset(world["ws"])
    with pytest.raises(quotas.QuotaExceeded) as e:
        asset(world["ws"])
    assert e.value.key == "assets" and (e.value.limit, e.value.used, e.value.adding) == (2, 2, 1)
    s = SessionLocal()
    s.get(Asset, first).name = "Renamed"                   # editing adds nothing
    s.commit()
    s.get(Asset, first).deleted_at = datetime.now(timezone.utc)
    s.commit()
    s.close()
    asset(world["ws"])                                     # a deleted record makes room


def test_an_instance_administrator_signed_in_is_never_stopped(world):
    db = world["db"]
    quotas.set_workspace(db, world["ws"], {"assets": 0})
    db.commit()
    with pytest.raises(quotas.QuotaExceeded):
        asset(world["ws"])
    usage.begin({}, "/v1/assets")
    quotas.note_admin(True)
    try:
        asset(world["ws"])
    finally:
        usage._request.set(None)


def test_a_file_too_big_or_past_the_room_is_refused_before_it_is_sent(world):
    db = world["db"]
    quotas.set_workspace(db, world["ws"], {"file_bytes": 1000, "storage_bytes": 100_000})
    db.commit()
    as_(world["eve"])
    body = {"filename": "big.pdf", "content_type": "application/pdf", "sha256": hashlib.sha256(b"x").hexdigest()}
    r = client.post("/v1/uploads", json={**body, "size": 5000}, headers={"X-Workspace-Id": world["ws"]})
    assert r.status_code == 429 and r.json()["detail"]["quota"] == "file_bytes"
    quotas.set_workspace(db, world["ws"], {"file_bytes": None, "storage_bytes": 1000})
    db.commit()
    r = client.post("/v1/uploads", json={**body, "size": 5000}, headers={"X-Workspace-Id": world["ws"]})
    assert r.status_code == 429 and r.json()["detail"]["quota"] == "storage_bytes"
    assert "Administration → Quotas" in r.json()["detail"]["error"]
    quotas.set_workspace(db, world["ws"], {}, reset=("file_bytes", "storage_bytes"))
    db.commit()
    r = client.post("/v1/uploads", json={**body, "size": 5000}, headers={"X-Workspace-Id": world["ws"]})
    assert r.status_code == 201


def test_a_member_past_the_quota_is_refused_and_one_already_there_is_not_counted_again(world):
    db = world["db"]
    quotas.set_workspace(db, world["ws"], {"members": 1})       # eve is the one
    db.commit()
    s = SessionLocal()
    s.add(RoleBinding(workspace_id=world["ws"], subject_type="user", subject_id=world["eve"].id, role_id="viewer",
                      created_at=datetime.now(timezone.utc)))
    s.commit()                                                     # eve again: no one new
    s.add(RoleBinding(workspace_id=world["ws"], subject_type="user", subject_id=world["admin"].id, role_id="viewer",
                      created_at=datetime.now(timezone.utc)))
    with pytest.raises(quotas.QuotaExceeded) as e:
        s.commit()
    assert e.value.key == "members"
    s.rollback()
    s.query(RoleBinding).filter(RoleBinding.workspace_id == world["ws"]).delete()
    s.commit()
    s.close()


def test_the_ai_quota_is_checked_before_a_call_over_a_rolling_window(world):
    db = world["db"]
    hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    db.add_all([QuotaAIUsage(hour=hour - timedelta(hours=2), workspace_id=world["ws"], tokens=600),
                QuotaAIUsage(hour=hour - timedelta(hours=30), workspace_id=world["ws"], tokens=5000)])
    quotas.set_workspace(db, world["ws"], {"ai_tokens_5h": 1000, "ai_tokens_week": 10_000})
    db.commit()
    quotas.check_ai(db, world["ws"])                               # 600 of 1000 in 5 h, 5600 of 10000 in a week
    quotas.note_tokens(world["ws"], 500)
    with pytest.raises(quotas.QuotaExceeded) as e:
        quotas.check_ai(db, world["ws"])
    assert e.value.key == "ai_tokens_5h" and e.value.used == 1100
    assert e.value.frees_at == hour - timedelta(hours=2) + timedelta(hours=5)
    rows = {r["key"]: r for r in quotas.status(db, world["ws"])}
    assert rows["ai_tokens_5h"]["level"] == "over" and rows["ai_tokens_week"]["level"] == "ok"

    from app.services import llm
    usage.begin({"x-workspace-id": world["ws"]}, "/v1/ask")
    try:
        with pytest.raises(llm.LLMQuotaExceeded):
            llm._post("chat", "m", "http://127.0.0.1:9/never")    # refused before anything is sent
    finally:
        usage._request.set(None)


def test_api_operations_past_the_rate_are_refused_with_when_to_try_again(world):
    db = world["db"]
    quotas.set_workspace(db, world["ws"], {"api_ops_minute": 2})
    db.commit()
    quotas.forget_cache()
    headers = {"X-Workspace-Id": world["ws"], "User-Agent": "robot/1.0"}
    as_(world["eve"])
    codes = [client.get("/v1/assets", headers=headers).status_code for _ in range(3)]
    assert codes[:2] != [429, 429] and codes[2] == 429
    r = client.get("/v1/assets", headers=headers)
    assert r.json()["detail"]["quota"] == "api_ops_minute" and int(r.headers["Retry-After"]) <= 60
    assert client.get("/v1/assets", headers={**headers, "User-Agent": "Mozilla/5.0"}).status_code != 429   # the web app


def test_one_portability_import_at_once(world, monkeypatch):
    from app.portability import service
    db = world["db"]
    quotas.set_defaults(db, {"imports_at_once": 0})
    db.commit()
    with pytest.raises(service.ServiceError) as e:
        service.create_import(db, "a@argus.test", mode="clone", source={"upload": True}, decisions={},
                              cfg=service.config())
    assert e.value.code == "quota_exceeded" and e.value.status == 429
    db.rollback()


def test_a_workspace_sees_its_quotas_warning_at_80_percent(world):
    db = world["db"]
    quotas.set_workspace(db, world["ws"], {"assets": 5})
    db.commit()
    for _ in range(4):
        asset(world["ws"])
    as_(world["admin"])
    rows = {q["key"]: q for q in client.get(f"/v1/workspaces/{world['ws']}/quotas").json()["quotas"]}
    assert rows["assets"]["used"] == 4 and rows["assets"]["level"] == "warn"
    listing = {w["id"]: w for w in client.get("/v1/admin/quotas").json()["workspaces"]}
    assert listing[world["ws"]]["level"] == "warn"
