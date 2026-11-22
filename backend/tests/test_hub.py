"""The unified knowledge layer: an asset, its tickets and its documents in one answer.

The case is an ion pump. A procedure is written for every *Vacuum Pump* (its
parent type), a manual for its product model, and a note for this very unit.
Two tickets are raised on it (one open, one closed), and a third is linked to
it after the fact. Every view of the pump, of the ticket and of the procedure
has to show the other two.
"""
import secrets
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import hash_token
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models.api_token import ApiToken
from app.models.asset import Asset, Relation
from app.models.asset_subresources import AssetTicket
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.models.issue import Issue
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.services import knowledge_hub as hub

client = TestClient(app)
NOW = datetime.now(timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield


@pytest.fixture()
def world():
    ws = f"hub-{secrets.token_hex(4)}"
    t = secrets.token_hex(3)
    db = SessionLocal()
    db.add(Workspace(id=ws, name="Hub"))
    db.flush()
    db.add(Schema(uid=f"{ws}:pump", workspace_id=ws, name="Vacuum Pump", applies_to="objects"))
    db.flush()
    db.add(Schema(uid=f"{ws}:ion", workspace_id=ws, name="Ion Pump", applies_to="objects",
                  parent_schema_uid=f"{ws}:pump"))
    db.add(Schema(uid=f"{ws}:pm", workspace_id=ws, name="Product Model", applies_to="objects"))
    db.flush()
    db.add(Asset(uid=f"{ws}-model", workspace_id=ws, schema_uid=f"{ws}:pm", key=f"PM{t}-1",
                 name="Agilent IPCMini", type="Product Model", attributes={}))
    db.add(Asset(uid=f"{ws}-pump", workspace_id=ws, schema_uid=f"{ws}:ion", key=f"SP{t}-12",
                 name="GUNSIP01", type="Ion Pump",
                 attributes={"serial": f"SN-{t}-84321", "product_model": f"{ws}-model",
                             "argus_system": "Vacuum"}))
    db.add(Asset(uid=f"{ws}-moxa", workspace_id=ws, schema_uid=f"{ws}:pm", key=f"MX{t}-1",
                 name="scsparcsipmxa001", type="Serial Converter", attributes={}))
    db.flush()
    db.add(Relation(workspace_id=ws, from_asset_uid=f"{ws}-pump", to_asset_uid=f"{ws}-moxa",
                    relation_type="reached through"))
    db.add(Issue(uid=f"{ws}-t1", workspace_id=ws, title="GUNSIP01 pressure spikes", state="new",
                 asset_uid=f"{ws}-pump", priority="high"))
    db.add(Issue(uid=f"{ws}-t2", workspace_id=ws, title="GUNSIP01 controller replaced", state="closed",
                 asset_uid=f"{ws}-pump", closed_at=NOW))
    db.add(Issue(uid=f"{ws}-t3", workspace_id=ws, title="Vacuum readback frozen", state="new"))
    db.flush()
    db.add(AssetTicket(uid=f"{ws}-at3", asset_uid=f"{ws}-pump", ticket_key=f"{ws}-t3",
                       summary="Vacuum readback frozen", type="affects", status="new",
                       created=NOW, updated=NOW))
    db.add(AssetTicket(uid=f"{ws}-atj", asset_uid=f"{ws}-pump", ticket_key="SPARC-77",
                       summary="Old Jira ticket", type="Incident", status="Done",
                       created=NOW, updated=NOW, backend_url="https://jira.example/browse/SPARC-77"))
    docs = [
        ("proc", f"PRC-{t}-1", "Ion pump bake-out procedure", ("schema", f"{ws}:pump")),
        ("manual", f"MAN-{t}-1", "IPCMini controller manual", ("asset", f"{ws}-model")),
        ("note", f"NOTE-{t}-1", "GUNSIP01 installation note", ("asset", f"{ws}-pump")),
        ("other", f"OTH-{t}-1", "Magnet cycling", None),
    ]
    for key, code, title, target in docs:
        db.add(Document(uid=f"{ws}-{key}", workspace_id=ws, code=code, title=title))
        db.flush()
        rev = DocumentRevision(uid=f"{ws}-{key}-r1", document_uid=f"{ws}-{key}", revision_number=1,
                               state="published",
                               next_review_due=date.today() - timedelta(days=3) if key == "proc" else None)
        db.add(rev)
        db.flush()
        db.get(Document, f"{ws}-{key}").current_revision_uid = rev.uid
        if target:
            db.add(DocumentRelation(workspace_id=ws, from_document_uid=f"{ws}-{key}",
                                    to_type=target[0], to_uid=target[1], relation_type="describes"))
    # The note is already linked to ticket 1, so it is not "suggested" there.
    db.add(DocumentRelation(workspace_id=ws, from_document_uid=f"{ws}-note", to_type="issue",
                            to_uid=f"{ws}-t1", relation_type="documents"))
    raw = secrets.token_urlsafe(16)
    db.add(ApiToken(workspace_id=ws, token_hash=hash_token(raw)))
    db.commit()
    db.close()
    return {"ws": ws, "t": t, "headers": {"Authorization": f"Bearer {raw}"}}


def test_an_asset_shows_its_tickets_documents_and_connections(world):
    ws = world["ws"]
    resp = client.get(f"/v1/hub/assets/{ws}-pump/context", headers=world["headers"])
    assert resp.status_code == 200, resp.text
    ctx = resp.json()
    assert ctx["type_path"] == ["Vacuum Pump", "Ion Pump"]
    tickets = {t["uid"]: t for t in ctx["tickets"]}
    # Its subject tickets and the one linked afterwards; the open ones first.
    assert set(tickets) == {f"{ws}-t1", f"{ws}-t2", f"{ws}-t3"}
    assert ctx["tickets"][-1]["uid"] == f"{ws}-t2" and not ctx["tickets"][-1]["open"]
    assert ctx["stats"]["open_tickets"] == 2
    # The Jira ticket that has no native counterpart is listed as external.
    assert [e["key"] for e in ctx["external_tickets"]] == ["SPARC-77"]
    via = {d["uid"]: d["via"] for d in ctx["documents"]}
    assert via == {f"{ws}-note": "asset", f"{ws}-manual": "product", f"{ws}-proc": "type"}
    proc = next(d for d in ctx["documents"] if d["uid"] == f"{ws}-proc")
    assert proc["via_label"] == "Vacuum Pump" and proc["review_overdue"]
    assert ctx["stats"]["documents_overdue"] == 1
    assert ctx["relations"]["items"][0]["name"] == "scsparcsipmxa001"


def test_a_section_the_caller_cannot_read_comes_back_empty(world):
    db = SessionLocal()
    pump = db.get(Asset, f"{world['ws']}-pump")
    ctx = hub.asset_context(db, world["ws"], pump, hub.Access(assets=True, tickets=False, documents=True))
    db.close()
    assert ctx["tickets"] == [] and ctx["external_tickets"] == []
    assert ctx["access"]["tickets"] is False
    assert ctx["documents"]


def test_a_ticket_shows_its_equipment_and_the_knowledge_for_it(world):
    ws = world["ws"]
    resp = client.get(f"/v1/hub/tickets/{ws}-t1/context", headers=world["headers"])
    assert resp.status_code == 200, resp.text
    ctx = resp.json()
    assert [a["uid"] for a in ctx["assets"]] == [f"{ws}-pump"]
    suggested = {d["uid"] for d in ctx["suggested_documents"]}
    # Everything that applies to the pump, except what is already linked.
    assert suggested == {f"{ws}-proc", f"{ws}-manual"}
    assert [t["uid"] for t in ctx["concurrent_tickets"]] == [f"{ws}-t3"]


def test_a_document_shows_where_it_applies_and_what_is_open_there(world):
    ws = world["ws"]
    ctx = client.get(f"/v1/hub/documents/{ws}-proc/context", headers=world["headers"]).json()
    assert ctx["types"] == [{"uid": f"{ws}:pump", "name": "Vacuum Pump", "assets": 1}]
    manual = client.get(f"/v1/hub/documents/{ws}-manual/context", headers=world["headers"]).json()
    # A manual for a product model covers every instance of it.
    assert [a["uid"] for a in manual["instances"]] == [f"{ws}-pump"]
    assert {t["uid"] for t in manual["open_tickets"]} == {f"{ws}-t1", f"{ws}-t3"}


def test_one_search_finds_equipment_tickets_and_documents(world):
    ws, t = world["ws"], world["t"]
    by_serial = client.get(f"/v1/hub/search?q=SN-{t}-84321", headers=world["headers"]).json()
    assert [a["uid"] for a in by_serial["assets"]] == [f"{ws}-pump"]
    mixed = client.get("/v1/hub/search?q=GUNSIP01", headers=world["headers"]).json()
    assert mixed["assets"][0]["name"] == "GUNSIP01"
    assert {i["uid"] for i in mixed["tickets"]} >= {f"{ws}-t1", f"{ws}-t2"}
    assert [d["uid"] for d in mixed["documents"]] == [f"{ws}-note"]
    assert client.get("/v1/hub/search?q=x", headers=world["headers"]).json()["assets"] == []


def test_the_cockpit_shows_what_needs_attention(world):
    ov = client.get("/v1/hub/overview", headers=world["headers"]).json()
    ws = world["ws"]
    assert ov["tickets"]["open"] == 2 and ov["tickets"]["total"] == 3
    assert ov["tickets"]["hotspots"][0]["uid"] == f"{ws}-pump"
    assert ov["tickets"]["hotspots"][0]["open_tickets"] == 1
    assert ov["tickets"]["without_asset"] == 1
    assert [d["uid"] for d in ov["documents"]["review_overdue"]] == [f"{ws}-proc"]
    assert ov["documents"]["not_linked_to_assets"] == 1
    assert ov["assets"]["own"] == 3


def test_another_workspaces_private_records_are_not_reachable(world):
    other = client.get(f"/v1/hub/assets/{world['ws']}-pump/context", headers={
        "Authorization": world["headers"]["Authorization"] + "x"})
    assert other.status_code == 401
    missing = client.get("/v1/hub/tickets/nope/context", headers=world["headers"])
    assert missing.status_code == 404


def test_an_object_cannot_be_made_with_another_workspaces_private_type(world):
    db = SessionLocal()
    foreign = f"foreign-{secrets.token_hex(4)}"
    db.add(Workspace(id=foreign, name="Foreign"))
    db.flush()
    db.add(Schema(uid=f"{foreign}:secret", workspace_id=foreign, name="Secret", applies_to="objects"))
    db.commit()
    db.close()
    resp = client.post("/v1/assets", headers=world["headers"], json={
        "uid": f"{world['ws']}-x", "schema_uid": f"{foreign}:secret", "key": f"X{world['t']}-9",
        "name": "x", "type": "Secret", "attributes": {}})
    assert resp.status_code == 422


def test_looking_at_an_object_does_not_mark_it_changed(world):
    """Reading an object resyncs its relation cache; that must not bump
    updated_at, or "recent activity" lists whatever somebody merely opened."""
    uid = f"{world['ws']}-pump"
    first = client.get(f"/v1/assets/{uid}", headers=world["headers"]).json()["updated_at"]
    second = client.get(f"/v1/assets/{uid}", headers=world["headers"]).json()["updated_at"]
    assert first == second


def test_start_here_follows_a_new_workspace_until_it_is_set_up():
    """The cockpit's *Start here*: places, equipment, people, a first document, a first ticket — each done once
    the workspace has one, the creator not counting as someone invited."""
    from app.models.membership import Membership
    from app.models.role import RoleBinding
    ws = f"start-{secrets.token_hex(4)}"
    db = SessionLocal()
    try:
        db.add(Workspace(id=ws, name="Start"))
        db.flush()
        for name, parent in (("item", None), ("location", "item"), ("building", "location"),
                             ("engineered-item", "item"), ("asset", "engineered-item"), ("vacuum-pump", "asset")):
            db.add(Schema(uid=f"{ws}:argus-object:{name}", workspace_id=ws, name=name.title(), applies_to="objects",
                          parent_schema_uid=f"{ws}:argus-object:{parent}" if parent else None))
            db.flush()
        from app.models.user import User
        creator = User(id=f"{ws}-creator", email=f"{ws}@example.org", active=True)
        db.add(creator)
        db.flush()
        db.add(Membership(workspace_id=ws, user_id=creator.id))
        db.commit()
        everything = hub.Access(True, True, True)
        start = hub.start_here(db, ws, everything)
        assert [s["key"] for s in start["steps"]] == ["places", "equipment", "people", "document", "ticket"]
        assert not start["done"] and not any(s["done"] for s in start["steps"])
        assert start["steps"][0]["type_uid"] == f"{ws}:argus-object:building"

        db.add(Asset(uid=f"{ws}-hall", workspace_id=ws, schema_uid=f"{ws}:argus-object:building", key=f"{ws}-B1",
                     name="Hall", type="Building", attributes={}))
        db.add(RoleBinding(workspace_id=ws, subject_type="user", subject_id="colleague", role_id="viewer",
                           created_at=NOW))
        db.commit()
        start = {s["key"]: s for s in hub.start_here(db, ws, everything)["steps"]}
        assert start["places"]["done"] and not start["equipment"]["done"], "a building is a place, not equipment"
        assert start["people"]["count"] == 1

        db.add(Asset(uid=f"{ws}-pump", workspace_id=ws, schema_uid=f"{ws}:argus-object:vacuum-pump",
                     key=f"{ws}-P1", name="Pump", type="Vacuum Pump", attributes={}))
        db.add(Document(uid=f"{ws}-doc", code=f"{ws}-D1", title="Procedure", workspace_id=ws))
        db.add(Issue(uid=f"{ws}-tck", workspace_id=ws, title="Leak", state="new"))
        db.commit()
        assert hub.start_here(db, ws, everything)["done"]
        assert [s["key"] for s in hub.start_here(db, ws, hub.Access(True, False, False))["steps"]] == \
            ["places", "equipment", "people"], "only the steps of what the caller may read"
    finally:
        db.close()


def test_a_first_document_sent_for_review_is_waiting_for_approval():
    """A document never published has no current revision; its revision in review still waits for approval, in the
    tile and in the list under it alike."""
    ws = f"first-{secrets.token_hex(4)}"
    db = SessionLocal()
    try:
        db.add(Workspace(id=ws, name="First"))
        db.flush()
        db.add(Document(uid=f"{ws}-doc", workspace_id=ws, code=f"{ws}-P1", title="Pump replacement"))
        db.flush()
        db.add(DocumentRevision(uid=f"{ws}-doc-r1", document_uid=f"{ws}-doc", revision_number=1, state="in_review"))
        db.commit()
        docs = hub.overview(db, ws, hub.Access(False, False, True), None, setup=False)["documents"]
        assert docs["in_review"] == 1
        assert [(d["uid"], d["state"]) for d in docs["awaiting_review"]] == [(f"{ws}-doc", "in_review")]
    finally:
        db.close()


def test_a_document_offers_the_equipment_its_text_names_and_is_not_linked_to():
    """An imported page names a pump and a hall: both are offered to link, the one already linked is not, and
    nothing is linked by itself."""
    ws = f"named-{secrets.token_hex(4)}"
    db = SessionLocal()
    try:
        db.add(Workspace(id=ws, name="Named"))
        db.flush()
        db.add(Schema(uid=f"{ws}:pump", workspace_id=ws, name="Pump", applies_to="objects"))
        db.flush()
        n = secrets.token_hex(3).upper()                 # keys are unique across every workspace
        for uid, key, name in (("p1", f"IP-{n}3", "Pompa ionica sezione 1A"), ("hall", f"B{n}-HALL", "Hall"),
                               ("p2", f"IP-{n}4", "Pompa ionica sezione 1B")):
            db.add(Asset(uid=f"{ws}-{uid}", workspace_id=ws, schema_uid=f"{ws}:pump", key=key, name=name,
                         type="Pump", attributes={}))
        db.add(Document(uid=f"{ws}-doc", workspace_id=ws, code=f"{ws}-D", title="Prova di tenuta"))
        db.flush()
        db.add(DocumentRevision(uid=f"{ws}-doc-r1", document_uid=f"{ws}-doc", revision_number=1, state="published",
                                body_markdown=f"Se la Pompa ionica sezione 1A in B{n}-HALL non tiene, vedi la 1B."))
        db.add(DocumentRelation(workspace_id=ws, from_document_uid=f"{ws}-doc", to_type="asset", to_uid=f"{ws}-hall",
                                relation_type="describes"))
        db.commit()
        c = hub.document_context(db, ws, db.get(Document, f"{ws}-doc"), hub.Access(True, True, True))
        assert [(a["uid"], a["matched_on"]) for a in c["named"]] == [(f"{ws}-p1", "name")]
        assert [a["uid"] for a in c["assets"]] == [f"{ws}-hall"]
        assert hub.document_context(db, ws, db.get(Document, f"{ws}-doc"), hub.Access(False, True, True))["named"] == []
    finally:
        db.close()
