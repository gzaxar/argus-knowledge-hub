"""Copying/moving types and objects between workspaces.

Two layers: the transfer service itself (workspace reassignment, relation
drop/remap policy, key/code regeneration on copy), and the /v1/transfers
API (the two-workspace permission check, PAT rejection).
"""
import secrets

import pytest
from fastapi.testclient import TestClient

from app.auth import OidcIdentity, PatIdentity, get_identity
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models.asset import Asset, Relation
from app.models.attachment import Attachment
from app.models.icon import Icon
from app.models.membership import Membership
from app.models.schema import Schema
from app.models.transfer_job import TransferJob
from app.models.user import User
from app.models.workspace import Workspace
from app.services.workspace_transfer import run_transfer

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield


def _workspaces(db, suffix):
    source, target = f"src-{suffix}", f"dst-{suffix}"
    db.add(Workspace(id=source, name="Source"))
    db.add(Workspace(id=target, name="Target"))
    db.flush()
    return source, target


def _two_linked_assets(db, source, suffix, target_type=True):
    """schema + two assets in `source`, related to each other (and, unless told otherwise, a Camera type of the
    target's own for them to take there)."""
    schema_uid = f"sch-{suffix}"
    db.add(Schema(uid=schema_uid, workspace_id=source, name="Camera"))
    # The target has a Camera of its own: a record moved or copied there takes it (its source's is private).
    if target_type:
        db.add(Schema(uid=f"{schema_uid}-dst", workspace_id=source.replace("src-", "dst-", 1), name="Camera"))
    db.flush()
    a_uid, b_uid = f"a-{suffix}", f"b-{suffix}"
    db.add(Asset(uid=a_uid, workspace_id=source, schema_uid=schema_uid, key=f"KEY-A-{suffix}", name="A", type="Camera"))
    db.add(Asset(uid=b_uid, workspace_id=source, schema_uid=schema_uid, key=f"KEY-B-{suffix}", name="B", type="Camera"))
    db.flush()
    db.add(Relation(workspace_id=source, from_asset_uid=a_uid, to_asset_uid=b_uid, relation_type="related_to"))
    db.commit()
    return schema_uid, a_uid, b_uid


# --------------------------------------------------------------------------
# Move
# --------------------------------------------------------------------------

def test_move_asset_reassigns_workspace_and_drops_cross_boundary_relation():
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    source, target = _workspaces(db, suffix)
    schema_uid, a_uid, b_uid = _two_linked_assets(db, source, suffix)

    job_uid = f"job-{suffix}"
    db.add(TransferJob(uid=job_uid, workspace_id=source, target_workspace_id=target, mode="move"))
    db.commit()
    db.close()

    # Only A moves; the relation to B (left behind) must be dropped, not
    # silently kept pointing across the boundary.
    run_transfer(job_uid, source, target, "move", [], False, [a_uid], [], [])

    db = SessionLocal()
    moved = db.get(Asset, a_uid)
    left_behind = db.get(Asset, b_uid)
    assert moved.workspace_id == target
    assert left_behind.workspace_id == source
    assert db.query(Relation).filter(Relation.from_asset_uid == a_uid).count() == 0
    assert moved.outbound_relations == []
    assert left_behind.inbound_relations == []

    refreshed = db.get(TransferJob, job_uid)
    assert refreshed.status == "succeeded"
    assert refreshed.counts["assets"] == 1
    assert refreshed.counts["relations_dropped"] == 1
    db.close()


def test_move_keeps_relation_when_both_endpoints_move_together():
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    source, target = _workspaces(db, suffix)
    schema_uid, a_uid, b_uid = _two_linked_assets(db, source, suffix)
    job_uid = f"job-{suffix}"
    db.add(TransferJob(uid=job_uid, workspace_id=source, target_workspace_id=target, mode="move"))
    db.commit()
    db.close()

    run_transfer(job_uid, source, target, "move", [], False, [a_uid, b_uid], [], [])

    db = SessionLocal()
    assert db.get(Asset, a_uid).workspace_id == target
    assert db.get(Asset, b_uid).workspace_id == target
    relation = db.query(Relation).filter(Relation.from_asset_uid == a_uid).one()
    assert relation.to_asset_uid == b_uid
    assert relation.workspace_id == target
    assert db.get(Asset, a_uid).outbound_relations == [b_uid]
    assert db.get(Asset, b_uid).inbound_relations == [a_uid]

    refreshed = db.get(TransferJob, job_uid)
    assert refreshed.counts["relations_dropped"] == 0
    db.close()


def test_move_type_with_instances_pulls_in_ancestor_and_moves_its_assets():
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    source, target = _workspaces(db, suffix)
    base_uid, child_uid = f"base-{suffix}", f"child-{suffix}"
    db.add(Schema(uid=base_uid, workspace_id=source, name="Equipment"))
    db.flush()
    db.add(Schema(uid=child_uid, workspace_id=source, name="Camera", parent_schema_uid=base_uid))
    db.flush()
    asset_uid = f"a-{suffix}"
    db.add(Asset(uid=asset_uid, workspace_id=source, schema_uid=child_uid, key=f"KEY-{suffix}", name="Cam", type="Camera"))
    db.commit()

    job_uid = f"job-{suffix}"
    db.add(TransferJob(uid=job_uid, workspace_id=source, target_workspace_id=target, mode="move"))
    db.commit()
    db.close()

    run_transfer(job_uid, source, target, "move", [child_uid], True, [], [], [])

    db = SessionLocal()
    assert db.get(Schema, child_uid).workspace_id == target
    assert db.get(Schema, base_uid).workspace_id == target
    assert db.get(Asset, asset_uid).workspace_id == target
    refreshed = db.get(TransferJob, job_uid)
    assert refreshed.counts["types"] == 2
    assert refreshed.counts["assets"] == 1
    db.close()


def test_move_base_type_leaves_children_behind_unless_asked():
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    source, target = _workspaces(db, suffix)
    base_uid, child_uid, grandchild_uid = f"base-{suffix}", f"child-{suffix}", f"grand-{suffix}"
    db.add(Schema(uid=base_uid, workspace_id=source, name="Equipment"))
    db.flush()
    db.add(Schema(uid=child_uid, workspace_id=source, name="Camera", parent_schema_uid=base_uid))
    db.flush()
    db.add(Schema(uid=grandchild_uid, workspace_id=source, name="PTZ Camera", parent_schema_uid=child_uid))
    db.flush()
    child_asset_uid = f"a-{suffix}"
    db.add(Asset(uid=child_asset_uid, workspace_id=source, schema_uid=child_uid, key=f"KEY-{suffix}", name="Cam", type="Camera"))
    db.commit()

    job_uid = f"job-{suffix}"
    db.add(TransferJob(uid=job_uid, workspace_id=source, target_workspace_id=target, mode="move"))
    db.commit()
    db.close()

    # Moving the base type without include_descendant_types must not touch
    # its children at all — only the base type itself moves.
    run_transfer(job_uid, source, target, "move", [base_uid], True, [], [], [], False)

    db = SessionLocal()
    assert db.get(Schema, base_uid).workspace_id == target
    assert db.get(Schema, child_uid).workspace_id == source
    assert db.get(Schema, grandchild_uid).workspace_id == source
    assert db.get(Asset, child_asset_uid).workspace_id == source
    refreshed = db.get(TransferJob, job_uid)
    assert refreshed.counts["types"] == 1
    assert refreshed.counts["assets"] == 0
    db.close()


def test_move_base_type_with_descendants_pulls_in_whole_tree_and_instances():
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    source, target = _workspaces(db, suffix)
    base_uid, child_uid, grandchild_uid = f"base-{suffix}", f"child-{suffix}", f"grand-{suffix}"
    db.add(Schema(uid=base_uid, workspace_id=source, name="Equipment"))
    db.flush()
    db.add(Schema(uid=child_uid, workspace_id=source, name="Camera", parent_schema_uid=base_uid))
    db.flush()
    db.add(Schema(uid=grandchild_uid, workspace_id=source, name="PTZ Camera", parent_schema_uid=child_uid))
    db.flush()
    child_asset_uid, grandchild_asset_uid = f"a-{suffix}", f"b-{suffix}"
    db.add(Asset(uid=child_asset_uid, workspace_id=source, schema_uid=child_uid, key=f"KEY-A-{suffix}", name="Cam", type="Camera"))
    db.add(Asset(uid=grandchild_asset_uid, workspace_id=source, schema_uid=grandchild_uid, key=f"KEY-B-{suffix}", name="PTZ", type="PTZ Camera"))
    db.commit()

    job_uid = f"job-{suffix}"
    db.add(TransferJob(uid=job_uid, workspace_id=source, target_workspace_id=target, mode="move"))
    db.commit()
    db.close()

    run_transfer(job_uid, source, target, "move", [base_uid], True, [], [], [], True)

    db = SessionLocal()
    assert db.get(Schema, base_uid).workspace_id == target
    assert db.get(Schema, child_uid).workspace_id == target
    assert db.get(Schema, grandchild_uid).workspace_id == target
    assert db.get(Asset, child_asset_uid).workspace_id == target
    assert db.get(Asset, grandchild_asset_uid).workspace_id == target
    refreshed = db.get(TransferJob, job_uid)
    assert refreshed.counts["types"] == 3
    assert refreshed.counts["assets"] == 2
    db.close()


# --------------------------------------------------------------------------
# Copy
# --------------------------------------------------------------------------

def test_copy_asset_gets_new_identity_and_remaps_only_co_copied_relation():
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    source, target = _workspaces(db, suffix)
    schema_uid, a_uid, b_uid = _two_linked_assets(db, source, suffix)
    job_uid = f"job-{suffix}"
    db.add(TransferJob(uid=job_uid, workspace_id=source, target_workspace_id=target, mode="copy"))
    db.commit()
    db.close()

    # Only A is copied — the relation to B (not copied) must be dropped.
    run_transfer(job_uid, source, target, "copy", [], False, [a_uid], [], [])

    db = SessionLocal()
    assert db.get(Asset, a_uid).workspace_id == source  # original untouched
    copies = db.query(Asset).filter(Asset.workspace_id == target).all()
    assert len(copies) == 1
    copy = copies[0]
    assert copy.uid != a_uid
    assert copy.key != db.get(Asset, a_uid).key
    assert copy.key.startswith(db.get(Asset, a_uid).key)
    assert db.query(Relation).filter(Relation.from_asset_uid == copy.uid).count() == 0

    refreshed = db.get(TransferJob, job_uid)
    assert refreshed.counts["assets"] == 1
    assert refreshed.counts["relations_dropped"] == 1
    db.close()


def test_copy_remaps_relation_between_two_co_copied_assets():
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    source, target = _workspaces(db, suffix)
    schema_uid, a_uid, b_uid = _two_linked_assets(db, source, suffix)
    job_uid = f"job-{suffix}"
    db.add(TransferJob(uid=job_uid, workspace_id=source, target_workspace_id=target, mode="copy"))
    db.commit()
    db.close()

    run_transfer(job_uid, source, target, "copy", [], False, [a_uid, b_uid], [], [])

    db = SessionLocal()
    copies = {a.key.rsplit("-copy", 1)[0]: a for a in db.query(Asset).filter(Asset.workspace_id == target)}
    original_a_key = db.get(Asset, a_uid).key
    original_b_key = db.get(Asset, b_uid).key
    copy_a = copies[original_a_key]
    copy_b = copies[original_b_key]
    relation = db.query(Relation).filter(Relation.from_asset_uid == copy_a.uid).one()
    assert relation.to_asset_uid == copy_b.uid
    assert copy_a.outbound_relations == [copy_b.uid]
    assert copy_b.inbound_relations == [copy_a.uid]

    refreshed = db.get(TransferJob, job_uid)
    assert refreshed.counts["relations_copied"] == 1
    assert refreshed.counts["relations_dropped"] == 0
    db.close()


def test_copy_type_only_does_not_copy_instances():
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    source, target = _workspaces(db, suffix)
    schema_uid, a_uid, b_uid = _two_linked_assets(db, source, suffix, target_type=False)
    job_uid = f"job-{suffix}"
    db.add(TransferJob(uid=job_uid, workspace_id=source, target_workspace_id=target, mode="copy"))
    db.commit()
    db.close()

    run_transfer(job_uid, source, target, "copy", [schema_uid], False, [], [], [])

    db = SessionLocal()
    copied_schemas = db.query(Schema).filter(Schema.workspace_id == target).all()
    assert len(copied_schemas) == 1
    assert copied_schemas[0].uid != schema_uid
    assert db.query(Asset).filter(Asset.workspace_id == target).count() == 0
    refreshed = db.get(TransferJob, job_uid)
    assert refreshed.counts["types"] == 1
    assert refreshed.counts["assets"] == 0
    db.close()


def test_copy_reassigns_the_avatar_to_the_new_attachment():
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    source, target = _workspaces(db, suffix)
    schema_uid, a_uid, _b_uid = _two_linked_assets(db, source, suffix)
    att_uid = f"att-{suffix}"
    db.add(Attachment(
        uid=att_uid, workspace_id=source, asset_uid=a_uid, filename="pic.png",
        mime_type="image/png", storage_path=f"/tmp/{att_uid}",
    ))
    db.flush()
    db.get(Asset, a_uid).avatar_icon_uid = att_uid
    db.commit()
    job_uid = f"job-{suffix}"
    db.add(TransferJob(uid=job_uid, workspace_id=source, target_workspace_id=target, mode="copy"))
    db.commit()
    db.close()

    run_transfer(job_uid, source, target, "copy", [], False, [a_uid], [], [])

    db = SessionLocal()
    copy = db.query(Asset).filter(Asset.workspace_id == target).one()
    assert copy.avatar_icon_uid is not None
    assert copy.avatar_icon_uid != att_uid
    copied_attachment = db.get(Attachment, copy.avatar_icon_uid)
    assert copied_attachment is not None
    assert copied_attachment.asset_uid == copy.uid
    db.close()


def test_copy_keeps_a_global_icon_but_drops_a_private_one():
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    source, target = _workspaces(db, suffix)
    global_icon_uid, private_icon_uid = f"gi-{suffix}", f"pi-{suffix}"
    db.add(Icon(uid=global_icon_uid, workspace_id=source, name="Global", filename="g.png", storage_path="/tmp/g", is_global=True))
    db.add(Icon(uid=private_icon_uid, workspace_id=source, name="Private", filename="p.png", storage_path="/tmp/p", is_global=False))
    db.flush()
    global_type, private_type = f"gt-{suffix}", f"pt-{suffix}"
    db.add(Schema(uid=global_type, workspace_id=source, name="Global type", icon_uid=global_icon_uid))
    db.add(Schema(uid=private_type, workspace_id=source, name="Private type", icon_uid=private_icon_uid))
    db.commit()
    job_uid = f"job-{suffix}"
    db.add(TransferJob(uid=job_uid, workspace_id=source, target_workspace_id=target, mode="copy"))
    db.commit()
    db.close()

    run_transfer(job_uid, source, target, "copy", [global_type, private_type], False, [], [], [])

    db = SessionLocal()
    copies = {s.name: s for s in db.query(Schema).filter(Schema.workspace_id == target)}
    assert copies["Global type"].icon_uid == global_icon_uid
    assert copies["Private type"].icon_uid is None
    refreshed = db.get(TransferJob, job_uid)
    assert refreshed.counts["icons_dropped"] == 1
    db.close()


def test_move_schema_icon_follows_when_exclusive_but_drops_when_shared():
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    source, target = _workspaces(db, suffix)
    icon_uid = f"icon-{suffix}"
    db.add(Icon(uid=icon_uid, workspace_id=source, name="Shared", filename="s.png", storage_path="/tmp/s", is_global=False))
    db.flush()
    moving_uid, staying_uid = f"mv-{suffix}", f"st-{suffix}"
    db.add(Schema(uid=moving_uid, workspace_id=source, name="Moving", icon_uid=icon_uid))
    db.add(Schema(uid=staying_uid, workspace_id=source, name="Staying", icon_uid=icon_uid))
    db.commit()
    job_uid = f"job-{suffix}"
    db.add(TransferJob(uid=job_uid, workspace_id=source, target_workspace_id=target, mode="move"))
    db.commit()
    db.close()

    # The icon is also used by a type that isn't moving — it must stay
    # behind, and the moved type loses the reference rather than keep a
    # cross-workspace pointer.
    run_transfer(job_uid, source, target, "move", [moving_uid], False, [], [], [])

    db = SessionLocal()
    assert db.get(Schema, moving_uid).icon_uid is None
    assert db.get(Schema, staying_uid).icon_uid == icon_uid
    assert db.get(Icon, icon_uid).workspace_id == source
    refreshed = db.get(TransferJob, job_uid)
    assert refreshed.counts["icons_dropped"] == 1
    db.close()


def test_move_schema_icon_follows_both_types_when_moved_together():
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    source, target = _workspaces(db, suffix)
    icon_uid = f"icon-{suffix}"
    db.add(Icon(uid=icon_uid, workspace_id=source, name="Shared", filename="s.png", storage_path="/tmp/s", is_global=False))
    db.flush()
    a_uid, b_uid = f"a-{suffix}", f"b-{suffix}"
    db.add(Schema(uid=a_uid, workspace_id=source, name="A", icon_uid=icon_uid))
    db.add(Schema(uid=b_uid, workspace_id=source, name="B", icon_uid=icon_uid))
    db.commit()
    job_uid = f"job-{suffix}"
    db.add(TransferJob(uid=job_uid, workspace_id=source, target_workspace_id=target, mode="move"))
    db.commit()
    db.close()

    run_transfer(job_uid, source, target, "move", [a_uid, b_uid], False, [], [], [])

    db = SessionLocal()
    assert db.get(Schema, a_uid).icon_uid == icon_uid
    assert db.get(Schema, b_uid).icon_uid == icon_uid
    assert db.get(Icon, icon_uid).workspace_id == target
    refreshed = db.get(TransferJob, job_uid)
    assert refreshed.counts["icons_dropped"] == 0
    db.close()


# --------------------------------------------------------------------------
# Name conflicts
# --------------------------------------------------------------------------

def test_copy_blocks_on_type_name_conflict_without_force():
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    source, target = _workspaces(db, suffix)
    source_uid, target_uid = f"src-widget-{suffix}", f"dst-widget-{suffix}"
    db.add(Schema(uid=source_uid, workspace_id=source, name="Widget"))
    db.add(Schema(uid=target_uid, workspace_id=target, name="Widget"))
    db.commit()
    job_uid = f"job-{suffix}"
    db.add(TransferJob(uid=job_uid, workspace_id=source, target_workspace_id=target, mode="copy"))
    db.commit()
    db.close()

    run_transfer(job_uid, source, target, "copy", [source_uid], False, [], [], [])

    db = SessionLocal()
    refreshed = db.get(TransferJob, job_uid)
    assert refreshed.status == "failed"
    assert "Widget" in refreshed.error
    assert db.query(Schema).filter(Schema.workspace_id == target, Schema.name == "Widget").count() == 1
    db.close()


def test_copy_with_force_re_copy_merges_into_the_earlier_copy():
    """The real scenario this guards: someone copies a type+object, the
    source changes, and they re-run the copy with Force to sync it — that
    must update the one earlier copy in place, not add a second one. (A
    plain re-copy can't match by Asset.key: it's unique across the whole
    install, so a copy can never share its source's own key — matching
    goes through a provenance stamp set on the first copy instead.)"""
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    source, target = _workspaces(db, suffix)
    source_type = f"src-widget-{suffix}"
    db.add(Schema(uid=source_type, workspace_id=source, name="Widget", description="v1"))
    db.flush()
    source_asset = f"src-a-{suffix}"
    db.add(Asset(
        uid=source_asset, workspace_id=source, schema_uid=source_type, key=f"KEY-{suffix}",
        name="Name v1", type="Widget", attributes={"x": 1},
    ))
    db.commit()
    job1 = f"job1-{suffix}"
    db.add(TransferJob(uid=job1, workspace_id=source, target_workspace_id=target, mode="copy"))
    db.commit()
    db.close()

    run_transfer(job1, source, target, "copy", [source_type], False, [source_asset], [], [])

    db = SessionLocal()
    first_schema = db.query(Schema).filter(Schema.workspace_id == target, Schema.name == "Widget").one()
    first_asset = db.query(Asset).filter(Asset.workspace_id == target).one()
    assert first_asset.key != f"KEY-{suffix}"  # minted a fresh key, as usual
    first_schema_uid, first_asset_uid = first_schema.uid, first_asset.uid

    # The source changes, then gets re-copied with Force.
    db.get(Schema, source_type).description = "v2"
    source_asset_row = db.get(Asset, source_asset)
    source_asset_row.name = "Name v2"
    source_asset_row.attributes = {"x": 2}
    db.commit()
    job2 = f"job2-{suffix}"
    db.add(TransferJob(uid=job2, workspace_id=source, target_workspace_id=target, mode="copy"))
    db.commit()
    db.close()

    run_transfer(job2, source, target, "copy", [source_type], False, [source_asset], [], [], False, True)

    db = SessionLocal()
    schemas = db.query(Schema).filter(Schema.workspace_id == target, Schema.name == "Widget").all()
    assert len(schemas) == 1
    assert schemas[0].uid == first_schema_uid
    assert schemas[0].description == "v2"

    assets = db.query(Asset).filter(Asset.workspace_id == target).all()
    assert len(assets) == 1
    assert assets[0].uid == first_asset_uid
    assert assets[0].name == "Name v2"
    assert assets[0].attributes.get("x") == 2

    refreshed = db.get(TransferJob, job2)
    assert refreshed.status == "succeeded"
    assert refreshed.counts["types_overridden"] == 1
    assert refreshed.counts["assets_overridden"] == 1
    assert refreshed.counts["types"] == 0
    assert refreshed.counts["assets"] == 0
    db.close()


def test_move_blocks_on_type_name_conflict_even_with_force():
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    source, target = _workspaces(db, suffix)
    source_uid, target_uid = f"src-widget-{suffix}", f"dst-widget-{suffix}"
    db.add(Schema(uid=source_uid, workspace_id=source, name="Widget"))
    db.add(Schema(uid=target_uid, workspace_id=target, name="Widget"))
    db.commit()
    job_uid = f"job-{suffix}"
    db.add(TransferJob(uid=job_uid, workspace_id=source, target_workspace_id=target, mode="move"))
    db.commit()
    db.close()

    # Move has no merge path — force is ignored for it.
    run_transfer(job_uid, source, target, "move", [source_uid], False, [], [], [], False, True)

    db = SessionLocal()
    refreshed = db.get(TransferJob, job_uid)
    assert refreshed.status == "failed"
    assert db.get(Schema, source_uid).workspace_id == source
    db.close()


# --------------------------------------------------------------------------
# API: permissions
# --------------------------------------------------------------------------

def as_identity(identity):
    app.dependency_overrides[get_identity] = lambda: identity


@pytest.fixture()
def api_world():
    suffix = secrets.token_hex(4)
    db = SessionLocal()
    source, target = _workspaces(db, suffix)
    schema_uid, a_uid, _b_uid = _two_linked_assets(db, source, suffix)
    user_id = f"u-{suffix}"
    db.add(User(id=user_id, email=f"{user_id}@test.invalid"))
    db.commit()
    db.close()
    yield {"source": source, "target": target, "asset_uid": a_uid, "user_id": user_id}
    app.dependency_overrides.pop(get_identity, None)


def test_pat_identity_cannot_transfer(api_world):
    as_identity(PatIdentity(workspace_id=api_world["source"]))
    resp = client.post(
        "/v1/transfers",
        json={"target_workspace_id": api_world["target"], "mode": "copy", "asset_uids": [api_world["asset_uid"]]},
        headers={"X-Workspace-Id": api_world["source"]},
    )
    assert resp.status_code == 403


def test_transfer_requires_create_permission_on_target(api_world):
    # Read on the source, nothing at all on the target.
    setup_db = SessionLocal()
    setup_db.add(Membership(workspace_id=api_world["source"], user_id=api_world["user_id"], can_read=True))
    setup_db.commit()
    setup_db.close()

    db = SessionLocal()
    user = db.get(User, api_world["user_id"])
    as_identity(OidcIdentity(user=user))

    resp = client.post(
        "/v1/transfers",
        json={"target_workspace_id": api_world["target"], "mode": "copy", "asset_uids": [api_world["asset_uid"]]},
        headers={"X-Workspace-Id": api_world["source"]},
    )
    assert resp.status_code == 403
    db.close()


def test_transfer_runs_end_to_end_through_the_api(api_world):
    setup_db = SessionLocal()
    setup_db.add(Membership(workspace_id=api_world["source"], user_id=api_world["user_id"], can_read=True))
    setup_db.add(Membership(workspace_id=api_world["target"], user_id=api_world["user_id"], can_create=True))
    setup_db.commit()
    setup_db.close()

    db = SessionLocal()
    user = db.get(User, api_world["user_id"])
    as_identity(OidcIdentity(user=user))

    resp = client.post(
        "/v1/transfers",
        json={"target_workspace_id": api_world["target"], "mode": "copy", "asset_uids": [api_world["asset_uid"]]},
        headers={"X-Workspace-Id": api_world["source"]},
    )
    assert resp.status_code == 201, resp.text
    job_uid = resp.json()["uid"]

    status = client.get(f"/v1/transfers/{job_uid}", headers={"X-Workspace-Id": api_world["source"]})
    assert status.status_code == 200
    assert status.json()["status"] == "succeeded"
    assert status.json()["counts"]["assets"] == 1
    db.close()
