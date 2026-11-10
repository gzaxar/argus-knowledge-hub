"""A retired or merged record keeps its history and opens by its key, but what looks for records does not offer it:
a magnet renamed in the beam model must not stay in the answers beside its new name."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models.asset import Asset
from app.services import beam_model as bm, jql, knowledge_hub, mcp_tools
from tests.test_beam_model import load, world, db  # noqa: F401 — fixtures shared with the beam model's tests

client = TestClient(app)


def renamed(db, ws):  # noqa: F811
    doc = load("linac.json")
    for e in doc["elements"]:
        if e["id"] == "ACC02":
            e["id"], e["name"] = "ACC02B", "ACC02B"
    for p in doc["paths"]:
        p["elements"] = ["ACC02B" if x == "ACC02" else x for x in p["elements"]]
    assert bm.import_canonical(db, ws, doc, "test")["state"] == "published"
    db.commit()
    old = record(db, ws, "ACC02")
    assert old.record_status == "Retired"
    return old


def record(db, ws, ident):  # noqa: F811
    """A beam record by its id in the model: its key follows the workspace's Record keys pattern."""
    uid = next(u for u, i in bm.model_ids(db, ws, "linac-demo", "element").items() if i == ident)
    return db.get(Asset, uid)


def keys(result):
    return {o["key"] for o in result["objects"]}


def test_ask_does_not_find_a_retired_record_unless_asked(world, db):  # noqa: F811
    ws = world["ws"]
    old = renamed(db, ws)
    found = mcp_tools.search_objects(db, ws, types=[old.type])
    assert record(db, ws, "ACC02B").key in keys(found) and old.key not in keys(found)
    assert found["by_type"][old.type] == found["total"]
    assert mcp_tools.search_objects(db, ws, query="ACC02")["total"] == 1
    asked = mcp_tools.search_objects(db, ws, query="ACC02", include_retired=True)
    assert asked["total"] == 2
    assert {o["key"]: o.get("status") for o in asked["objects"]}[old.key] == "Retired"
    # Opened by its key it is still there, and says what it is.
    opened = mcp_tools.get_object(db, ws, old.key)
    assert opened["found"] and opened["status"] == "Retired"
    assert "status" not in mcp_tools.get_object(db, ws, record(db, ws, "ACC02B").key)


def test_a_page_of_records_and_the_type_counts_leave_it_out(world, db):  # noqa: F811
    ws = world["ws"]
    old = renamed(db, ws)
    h = world["h"]
    page = client.get("/v1/assets", headers=h, params={"limit": 500, "q": "ACC02"}).json()
    assert {a["key"] for a in page} == {record(db, ws, "ACC02B").key}
    both = client.get("/v1/assets", headers=h, params={"limit": 500, "q": "ACC02", "include_retired": True}).json()
    assert {a["key"]: a["record_status"] for a in both}[old.key] == "Retired"
    # The whole list stays whole: it is what resolves a link to a retired record into its name.
    assert old.key in {a["key"] for a in client.get("/v1/assets", headers=h).json()}
    assert client.get(f"/v1/assets/{old.uid}", headers=h).json()["record_status"] == "Retired"
    live = db.scalars(select(Asset).where(Asset.workspace_id == ws, Asset.schema_uid == old.schema_uid,
                                          Asset.record_status == "Active", Asset.deleted_at.is_(None))).all()
    assert client.get("/v1/assets/type-counts", headers=h).json()[old.schema_uid] == len(live)


def test_search_finds_it_only_by_naming_a_status(world, db):  # noqa: F811
    ws = world["ws"]
    old = renamed(db, ws)

    def query(text):
        return {r.key for r in jql.run(db, "assets", text, user_ids=[], workspaces=[ws], current_workspace=ws,
                                       visible=lambda r: True)["rows"]}
    assert query('name ~ "ACC02"') == {record(db, ws, "ACC02B").key}
    assert query("status = Retired") == {old.key}
    assert old.key in query('name ~ "ACC02" AND status != Active')
    hub = knowledge_hub.unified_search(db, ws, knowledge_hub.Access(assets=True, tickets=False, documents=False),
                                       "ACC02")
    found = {a["key"] for a in hub["assets"]}
    assert record(db, ws, "ACC02B").key in found and old.key not in found
