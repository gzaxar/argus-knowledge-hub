"""Tickets and beam model records take their keys from the workspace's Record keys pattern."""
import secrets
import uuid

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models.asset import Asset
from app.models.asset_subresources import AssetLabel
from app.models.issue import Issue
from app.models.workspace import Workspace
from app.services import asset_keys
from app.services.mcp_tools import call
from tests.test_beam_converters import db_world  # noqa: F401


@pytest.fixture()
def ws():
    workspace = f"k{secrets.token_hex(3)}"
    db = SessionLocal()
    db.add(Workspace(id=workspace, name="Keys"))
    db.commit()
    db.close()
    yield workspace
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    db.delete(db.get(Workspace, workspace))
    db.commit()
    db.close()


def ticket(db, ws, title, key=None):
    issue = Issue(uid=str(uuid.uuid4()), workspace_id=ws, title=title, key=key, attributes={}, labels=[])
    db.add(issue)
    db.commit()
    return issue


def test_a_new_ticket_gets_the_next_key_however_it_is_made(ws):
    db = SessionLocal()
    a, b = ticket(db, ws, "first"), ticket(db, ws, "second")
    assert a.key == f"{ws.upper()}-TCK-0001" and b.key == f"{ws.upper()}-TCK-0002"
    given = ticket(db, ws, "imported", key=f"{ws.upper()}-TCK-0003")
    assert given.key == f"{ws.upper()}-TCK-0003", "a key someone gave is kept"
    assert ticket(db, ws, "next").key == f"{ws.upper()}-TCK-0004", "and skipped"
    db.close()


def test_the_workspace_pattern_shapes_the_ticket_key(ws):
    db = SessionLocal()
    db.get(Workspace, ws).asset_key_pattern = "{WS}/{TYPE}/{YYYY}/{SEQ:3}"
    db.commit()
    key = ticket(db, ws, "patterned").key
    assert key.startswith(f"{ws.upper()}/TCK/") and key.endswith("/001")
    db.close()


def test_a_ticket_is_found_by_its_key(ws):
    db = SessionLocal()
    issue = ticket(db, ws, "Vacuum leak at the septum")
    import json
    got = json.loads(call(db, ws, "get_ticket", {"uid": issue.key}))
    assert got["found"] and got["uid"] == issue.uid and got["key"] == issue.key
    found = json.loads(call(db, ws, "search_tickets", {"query": issue.key.lower()}))
    assert [t["uid"] for t in found["tickets"]] == [issue.uid]
    db.close()


def test_old_tickets_get_keys_oldest_first_when_asked(ws):
    db = SessionLocal()
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    old = [ticket(db, ws, f"old {n}") for n in range(3)]
    db.execute(update(Issue).where(Issue.uid.in_([i.uid for i in old])).values(key=None))
    for n, i in enumerate(reversed(old)):
        db.execute(update(Issue).where(Issue.uid == i.uid).values(created_at=t0 + timedelta(days=n)))
    db.commit()
    done = asset_keys.backfill_ticket_keys(db, ws)
    db.commit()
    assert [uid for uid, _ in done] == [i.uid for i in reversed(old)]
    assert all(k.startswith(f"{ws.upper()}-TCK-") for _, k in done)
    assert asset_keys.backfill_ticket_keys(db, ws) == [], "only tickets with no key"
    db.close()


def test_a_ticket_key_is_never_an_object_key(ws):
    db = SessionLocal()
    from app.models.schema import Schema
    schema = Schema(uid=f"{ws}:tck", workspace_id=ws, name="Ticket Thing", applies_to="objects",
                    metadata_json={"key_prefix": "TCK"})
    db.add(schema)
    db.flush()
    taken = ticket(db, ws, "first").key
    assert asset_keys.allocate(db, ws, schema) != taken
    db.rollback()
    db.close()


MODEL = {
    "schema_version": "argus.beam-model/2",
    "model": {"id": "ring", "name": "Ring"},
    "systems": [{"id": "ring", "name": "Ring", "kind": "Other"}],
    "paths": [{"id": "arc", "system": "ring", "topology": "open", "placements": ["QF1", "QD1"]}],
    "components": [{"id": "QF1", "type": "quadrupole"}, {"id": "QD1", "type": "quadrupole"}],
}


def test_beam_model_records_take_the_pattern_and_say_their_model(db_world):
    from tests.test_beam_model import client
    h = db_world
    ws = h["X-Workspace-Id"]
    assert client.post("/v1/beam-model/import", headers=h, json=MODEL).status_code == 200
    db = SessionLocal()
    quads = {a.name: a for a in db.scalars(select(Asset).where(Asset.workspace_id == ws, Asset.name.in_(["QF1", "QD1"])))}
    assert {a.key for a in quads.values()} == {f"{ws.upper()}-QUA-0001", f"{ws.upper()}-QUA-0002"}
    assert all(a.attributes.get("beam_model") == "ring" for a in quads.values())
    found = __import__("json").loads(call(db, ws, "search_objects", {"query": "QF1"}))
    assert found["objects"][0]["model"] == "ring"
    db.close()
    again = client.post("/v1/beam-model/import", headers=h, json={**MODEL, "model": {"id": "ring", "name": "Ring 2"}})
    assert again.status_code == 200
    db = SessionLocal()
    assert {a.key for a in db.scalars(select(Asset).where(Asset.workspace_id == ws, Asset.name.in_(["QF1", "QD1"])))} \
        == {a.key for a in quads.values()}, "a re-import keeps the keys"
    db.close()


def test_records_keyed_the_old_way_get_the_pattern_and_keep_the_old_key(db_world):
    from app.services import beam_model as bm
    from tests.test_beam_model import client
    h = db_world
    ws = h["X-Workspace-Id"]
    assert client.post("/v1/beam-model/import", headers=h, json=MODEL).status_code == 200
    db = SessionLocal()
    rows = list(db.scalars(select(Asset).where(Asset.workspace_id == ws, Asset.name.in_(["QF1", "QD1"]))))
    for a in rows:
        a.key = f"{ws}:ring/{a.name}"          # as every record made before this release
    db.commit()
    done = bm.rekey_records(db, ws, "tester")
    db.commit()
    assert {old for old, _ in done} >= {f"{ws}:ring/QF1", f"{ws}:ring/QD1"}
    qf1 = db.scalar(select(Asset).where(Asset.workspace_id == ws, Asset.name == "QF1"))
    assert qf1.key.startswith(f"{ws.upper()}-QUA-")
    assert db.scalar(select(AssetLabel.value).where(AssetLabel.asset_uid == qf1.uid, AssetLabel.type == "former_key")) \
        == f"{ws}:ring/QF1"
    import json
    assert json.loads(call(db, ws, "get_object", {"uid_or_key": f"{ws}:ring/QF1"}))["uid"] == qf1.uid
    assert bm.rekey_records(db, ws, "tester") == [], "once"
    db.close()
