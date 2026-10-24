"""Migrating records to a package type (app/services/type_migration.py, docs/type-migration.md).

A shared catalogue workspace defines a custom "Server" — the same name as the `it` package's Server, a different
type — used by records in two workspaces that hang from the catalogue. They move to the package's Server, found by
its package, version and the installer's identity for it, never by name; their history, files, map position,
indoor placement, comments and relations stay; a rebuild of the ledger keeps the result; applying again changes
nothing; restricted records are not moved by someone who may not see them; a reference that the new type would
break blocks the move. Documents keep their revisions; tickets get a state of the target workflow.
"""
from __future__ import annotations

import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm.attributes import flag_modified

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.asset import Asset, Relation
from app.models.asset_subresources import AssetComment, AssetHistory
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRevision
from app.models.issue import Issue, IssueHistory
from app.models.schema import Schema
from app.models.type_migration import TypeMigration, TypeMigrationItem
from app.models.user import User
from app.models.workspace import Workspace
from app.packages import install as installer
from app.packages.install import kind_uid
from app.services import asset_types, visibility
from app.services import type_migration as tm

ALL = lambda ws: visibility.Grants.all()  # noqa: E731
ACTOR = "admin-tm@argus.test"


# --------------------------------------------------------------------------- the world

def _asset(db, ws, schema, key, name, attrs):
    from app.ledger import service as ledger
    uid = str(uuid.uuid4())
    ledger.create_record(db, ws, ACTOR, uid=uid, schema_uid=schema.uid, key=key, name=name, type_name=schema.name,
                         attributes=attrs)
    return db.get(Asset, uid)


@pytest.fixture(scope="module")
def world():
    t = secrets.token_hex(3)
    cat, w1, w2, w3, other = f"tmc-{t}", f"tm1-{t}", f"tm2-{t}", f"tm3-{t}", f"tmo-{t}"
    db = SessionLocal()
    for w in (cat, w1, w2, w3, other):
        db.add(Workspace(id=w, name=w))
    db.flush()
    installer.install(db, cat, ["core-facility", "core-objects", "it"], scope="global", actor="test")
    installer.install(db, other, ["core-facility", "core-objects", "it"], scope="global", actor="test")
    for w in (w1, w2):
        installer.install(db, w, ["core-facility", "core-objects", "it"], catalogue_workspace_id=cat, actor="test")
    installer.install(db, w3, ["core-facility"], actor="test")      # no `it`: the target is missing there
    db.flush()
    it_equipment = db.get(Schema, asset_types.type_uid(cat, "IT Equipment"))
    # The shared catalogue's own "Server": a custom type with the package type's name.
    custom = Schema(uid=f"{cat}:custom:server", workspace_id=cat, name="Server", applies_to="objects", is_global=True,
                    parent_schema_uid=it_equipment.uid, metadata_json={},
                    attributes=[{"key": "state", "name": "State", "type": "enumeration",
                                 "options": [{"id": "ok", "value": "OK"}, {"id": "broken", "value": "Broken"}]},
                                {"key": "legacy_code", "name": "Legacy code", "type": "string"},
                                {"key": "cores", "name": "Cores", "type": "string"}])
    db.add(custom)
    # A type that refers to custom servers specifically: moving them would break its references.
    rack_unit = Schema(uid=f"{w2}:custom:rack-unit", workspace_id=w2, name="Rack unit", applies_to="objects",
                       parent_schema_uid=it_equipment.uid, metadata_json={},
                       attributes=[{"key": "server", "name": "Server", "type": "reference",
                                    "referenceSchemaUid": custom.uid}])
    db.add(rack_unit)
    db.flush()
    s1 = _asset(db, w1, custom, f"S1-{t}", "srv-a", {"state": "OK", "legacy_code": "X-1", "cores": "32", "hostname": "a"})
    s2 = _asset(db, w1, custom, f"S2-{t}", "srv-b", {"state": "Broken", "legacy_code": "X-2"})
    s3 = _asset(db, w2, custom, f"S3-{t}", "srv-c", {"state": "OK", "classification": "restricted:security"})
    s4 = _asset(db, w2, custom, f"S4-{t}", "srv-d", {"state": "OK"})
    ru = _asset(db, w2, rack_unit, f"RU-{t}", "ru-1", {"server": s4.uid})
    # s1's surroundings: a comment, a file, a relation, a map position and an indoor placement.
    building = _asset(db, w1, db.get(Schema, asset_types.type_uid(cat, "Building")), f"B-{t}", "hall", {})
    db.add(AssetComment(uid=str(uuid.uuid4()), asset_uid=s1.uid, author=ACTOR, text="note", created=tm.now(),
                        updated=tm.now()))
    db.add(Attachment(uid=str(uuid.uuid4()), workspace_id=w1, asset_uid=s1.uid, filename="cfg.txt", storage_path="/x",
                      created_at=tm.now(), updated_at=tm.now()))
    db.add(Relation(workspace_id=w1, from_asset_uid=s1.uid, to_asset_uid=s2.uid, relation_type="connects to"))
    from app.services import indoor, spatial
    spatial.set_location(db, s1, spatial.point(43.0, 12.0), actor=ACTOR, source="survey")
    indoor.place(db, s1, place_uid=building.uid, level_uid=None, plan_uid=None, x=None, y=None, actor=ACTOR)
    # A ticket type and a document type of w1's own, with records.
    fault = Schema(uid=f"{w1}:custom:fault", workspace_id=w1, name="Fault", applies_to="tickets",
                   parent_schema_uid=kind_uid(w1, "ticket_types", "base"), metadata_json={},
                   attributes=[{"key": "symptom", "name": "Symptom", "type": "string"}])
    note = Schema(uid=f"{w1}:custom:field-note", workspace_id=w1, name="Field note", applies_to="documents",
                  parent_schema_uid=kind_uid(w1, "document_types", "base"), metadata_json={},
                  attributes=[{"key": "ref_no", "name": "Reference number", "type": "string"}])
    db.add_all([fault, note])
    db.flush()
    tk = Issue(uid=str(uuid.uuid4()), workspace_id=w1, schema_uid=fault.uid, title="pump noise", state="triage",
               labels=[], attributes={"symptom": "rattle"}, version=1, created_at=tm.now(), updated_at=tm.now())
    db.add(tk)
    doc = Document(uid=str(uuid.uuid4()), workspace_id=w1, code=f"FN-{t}", title="Hall walk-down",
                   document_type_uid=note.uid, authority_level="informativo", confidentiality="interno", source="manual",
                   created_at=tm.now(), updated_at=tm.now())
    db.add(doc)
    db.flush()
    revs = []
    for n in (1, 2):
        r = DocumentRevision(uid=f"{doc.uid}-r{n}", document_uid=doc.uid, revision_number=n,
                             state="published" if n == 2 else "superseded", body_markdown=f"rev {n}",
                             attributes={"ref_no": f"R-{n}"}, steps=[], created_at=tm.now(), updated_at=tm.now())
        db.add(r)
        revs.append(r)
    db.flush()
    doc.current_revision_uid = revs[-1].uid
    db.commit()
    w = dict(t=t, cat=cat, w1=w1, w2=w2, w3=w3, other=other, custom=custom.uid, rack_unit=rack_unit.uid,
             s1=s1.uid, s2=s2.uid, s3=s3.uid, s4=s4.uid, ru=ru.uid, fault=fault.uid, note=note.uid, ticket=tk.uid,
             doc=doc.uid, target_server=asset_types.type_uid(cat, "Server"))
    db.close()
    yield w
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    db.query(TypeMigration).filter(TypeMigration.source_schema_uid.in_([w["custom"], w["fault"], w["note"]])).delete(
        synchronize_session=False)
    db.commit()
    for ws in (w1, w2, w3, other, cat):
        allow_purge(db)
        row = db.get(Workspace, ws)
        if row is not None:
            db.delete(row)
        db.commit()
    db.close()


SERVER = {"package_id": "it", "type": "Server"}


def _plan(db, w, **kw):
    args = dict(kind="objects", source_schema_uid=w["custom"], target=SERVER, workspaces=[w["w1"], w["w2"]],
                include_descendants=False, reason="custom servers to the IT package's Server")
    args.update(kw)
    return tm.create(db, ACTOR, args["kind"], args["source_schema_uid"], args["target"], args["workspaces"],
                     args["include_descendants"], args["reason"])


# --------------------------------------------------------------------------- the target, by identity

def test_the_target_is_the_package_type_where_the_records_live_never_a_namesake(world):
    db = SessionLocal()
    for ws in (world["w1"], world["w2"]):
        r = tm.resolve_target(db, ws, "objects", SERVER)
        assert r["status"] == "ok" and r["home"] == world["cat"] and r["schema_uid"] == world["target_server"]
        assert r["schema_uid"] != world["custom"]                       # the custom "Server" is not it
        assert r["installed_version"] == installer.installed(db, world["cat"])["it"].version
    # Another catalogue's package Server is not chosen for records of these workspaces.
    assert tm.resolve_target(db, world["w1"], "objects", SERVER)["schema_uid"] != asset_types.type_uid(world["other"], "Server")
    # The custom Server is a source, the package Server is not.
    srcs = {s["uid"] for s in tm.sources(db, "objects")}
    assert world["custom"] in srcs and world["target_server"] not in srcs
    db.close()


def test_a_missing_package_says_where_it_is_needed_and_previews_the_install(world):
    db = SessionLocal()
    r = tm.resolve_target(db, world["w3"], "objects", SERVER)
    assert r["status"] == "package_missing" and r["home"] == world["w3"] and "it is not installed" in r["detail"]
    p = tm.install_preview(db, world["w3"], "it")
    assert p["ok"] and any(s["package_id"] == "it" and s["action"] == "install" for s in p["plan"]["steps"])
    assert "it" not in installer.installed(db, world["w3"])            # a preview installs nothing
    db.close()


# --------------------------------------------------------------------------- mapping, preview

def test_the_proposal_copies_shared_fields_and_keeps_the_rest_in_provenance(world):
    db = SessionLocal()
    m = _plan(db, world)
    a = m.mapping["attributes"]
    assert a["hostname"]["action"] == "copy" and a["hostname"]["to"] == "hostname"
    assert a["legacy_code"]["action"] == "provenance" and a["cores"]["action"] == "provenance"
    assert "classification" not in a                                   # never mapped
    db.close()


def test_preview_writes_nothing_and_blocks_what_the_target_would_refuse(world):
    db = SessionLocal()
    m = _plan(db, world)
    m = tm.change(db, m, ACTOR, {"attributes": {"state": {"action": "copy", "to": "condition",
                                                          "values": {"OK": "good"}}}})
    before = db.scalar(select(func.count()).select_from(TypeMigrationItem))
    types_before = {u: db.get(Asset, world[u]).schema_uid for u in ("s1", "s2", "s3", "s4")}
    p = tm.preview(db, m, ALL)
    db.rollback()
    assert db.scalar(select(func.count()).select_from(TypeMigrationItem)) == before
    assert {u: db.get(Asset, world[u]).schema_uid for u in types_before} == types_before
    by = {r["uid"]: r for r in p["records"]}
    assert by[world["s1"]]["status"] == "ready"
    assert by[world["s2"]]["status"] == "blocked"                       # "Broken" has no choice yet
    assert any("Broken" in x for x in by[world["s2"]]["reasons"])
    assert "Broken" in p["unmapped_values"]["state"]
    # The reference a rack unit makes to srv-d (as a custom Server) would break: blocked.
    assert by[world["s4"]]["status"] == "blocked" and any("refers to it" in x for x in by[world["s4"]]["reasons"])
    assert set(p["counts"]) == {world["w1"], world["w2"]}
    # An explicit decision: "Broken" → faulty; srv-b is now ready.
    m = tm.change(db, m, ACTOR, {"attributes": {"state": {"action": "copy", "to": "condition",
                                                          "values": {"OK": "good", "Broken": "faulty"}}}})
    p = tm.preview(db, m, ALL)
    db.rollback()
    assert {r["uid"]: r for r in p["records"]}[world["s2"]]["status"] == "ready"
    db.close()


def test_incompatible_required_fields_block_until_given_a_default(world):
    db = SessionLocal()
    target = db.get(Schema, world["target_server"])
    original = [dict(a) for a in target.attributes]
    target.attributes = [{**a, "required": True} if a.get("key") == "hypervisor" else a for a in target.attributes]
    flag_modified(target, "attributes")
    db.commit()
    try:
        m = _plan(db, world, workspaces=[world["w1"]])
        m = tm.change(db, m, ACTOR, {"attributes": {"state": {"action": "copy", "to": "condition",
                                                              "values": {"OK": "good", "Broken": "faulty"}}}})
        p = tm.preview(db, m, ALL)
        db.rollback()
        assert all(r["status"] == "blocked" and any("Hypervisor is required" in x for x in r["reasons"])
                   for r in p["records"])
        m = tm.change(db, m, ACTOR, {"defaults": {"hypervisor": "unknown"}})
        p = tm.preview(db, m, ALL)
        db.rollback()
        assert all(r["status"] == "ready" for r in p["records"])
    finally:
        target = db.get(Schema, world["target_server"])
        target.attributes = original
        flag_modified(target, "attributes")
        db.commit()
        db.close()


def test_restricted_records_are_not_moved_by_someone_who_may_not_see_them(world):
    db = SessionLocal()
    m = _plan(db, world, workspaces=[world["w2"]])
    p = tm.preview(db, m, lambda ws: visibility.Grants(()))
    db.rollback()
    by = {r["uid"]: r for r in p["records"]}
    assert by[world["s3"]]["status"] == "hidden"
    p = tm.preview(db, m, ALL)
    db.rollback()
    assert {r["uid"]: r for r in p["records"]}[world["s3"]]["status"] == "ready"
    db.close()


# --------------------------------------------------------------------------- apply, rebuild, repeat, verify, revert

def test_assets_move_in_place_in_their_own_workspaces_and_a_rebuild_keeps_it(world):
    from app.ledger import engine
    db = SessionLocal()
    m = _plan(db, world)
    m = tm.change(db, m, ACTOR, {"attributes": {"state": {"action": "copy", "to": "condition",
                                                          "values": {"OK": "good", "Broken": "faulty"}}}})
    s1_before = db.get(Asset, world["s1"])
    key1 = s1_before.key
    p = tm.preview(db, m, ALL)
    db.rollback()
    res = tm.apply(db, m, p["token"], ACTOR, ALL, batch_size=1)
    assert res["applied"] == 3 and res["failed"] == 0 and res["status"] == "partially_applied"   # srv-d stays
    db.expire_all()
    s1 = db.get(Asset, world["s1"])
    assert s1.schema_uid == world["target_server"] and s1.key == key1 and s1.workspace_id == world["w1"]
    assert s1.attributes["condition"] == "Good" and "legacy_code" not in s1.attributes and "state" not in s1.attributes
    assert db.get(Asset, world["s3"]).workspace_id == world["w2"]
    assert db.get(Asset, world["s3"]).attributes.get("classification") == "restricted:security"   # kept as it was
    assert db.get(Asset, world["s4"]).schema_uid == world["custom"]          # blocked by the rack unit's reference
    item = db.scalar(select(TypeMigrationItem).where(TypeMigrationItem.migration_id == m.id,
                                                     TypeMigrationItem.record_uid == world["s1"]))
    assert item.provenance == {"legacy_code": "X-1", "cores": "32"}
    assert item.before["attributes"]["state"] == "OK"
    # A rebuild of the ledger (the projection from the statements) puts it on the same type, by its identity.
    engine.project_subject(db, world["s1"], "test rebuild", emit=False)
    db.flush()
    assert db.get(Asset, world["s1"]).schema_uid == world["target_server"]
    db.rollback()
    # Verify: same uid and key, comment, file, relation, map position and placement all there.
    report = tm.verify(db, m, ACTOR)
    assert report["exceptions"] == [] and report["records"]["applied"] == 3
    assert not report["deprecation"]["possible"]                            # srv-d still uses the type
    with pytest.raises(tm.MigrationError, match="cannot be deprecated"):
        tm.verify(db, m, ACTOR, deprecate=True)
    # Applying again changes nothing: no record is moved twice.
    p = tm.preview(db, m, ALL)
    db.rollback()
    assert tm.apply(db, m, p["token"], ACTOR, ALL)["applied"] == 0
    assert db.scalar(select(func.count()).where(AssetHistory.asset_uid == world["s1"],
                                                AssetHistory.type == "type_migrated")) == 1
    assert db.scalar(select(func.count()).where(TypeMigrationItem.migration_id == m.id)) == 3
    # The log is the audit trail: who, when, what.
    assert [e["event"] for e in m.log][:2] == ["created", "mapping_changed"] and any(e["event"] == "batch" for e in m.log)
    # Revert puts them back, through the ledger too.
    out = tm.revert(db, m, ACTOR)
    assert out["reverted"] == 3
    db.expire_all()
    s1 = db.get(Asset, world["s1"])
    assert s1.schema_uid == world["custom"] and s1.attributes.get("state") == "OK" and s1.attributes.get("legacy_code") == "X-1"
    engine.project_subject(db, world["s1"], "test rebuild", emit=False)
    db.flush()
    assert db.get(Asset, world["s1"]).schema_uid == world["custom"]
    db.rollback()
    db.close()


def test_a_record_that_fails_is_reported_and_the_rest_go_on_then_retry(world, monkeypatch):
    db = SessionLocal()
    m = _plan(db, world, workspaces=[world["w1"]])
    m = tm.change(db, m, ACTOR, {"attributes": {"state": {"action": "copy", "to": "condition",
                                                          "values": {"OK": "good", "Broken": "faulty"}}}})
    real = tm._apply_one

    def flaky(db_, m_, e, actor):
        if e.label["uid"] == world["s2"]:
            raise RuntimeError("disk on fire")
        return real(db_, m_, e, actor)
    monkeypatch.setattr(tm, "_apply_one", flaky)
    p = tm.preview(db, m, ALL)
    db.rollback()
    res = tm.apply(db, m, p["token"], ACTOR, ALL)
    assert res == {"applied": 1, "failed": 1, "left": 1, "status": "partially_applied"}
    assert db.get(Asset, world["s2"]).schema_uid == world["custom"]
    monkeypatch.setattr(tm, "_apply_one", real)
    p = tm.preview(db, m, ALL)
    db.rollback()
    res = tm.apply(db, m, p["token"], ACTOR, ALL)
    assert res["applied"] == 1 and res["failed"] == 0 and res["status"] == "applied"
    assert db.scalar(select(func.count()).where(TypeMigrationItem.migration_id == m.id)) == 2
    assert tm.verify(db, m, ACTOR)["exceptions"] == []
    tm.revert(db, m, ACTOR)
    db.close()


def test_a_stale_preview_is_refused(world):
    db = SessionLocal()
    m = _plan(db, world, workspaces=[world["w1"]])
    p = tm.preview(db, m, ALL)
    db.rollback()
    tm.change(db, m, ACTOR, {"attributes": {"cores": {"action": "review"}}})
    with pytest.raises(tm.MigrationError, match="preview again"):
        tm.apply(db, m, p["token"], ACTOR, ALL)
    db.close()


def test_held_for_review_and_left_out_records_stay(world):
    db = SessionLocal()
    m = _plan(db, world, workspaces=[world["w1"]])
    m = tm.change(db, m, ACTOR, {"attributes": {"cores": {"action": "review"},
                                                "state": {"action": "copy", "to": "condition",
                                                          "values": {"OK": "good", "Broken": "faulty"}}},
                                 "records": {world["s2"]: "skip"}})
    p = tm.preview(db, m, ALL)
    db.rollback()
    by = {r["uid"]: r for r in p["records"]}
    assert by[world["s1"]]["status"] == "review" and by[world["s2"]]["status"] == "review"
    db.close()


def test_the_old_type_is_deprecated_only_when_nothing_depends_on_it_and_never_deleted(world):
    db = SessionLocal()
    m = tm.create(db, ACTOR, "documents", world["note"], {"package_id": "core-facility", "type": "Procedure"},
                  [world["w1"]], False, "field notes are procedures")
    p = tm.preview(db, m, ALL)
    db.rollback()
    assert tm.apply(db, m, p["token"], ACTOR, ALL)["status"] == "applied"
    report = tm.verify(db, m, ACTOR, deprecate=True)
    assert report["deprecation"]["deprecated"] is True
    note = db.get(Schema, world["note"])
    assert note is not None and note.metadata_json["deprecated"]["replaced_by"]["type"] == "Procedure"
    # The document kept both revisions; the current one carries the mapped fields, the old one too.
    doc = db.get(Document, world["doc"])
    assert doc.document_type_uid == kind_uid(world["w1"], "document_types", "Procedure")
    revs = list(db.scalars(select(DocumentRevision).where(DocumentRevision.document_uid == doc.uid)))
    assert len(revs) == 2 and all("ref_no" not in r.attributes for r in revs)
    item = db.scalar(select(TypeMigrationItem).where(TypeMigrationItem.migration_id == m.id))
    assert item.before["revisions"][f"{doc.uid}-r1"] == {"ref_no": "R-1"}
    assert item.provenance["ref_no"] == "R-2"
    assert m.status == "verified"
    tm.revert(db, m, ACTOR)
    db.expire_all()
    assert db.get(Document, world["doc"]).document_type_uid == world["note"]
    assert db.get(DocumentRevision, f"{doc.uid}-r1").attributes == {"ref_no": "R-1"}
    note = db.get(Schema, world["note"])
    meta = dict(note.metadata_json)
    meta.pop("deprecated", None)
    note.metadata_json = meta
    flag_modified(note, "metadata_json")
    db.commit()
    db.close()


def test_tickets_need_a_state_of_the_target_workflow(world):
    db = SessionLocal()
    m = tm.create(db, ACTOR, "tickets", world["fault"], {"package_id": "core-facility", "type": "Bug"},
                  [world["w1"]], False, "faults are bugs")
    assert m.mapping["states"] == {"triage": None}
    p = tm.preview(db, m, ALL)
    db.rollback()
    assert p["records"][0]["status"] == "blocked" and "triage" in p["records"][0]["reasons"][0]
    m = tm.change(db, m, ACTOR, {"states": {"triage": "new"}, "attributes": {"symptom": {"action": "provenance"}}})
    p = tm.preview(db, m, ALL)
    db.rollback()
    assert p["records"][0]["status"] == "ready" and p["records"][0]["state"] == {"before": "triage", "after": "new"}
    assert tm.apply(db, m, p["token"], ACTOR, ALL)["status"] == "applied"
    t = db.get(Issue, world["ticket"])
    assert t.schema_uid == kind_uid(world["w1"], "ticket_types", "Bug") and t.state == "new"
    hist = {(h.type, h.field) for h in db.scalars(select(IssueHistory).where(IssueHistory.issue_uid == t.uid))}
    assert ("type_migrated", "type") in hist and ("transition", "state") in hist
    tm.revert(db, m, ACTOR)
    db.expire_all()
    assert db.get(Issue, world["ticket"]).state == "triage"
    db.close()


def test_the_ledger_follows_the_type_identity_not_its_name(world):
    """Two types named Server are visible to w1 (the catalogue's custom one and the package's): a type
    statement naming the identity puts the record on exactly that one."""
    from app.ledger import service as ledger
    db = SessionLocal()
    s4 = db.get(Asset, world["s4"])
    target = db.get(Schema, world["target_server"])
    ledger.retype_to(db, world["w2"], ACTOR, [s4.uid], target, reason="test")
    assert db.get(Asset, s4.uid).schema_uid == target.uid
    ledger.retype_to(db, world["w2"], ACTOR, [s4.uid], db.get(Schema, world["custom"]), reason="test back")
    assert db.get(Asset, s4.uid).schema_uid == world["custom"]
    db.rollback()
    db.close()


# --------------------------------------------------------------------------- who may, and the authoring path

def test_only_instance_administrators_may(world):
    client = TestClient(app)
    plain = User(id="tm-plain", email="tm-plain@argus.test", is_admin=False)
    admin = User(id="tm-admin", email=ACTOR, is_admin=True)
    try:
        app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=plain)
        assert client.get("/v1/admin/type-migrations").status_code == 403
        assert client.post("/v1/admin/type-migrations", json={"source_schema_uid": world["custom"], "target": SERVER,
                                                              "reason": "x"}).status_code == 403
        assert client.post("/v1/admin/type-proposals", json={"schema_uid": world["custom"], "package_id": "it"}).status_code == 403
        app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
        r = client.post("/v1/admin/type-migrations", json={"source_schema_uid": world["custom"], "target": SERVER,
                                                           "workspaces": [world["w1"]], "reason": "api"})
        assert r.status_code == 201, r.text
        mid = r.json()["id"]
        p = client.post(f"/v1/admin/type-migrations/{mid}/preview")
        assert p.status_code == 200 and p.json()["token"]
        assert client.post(f"/v1/admin/type-migrations/{mid}/apply", json={"token": "stale"}).status_code == 409
        app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=plain)
        assert client.post(f"/v1/admin/type-migrations/{mid}/apply", json={"token": p.json()["token"]}).status_code == 403
        assert client.post(f"/v1/admin/type-migrations/{mid}/revert", json={}).status_code == 403
    finally:
        app.dependency_overrides.pop(get_identity, None)


def test_a_custom_type_proposed_as_package_yaml_is_checked_and_nothing_is_written(world, tmp_path):
    import yaml
    from app.packages.loader import packages_dir
    from app.services import type_proposal
    db = SessionLocal()
    shipped = (packages_dir() / "it" / "object_types.yaml").read_bytes()
    clash = type_proposal.propose(db, world["custom"], "it")
    assert not clash["ok"] and any("it already declares 'Server'" in p for p in clash["problems"])
    ok = type_proposal.propose(db, world["custom"], "it", name="Legacy Server")
    assert ok["ok"], ok["problems"]
    entry = yaml.safe_load(ok["yaml"])["object_types"]["types"][0]
    assert entry["name"] == "Legacy Server" and entry["parent"] == "IT Equipment"
    assert {a["key"] for a in entry["attributes"]} == {"state", "legacy_code", "cores"}
    assert [o["id"] for o in entry["attributes"][0]["options"]] == ["ok", "broken"]
    assert ok["next_version"] != ok["current_version"]
    # Bad keys and option ids are named.
    bad = db.get(Schema, world["custom"])
    saved = [dict(a) for a in bad.attributes]
    bad.attributes = saved + [{"key": "Bad Key", "name": "x", "type": "enumeration", "options": [{"id": "A B", "value": "a"}]}]
    flag_modified(bad, "attributes")
    db.flush()
    worse = type_proposal.propose(db, world["custom"], "it", name="Legacy Server")
    assert not worse["ok"] and any("Bad Key" in p for p in worse["problems"]) and any("'A B'" in p for p in worse["problems"])
    db.rollback()
    assert (packages_dir() / "it" / "object_types.yaml").read_bytes() == shipped
    db.close()
