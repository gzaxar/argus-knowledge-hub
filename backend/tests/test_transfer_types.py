"""A record's type across workspaces: a transfer gives a record the target's type of the same name when its own
is private to its workspace, and refuses one the target has none for; an edit gives a record moved before this
(a type the workspace cannot use) one of the workspace's — and changes no other type."""
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.asset import Asset
from app.models.asset_subresources import AssetHistory
from app.models.schema import Schema
from app.models.transfer_job import TransferJob
from app.models.user import User
from app.models.workspace import Workspace
from app.services import asset_types, indoor_transfer, workspace_transfer


@pytest.fixture()
def w():
    t = secrets.token_hex(3)
    src, dst = f"tsrc-{t}", f"tdst-{t}"
    db = SessionLocal()
    for ws in (src, dst):
        db.add(Workspace(id=ws, name=ws))
    db.flush()
    for ws in (src, dst):
        asset_types.ensure_asset_types(db, ws)          # each its own (private) copy of the types
    odd = Schema(uid=f"{src}:odd", workspace_id=src, name="Odd Thing", applies_to="objects", attributes=[])
    db.add(odd)
    admin = User(id=str(uuid.uuid4()), email=f"admin-{t}@argus.test", is_admin=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
    yield {"db": db, "src": src, "dst": dst, "admin": admin}
    app.dependency_overrides.pop(get_identity, None)
    db.rollback()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    for ws in (src, dst):
        db.delete(db.get(Workspace, ws))
    db.delete(db.get(User, admin.id))
    db.commit()
    db.close()


def make(db, ws, schema_uid, type_name, name) -> Asset:
    a = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=schema_uid, key=f"K-{uuid.uuid4().hex[:8]}",
              name=name, type=type_name, attributes={})
    db.add(a)
    db.commit()
    return a


def test_a_moved_record_takes_the_targets_type_of_the_same_name(w):
    db, src, dst = w["db"], w["src"], w["dst"]
    hall = make(db, src, asset_types.type_uid(src, "Area"), "Area", "Edificio 6a")
    report = indoor_transfer.preview(db, src, dst, "move", {hall.uid})
    assert report["records"][0]["type_after"] == {"keeps": False, "becomes": "Area"} and report["clean"]
    job = TransferJob(uid=str(uuid.uuid4()), workspace_id=src, target_workspace_id=dst, mode="move")
    db.add(job)
    db.commit()
    workspace_transfer.run_transfer(job.uid, src, dst, "move", [], False, [hall.uid], [], [])
    db.expire_all()
    assert db.get(TransferJob, job.uid).status == "succeeded", db.get(TransferJob, job.uid).error
    moved = db.get(Asset, hall.uid)
    assert moved.workspace_id == dst and moved.schema_uid == asset_types.type_uid(dst, "Area") and moved.type == "Area"


def test_a_record_the_target_has_no_type_for_is_refused_before_anything_moves(w):
    db, src, dst = w["db"], w["src"], w["dst"]
    odd = make(db, src, f"{src}:odd", "Odd Thing", "Something odd")
    report = indoor_transfer.preview(db, src, dst, "move", {odd.uid})
    assert not report["clean"] and any("Odd Thing" in p and "move or copy the type too" in p for p in report["problems"])
    r = TestClient(app).post("/v1/transfers", headers={"X-Workspace-Id": src}, json={
        "target_workspace_id": dst, "mode": "move", "type_uids": [], "include_instances": False,
        "asset_uids": [odd.uid], "document_uids": [], "issue_uids": []})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "transfer_type"
    db.expire_all()
    assert db.get(Asset, odd.uid).workspace_id == src


def test_an_edit_gives_a_stray_record_a_usable_type_and_changes_no_other(w):
    db, src, dst = w["db"], w["src"], w["dst"]
    # Moved before this release: in dst, still of src's private type.
    stray = make(db, dst, asset_types.type_uid(src, "Area"), "Area", "Edificio 6b")
    client, h = TestClient(app), {"X-Workspace-Id": dst}
    body = {"name": "Edificio 6b", "attributes": {}, "schema_uid": asset_types.type_uid(dst, "Area")}
    r = client.put(f"/v1/assets/{stray.uid}", headers=h, json=body)
    assert r.status_code == 200, r.text
    db.expire_all()
    fixed = db.get(Asset, stray.uid)
    assert fixed.schema_uid == asset_types.type_uid(dst, "Area") and fixed.type == "Area"
    assert any(x.type == "type_changed" for x in db.scalars(select(AssetHistory).where(AssetHistory.asset_uid == stray.uid)))
    # Its type is usable now: changing it again is a type migration's job.
    again = client.put(f"/v1/assets/{stray.uid}", headers=h,
                       json={**body, "schema_uid": asset_types.type_uid(dst, "Building")})
    assert again.status_code == 422 and again.json()["detail"]["code"] == "type_change"
    # A type the workspace cannot use is refused too.
    other = make(db, dst, asset_types.type_uid(src, "Area"), "Area", "Edificio 6c")
    bad = client.put(f"/v1/assets/{other.uid}", headers=h, json={**body, "schema_uid": f"{src}:odd"})
    assert bad.status_code == 422
