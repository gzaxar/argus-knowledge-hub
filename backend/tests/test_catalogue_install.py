"""Installing catalogue collections (app/catalogue/install.py, docs/catalogue-collections.md §3): new records
from a release; an existing record adopted in place, field by field; upgrades that change managed fields and
never overwrite a local one; corrections proposed back; retirement that keeps the record; transfers between
collections that keep the record; and the refusals — same version with other content, an older version, a
package missing — and the uniqueness the database itself enforces."""
import secrets
import uuid
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth import OidcIdentity, get_identity
from app.catalogue import install as inst
from app.catalogue import views
from app.catalogue.loader import load_tree
from app.db import SessionLocal
from app.ledger import service as ledger
from app.main import app
from app.models.asset import Asset
from app.models.asset_subresources import AssetLabel
from app.models.catalogue_entry import CatalogueEntry, CatalogueInstallation
from app.models.package import WorkspacePackage
from app.models.user import User
from app.models.workspace import Workspace
from app.services import catalogue_mapping as cm
from app.services.asset_types import ensure_asset_types

MOXA = {"id": "moxa", "name": "Moxa Inc.", "aliases": ["Moxa", "MOXA Technologies"], "website": "https://www.moxa.com"}
NPORT = {"id": "moxa/nport-5450", "vendor": "moxa", "model_code": "NPort 5450", "name": "Moxa NPort 5450",
         "device_class": "converter", "instance_type": "Serial Converter",
         "datasheet_url": "https://www.moxa.com/nport-5450.pdf", "specifications": {"serial_ports": 4}}


def write(root: Path, cid: str, version: str, vendors=None, models=None, moved=None) -> Path:
    d = root / cid
    d.mkdir(parents=True, exist_ok=True)
    content = {k: v for k, v in (("vendors", vendors), ("models", models), ("moved", moved)) if v is not None}
    (d / "entries.yaml").write_text(yaml.safe_dump(content, sort_keys=False))
    (d / "collection.yaml").write_text(yaml.safe_dump({
        "id": cid, "version": version, "name": cid.title(), "domain": "catalogue" if cid == "vendors" else "it",
        "owner": "INFN ARGUS", "license": "CC-BY-4.0", "contents": ["entries.yaml"],
        "requires": {"packages": {"core-objects": ">=2.1,<3", "it": ">=1.1,<2"},
                     "collections": {} if cid == "vendors" else {"vendors": ">=1.0,<2"}}}))
    return root


@pytest.fixture()
def w(tmp_path):
    t = secrets.token_hex(3)
    ws = f"cat-{t}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name="Catalogue"))
    db.flush()
    ensure_asset_types(db, ws)
    for pid, version in (("core-objects", "2.1.0"), ("it", "1.1.0")):
        db.add(WorkspacePackage(workspace_id=ws, package_id=pid, version=version, checksum="x"))
    admin = User(id=str(uuid.uuid4()), email=f"admin-{t}@argus.test", is_admin=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    model_schema, vendor_schema = cm.catalogue_types(db, ws)
    yield {"db": db, "ws": ws, "actor": admin.id, "admin": admin, "root": tmp_path, "model": model_schema,
           "vendor": vendor_schema}
    db.rollback()
    db.execute(CatalogueEntry.__table__.delete().where(CatalogueEntry.workspace_id == ws))
    db.execute(CatalogueInstallation.__table__.delete().where(CatalogueInstallation.workspace_id == ws))
    db.commit()
    db.close()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
    TestClient(app).delete(f"/v1/workspaces/{ws}")
    app.dependency_overrides.pop(get_identity, None)


def release(w, version="1.0.0", models=None, vendors=None, it_version=None, moved=None, **more):
    root = w["root"] / f"r{secrets.token_hex(3)}"
    write(root, "vendors", "1.0.0", vendors=vendors if vendors is not None else [MOXA])
    write(root, "it-network", it_version or version, models=models if models is not None else [NPORT], moved=moved)
    for cid, kw in more.items():
        write(root, cid, kw.pop("version", "1.0.0"), **kw)
    return load_tree(root)


def run(w, tree, collections=("it-network",), decisions=None, apply=True):
    fn = inst.install if apply else inst.preview
    out = fn(w["db"], w["ws"], list(collections), actor=w["actor"], decisions=decisions or {}, tree=tree)
    if apply:
        w["db"].commit()
    return out


def record(w, cid: str) -> Asset:
    row = w["db"].scalar(select(CatalogueEntry).where(CatalogueEntry.workspace_id == w["ws"],
                                                      CatalogueEntry.catalogue_id == cid))
    return w["db"].get(Asset, row.record_uid), row


def items(out) -> dict:
    return {i["catalogue_id"]: i for r in out["releases"] for i in r["items"]}


def existing(w, schema, name, **attrs) -> Asset:
    from app.services import asset_keys
    uid = str(uuid.uuid4())
    ledger.create_record(w["db"], w["ws"], w["actor"], uid=uid, schema_uid=schema.uid,
                         key=asset_keys.allocate(w["db"], w["ws"], schema), name=name, type_name=schema.name,
                         attributes=attrs, is_global=True)
    w["db"].commit()
    return w["db"].get(Asset, uid)


def test_a_fresh_install_creates_shared_records_and_says_so(w):
    tree = release(w)
    before = w["db"].scalar(select(Asset.uid).where(Asset.workspace_id == w["ws"]).limit(1))
    shown = run(w, tree, apply=False)
    assert shown["counts"] == {"add": 2} and shown["trial"] == "ok"
    assert shown["releases"][1]["not_stored"] == {"instance_type": 1, "specifications": 1}
    w["db"].rollback()
    assert w["db"].scalar(select(Asset.uid).where(Asset.workspace_id == w["ws"]).limit(1)) == before  # kept nothing

    out = run(w, tree)
    assert out["counts"] == {"add": 2}
    model, row = record(w, "moxa/nport-5450")
    vendor, _ = record(w, "moxa")
    assert model.is_global and model.name == "Moxa NPort 5450"
    assert model.attributes["vendor_ref"] == vendor.uid and model.attributes["vendor"] == "Moxa Inc."
    assert model.attributes["model_code"] == "NPort 5450" and model.attributes["device_class"] == "converter"
    assert set(row.managed_fields) == {"name", "vendor", "model_code", "device_class", "datasheet_url"}
    labels = {(l.type, l.value) for l in w["db"].scalars(select(AssetLabel).where(AssetLabel.asset_uid.in_(
        [model.uid, vendor.uid])))}
    assert ("catalogue_id", "moxa/nport-5450") in labels and ("alias", "MOXA Technologies") in labels
    assert [h.version for h in inst.history(w["db"], w["ws"])] == ["1.0.0", "1.0.0"]

    again = run(w, tree)                                                # the same release: nothing
    assert all(r["already_installed"] for r in again["releases"]) and again["counts"] == {}


def test_an_existing_record_is_adopted_in_place_field_by_field(w):
    moxa = existing(w, w["vendor"], "MOXA Technologies")
    nport = existing(w, w["model"], "NPort 5450", vendor="MOXA", vendor_ref=moxa.uid, model_code="NPORT-5450",
                     device_class="converter", datasheet_url="https://intranet.example/nport.pdf")
    tree = release(w)
    shown = run(w, tree, apply=False)
    found = items(shown)
    assert found["moxa"]["category"] == "link" and found["moxa"]["record_uid"] == moxa.uid
    assert found["moxa/nport-5450"]["category"] == "link" and found["moxa/nport-5450"]["record_uid"] == nport.uid
    assert set(shown["undecided"]) == {"moxa", "moxa/nport-5450"} and shown["trial"] is None
    with pytest.raises(inst.CatalogueProblem, match="need a decision"):
        run(w, tree)
    w["db"].rollback()

    decisions = {"moxa": {"action": "link", "fields": {"name": "local", "website": "managed"}},
                 "moxa/nport-5450": {"action": "link", "fields": {
                     "name": "managed", "model_code": "managed", "datasheet_url": "propose"}}}
    out = run(w, tree, decisions=decisions)
    assert out["counts"] == {"link": 2}
    model, row = record(w, "moxa/nport-5450")
    assert model.uid == nport.uid and row.adopted_by == w["actor"]          # the same record, adopted
    assert model.name == "Moxa NPort 5450" and model.attributes["model_code"] == "NPort 5450"
    assert model.attributes["datasheet_url"] == "https://intranet.example/nport.pdf"   # proposed back, kept
    assert row.corrections["datasheet_url"]["value"] == "https://intranet.example/nport.pdf"
    assert "datasheet_url" not in row.managed_fields and "vendor" in row.managed_fields
    vendor, vrow = record(w, "moxa")
    assert vendor.uid == moxa.uid and vendor.name == "MOXA Technologies" and "name" not in vrow.managed_fields


def test_an_upgrade_changes_managed_fields_and_never_a_local_one(w):
    run(w, release(w))
    model, row = record(w, "moxa/nport-5450")
    # Someone edits the datasheet link here; the release changes it and the name.
    ledger.edit_values(w["db"], w["ws"], w["actor"], model.uid, {"attr:datasheet_url": "https://local.example/x.pdf"})
    w["db"].commit()
    newer = {**NPORT, "name": "Moxa NPort 5450 serial device server", "datasheet_url": "https://www.moxa.com/v2.pdf",
             "firmware_version": "3.9"}
    out = run(w, release(w, "1.1.0", models=[newer]))
    item = items(out)["moxa/nport-5450"]
    assert item["category"] == "conflict"
    model, row = record(w, "moxa/nport-5450")
    assert model.name == "Moxa NPort 5450 serial device server"            # managed: written
    assert model.attributes["firmware_version"] == "3.9"                   # newly stated: managed, written
    assert model.attributes["datasheet_url"] == "https://local.example/x.pdf"  # edited here: kept
    assert row.conflicts["datasheet_url"]["release"] == "https://www.moxa.com/v2.pdf"
    assert row.collection_version == "1.1.0"
    from app.models.ledger import Decision
    reasons = set(w["db"].scalars(select(Decision.reason).where(Decision.subject_uid == model.uid)))
    assert "catalogue it-network 1.1.0" in reasons                          # the history says which release


def test_a_correction_proposed_back_closes_when_a_release_carries_it(w):
    nport = existing(w, w["model"], "NPort 5450", vendor="Moxa", model_code="NPort 5450", device_class="converter",
                     datasheet_url="https://right.example/nport.pdf")
    tree = release(w)
    fields = {f["field"]: "managed" for f in items(run(w, tree, apply=False))["moxa/nport-5450"]["fields"]}
    fields["datasheet_url"] = "propose"
    w["db"].rollback()
    run(w, tree, decisions={"moxa/nport-5450": {"action": "link", "fields": fields}})
    _, row = record(w, "moxa/nport-5450")
    assert "datasheet_url" in row.corrections
    run(w, release(w, "1.1.0", models=[{**NPORT, "datasheet_url": "https://right.example/nport.pdf"}]))
    model, row = record(w, "moxa/nport-5450")
    assert model.uid == nport.uid and row.corrections == {} and "datasheet_url" in row.managed_fields


def test_retiring_keeps_the_record_and_flags_its_units(w):
    run(w, release(w))
    model, _ = record(w, "moxa/nport-5450")
    w["db"].add(Asset(uid=str(uuid.uuid4()), workspace_id=w["ws"], schema_uid=w["model"].uid, key=f"U-{model.key}",
                      name="a unit", type="Product Model", attributes={"product_model": model.uid}))
    w["db"].commit()
    retired = {**NPORT, "retired": {"since": "1.1.0", "reason": "end of sale"}}
    item = items(run(w, release(w, "1.1.0", models=[retired])))["moxa/nport-5450"]
    assert item["category"] == "retire" and any("1 units" in n for n in item["notes"])
    model, row = record(w, "moxa/nport-5450")
    assert row.status == "retired" and model.record_status == "Active"     # never retired as a record


def test_a_transfer_moves_the_entry_and_keeps_the_record(w):
    run(w, release(w))
    model, _ = record(w, "moxa/nport-5450")
    tomb = [{"id": "moxa/nport-5450", "moved_to": "timing-control"}]
    moved = {**NPORT, "transferred_from": "it-network"}
    tree = release(w, "1.1.0", models=[], moved=tomb, **{"timing-control": {"models": [moved]}})
    # Only the old collection's release first: the entry waits, still in it.
    out = run(w, tree, collections=("it-network",))
    assert items(out)["moxa/nport-5450"]["category"] == "transfer"
    _, row = record(w, "moxa/nport-5450")
    assert row.status == "transferring" and row.collection_id == "it-network"
    out = run(w, tree, collections=("timing-control",))
    assert items(out)["moxa/nport-5450"]["category"] == "transfer"
    after, row = record(w, "moxa/nport-5450")
    assert after.uid == model.uid and row.collection_id == "timing-control" and row.status == "active"


def test_what_is_refused(w):
    run(w, release(w))
    with pytest.raises(inst.CatalogueProblem, match="other content"):
        run(w, release(w, models=[{**NPORT, "firmware_version": "4.0"}]))  # changed, same version
    w["db"].rollback()
    run(w, release(w, "1.2.0"))
    with pytest.raises(inst.CatalogueProblem, match="is older"):
        run(w, release(w, "1.1.0"))
    w["db"].rollback()
    w["db"].execute(WorkspacePackage.__table__.delete().where(WorkspacePackage.workspace_id == w["ws"],
                                                              WorkspacePackage.package_id == "it"))
    with pytest.raises(inst.CatalogueProblem, match="needs the package it"):
        run(w, release(w, "1.3.0"))
    w["db"].rollback()
    with pytest.raises(inst.CatalogueProblem, match="not valid"):
        run(w, release(w, "1.4.0", models=[{**NPORT, "model_code": ""}]))
    w["db"].rollback()


def test_the_database_holds_one_record_per_id_and_one_id_per_record(w):
    run(w, release(w))
    model, row = record(w, "moxa/nport-5450")
    vendor, _ = record(w, "moxa")
    db = w["db"]
    for twin in ({"catalogue_id": "moxa/nport-5450", "record_uid": vendor.uid},     # one id, two records
                 {"catalogue_id": "moxa/other", "record_uid": model.uid}):          # one record, two ids
        db.add(CatalogueEntry(workspace_id=w["ws"], kind="model", collection_id="it-network",
                              collection_version="1.0.0", collection_checksum="x", **twin))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_the_api_previews_and_installs_for_administrators(w, monkeypatch):
    tree = release(w)
    monkeypatch.setattr(inst, "catalogue_workspace", lambda db: w["ws"])
    monkeypatch.setattr("app.routers.catalogue_collections.load_tree", lambda **_: tree)
    monkeypatch.setattr(inst, "load_tree", lambda **_: tree)
    client = TestClient(app)
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=w["admin"])
    try:
        listed = client.get("/v1/catalogue/collections").json()
        assert {c["id"]: c["installed_version"] for c in listed["collections"]} == {"vendors": None, "it-network": None}
        shown = client.post("/v1/catalogue/collections/preview", json={"collections": ["it-network"]}).json()
        assert shown["counts"] == {"add": 2}
        done = client.post("/v1/catalogue/collections/install", json={"collections": ["it-network"]})
        assert done.status_code == 200, done.text
        entries = client.get("/v1/catalogue/collections/entries").json()
        assert [e["catalogue_id"] for e in entries] == ["moxa", "moxa/nport-5450"]
        bad = client.post("/v1/catalogue/collections/install", json={"collections": ["nothing"]})
        assert bad.status_code == 422 and "no collection 'nothing'" in bad.json()["detail"]["error"]
    finally:
        app.dependency_overrides.pop(get_identity, None)
    w["db"].expire_all()


def test_what_the_production_data_taught_the_matching(w):
    # Production models carry the code in the name ("TPG 366 control unit"): still a candidate, never a
    # silent second record. A `+` is a different product. An empty value here is simply filled.
    moxa = existing(w, w["vendor"], "Moxa")
    unit = existing(w, w["model"], "NPort 5450 serial server", vendor="Moxa", vendor_ref=moxa.uid,
                    device_class="converter")
    plus = {**NPORT, "id": "moxa/nport-5450-plus", "model_code": "NPort 5450+", "name": "Moxa NPort 5450+"}
    found = items(run(w, release(w, models=[NPORT, plus]), apply=False))
    assert found["moxa/nport-5450"]["category"] == "link" and found["moxa/nport-5450"]["record_uid"] == unit.uid
    assert found["moxa/nport-5450-plus"]["category"] == "add"
    actions = {f["field"]: f["action"] for f in found["moxa/nport-5450"]["fields"]}
    assert actions["model_code"] == "managed" and actions["datasheet_url"] == "managed"   # empty here: filled
    assert actions["name"] is None                                                         # differs: a person
    assert {f["field"]: f["action"] for f in found["moxa"]["fields"]}["website"] == "managed"


def test_a_models_page_says_where_each_value_comes_from(w):
    tree = release(w)
    run(w, tree)
    model, row = record(w, "moxa/nport-5450")
    ledger.edit_values(w["db"], w["ws"], w["actor"], model.uid, {"attr:datasheet_url": "https://local.example/x.pdf"})
    w["db"].commit()
    page = views.provenance(w["db"], model.uid, {w["ws"]}, tree=tree)
    source = {f["field"]: f["source"] for f in page["fields"]}
    assert source["name"] == "collection" and source["datasheet_url"] == "edited"
    assert source["firmware_version"] == "record"                         # not stated by the collection
    assert page["entry"]["catalogue_id"] == "moxa/nport-5450"
    assert page["stated_only"] == {"instance_type": "Serial Converter", "specifications": {"serial_ports": 4}}
    assert [r["version"] for r in page["releases"]] == ["1.0.0"]
    assert views.review_queue(w["db"], w["ws"])[0]["edited"] == ["datasheet_url"]

    # The person says what the edit is: proposed back to Git. Then back to the collection's value.
    views.decide_field(w["db"], w["ws"], w["actor"], "moxa/nport-5450", "datasheet_url", "propose")
    w["db"].commit()
    _, row = record(w, "moxa/nport-5450")
    assert "datasheet_url" in row.corrections and "datasheet_url" not in row.managed_fields
    views.decide_field(w["db"], w["ws"], w["actor"], "moxa/nport-5450", "datasheet_url", "managed")
    w["db"].commit()
    model, row = record(w, "moxa/nport-5450")
    assert model.attributes["datasheet_url"] == NPORT["datasheet_url"] and row.corrections == {}
    assert views.review_queue(w["db"], w["ws"]) == []
    with pytest.raises(inst.CatalogueProblem, match="states no part_number"):
        views.decide_field(w["db"], w["ws"], w["actor"], "moxa/nport-5450", "part_number", "local")


def test_browsing_the_catalogue(w):
    run(w, release(w))
    existing(w, w["model"], "Hand-made thing", vendor="Moxa", model_code="HM-1", device_class="io")
    found = views.browse(w["db"], w["ws"])
    by_name = {m["name"]: m for m in found["models"]}
    assert by_name["Moxa NPort 5450"]["status"] == "catalogue" and by_name["Moxa NPort 5450"]["collection"] == "it-network"
    assert by_name["Hand-made thing"]["status"] == "local"
    assert found["facets"]["status"] == {"catalogue": 1, "local": 1}
    only = views.browse(w["db"], w["ws"], q="nport", status="catalogue")
    assert [m["catalogue_id"] for m in only["models"]] == ["moxa/nport-5450"]


def test_export_then_install_with_the_manifest_adopts_merges_and_keeps_every_reference(w, monkeypatch, tmp_path):
    """S4: a workspace's records exported as candidates and a migration manifest; the candidates reviewed into
    the collections; installed with the manifest — every record adopted in place, the duplicate merged, and
    no reference lost."""
    from app.catalogue.export import export, manifest_decisions
    shipped = w["root"] / "shipped"
    write(shipped, "vendors", "1.0.0", vendors=[MOXA])
    write(shipped, "it-network", "1.0.0", models=[NPORT])
    monkeypatch.setenv("ARGUS_CATALOGUE_DIR", str(shipped))

    moxa = existing(w, w["vendor"], "MOXA Technologies")
    acme = existing(w, w["vendor"], "Acme GmbH")
    acme2 = existing(w, w["vendor"], "ACME")                              # the same company, spelt again
    nport = existing(w, w["model"], "NPort 5450 serial server", vendor="Moxa", vendor_ref=moxa.uid,
                     device_class="converter")
    widget = existing(w, w["model"], "Widget 9", vendor="Acme", vendor_ref=acme.uid, device_class="switch",
                      description="A widget.\nSold by: Shop S.r.l. (Mario)")
    widget2 = existing(w, w["model"], "WIDGET-9", vendor="ACME", vendor_ref=acme2.uid, device_class="switch")
    orphan = existing(w, w["model"], "Mystery box", device_class="io")
    from app.models.schema import Schema
    unit_type = w["db"].scalar(select(Schema).where(Schema.workspace_id == w["ws"], Schema.applies_to == "objects",
                                                    Schema.name.notin_(("Product Model", "Vendor"))).limit(1))
    for model, n in ((widget, 2), (widget2, 1), (nport, 1)):
        for _ in range(n):
            w["db"].add(Asset(uid=str(uuid.uuid4()), workspace_id=w["ws"], schema_uid=unit_type.uid,
                              key=f"U-{uuid.uuid4().hex[:8]}", name="unit", type=unit_type.name,
                              attributes={"product_model": model.uid}))
    w["db"].commit()

    out = tmp_path / "export"
    result = export(w["db"], w["ws"], out)
    assert result["problems"] == 0
    man = yaml.safe_load((out / f"migration-{w['ws']}.yaml").read_text())
    assert man["links"]["moxa"]["record_uid"] == moxa.uid                       # a shipped vendor, by alias
    # Its code is only inside its name: a possible match for a person, never linked or merged by the export.
    assert "moxa/nport-5450" not in man["links"] and nport.uid not in yaml.safe_dump(man["merge"])
    widget_id = next(cid for cid, l in man["links"].items() if l["record_uid"] == widget.uid)
    assert widget_id == "acme/widget-9" and [m["record_uid"] for m in man["merge"][widget_id]] == [widget2.uid]
    assert [m["record_uid"] for m in man["merge"]["acme"]] == [acme2.uid]
    assert man["references"][widget_id]["units"] == 3
    candidates = (out / "collections" / "it-network" / "models.yaml").read_text()
    assert "Sold by" not in candidates and "description" not in candidates   # never exported
    assert widget.uid not in candidates and "device_class: network switch" in candidates
    report = (out / "report.md").read_text()
    assert "Mystery box" in report and "no vendor" in report and "names the seller" in report
    assert "may be moxa/nport-5450 (its code is inside the name)" in report
    assert orphan.uid not in yaml.safe_dump(man["links"])

    # The reviewer merges the candidates into the collections (new versions), then installs with the manifest.
    vendors_new = yaml.safe_load((out / "collections" / "vendors" / "vendors.yaml").read_text())["vendors"]
    models_new = yaml.safe_load(candidates)["models"]
    write(shipped, "vendors", "1.1.0", vendors=[MOXA, *vendors_new])
    write(shipped, "it-network", "1.1.0", models=[NPORT, *models_new])
    decisions, merges, expected = manifest_decisions(man)
    # The person decides the possible match on the collections page: it is the same product.
    decisions["moxa/nport-5450"] = {"action": "link", "record_uid": nport.uid,
                                    "fields": {"name": "local", "datasheet_url": "managed"}}
    done = inst.install(w["db"], w["ws"], ["it-network"], actor=w["actor"], decisions=decisions, merges=merges,
                        expected=expected, tree=load_tree(shipped))
    w["db"].commit()
    assert done["counts"] == {"link": 4}                                        # nothing created
    model, row = record(w, widget_id)
    assert model.uid == widget.uid and row.adopted_by == w["actor"]
    assert model.attributes["device_class"] == "network switch"                  # the cleaned spelling, managed
    assert "Sold by" in model.attributes["description"]                          # the record keeps its own
    w["db"].expire_all()
    assert w["db"].get(Asset, widget2.uid).record_status == "Merged"
    assert w["db"].get(Asset, acme2.uid).record_status == "Merged"
    # A unit of the duplicate still names it, and the duplicate redirects to the survivor.
    assert w["db"].get(Asset, widget2.uid).merged_into_uid == widget.uid


def test_an_install_that_would_lose_references_keeps_nothing(w):
    tree = release(w)
    nport = existing(w, w["model"], "NPort 5450", vendor="Moxa", model_code="NPort 5450", device_class="converter")
    decisions = {"moxa/nport-5450": {"action": "link", "record_uid": nport.uid, "fields": {"name": "local"}}}
    with pytest.raises(inst.CatalogueProblem, match="references would be lost"):
        inst.install(w["db"], w["ws"], ["it-network"], actor=w["actor"], decisions=decisions, tree=tree,
                     expected={"moxa/nport-5450": {"units": 5, "relations": 0, "documents": 0}})
    w["db"].rollback()
    assert w["db"].scalar(select(CatalogueEntry).where(CatalogueEntry.workspace_id == w["ws"])) is None


def test_a_models_hardware_fills_the_product_model_fields(w):
    """core-objects 2.3: the part number, height, weight, airflow, draw, ports and every component become the
    model's fields (where its type has them); the specifications are still shown whole."""
    import json
    keys = {a.get("key") for a in w["model"].attributes or []}
    assert {"part_number", "components", "weight_kg"} <= keys, "the Product Model type has its hardware fields"
    hw = {**NPORT, "part_number": "NP5450-T", "notes": "See the [manual](https://moxa.example/m.pdf)",
          "specifications": {"rack_units": 1, "full_depth": False, "weight": {"value": 740, "unit": "g"},
                             "airflow": "passive", "maximum_draw_w": 12},
          "components": {"interfaces": [{"name": "eth0", "type": "100base-tx"}],
                         "console_server_ports": [{"name": f"P{i}", "type": "de-9"} for i in range(1, 5)]}}
    run(w, release(w, models=[hw]))
    model, row = record(w, "moxa/nport-5450")
    a = model.attributes
    assert a["part_number"] == "NP5450-T" and a["rack_units"] == 1 and a["full_depth"] is False
    assert a["weight_kg"] == 0.74 and a["airflow"] == "passive" and a["maximum_draw_w"] == 12
    assert a["port_summary"] == "1 × 100base-tx, 4 serial" and a["source_notes"].startswith("See the")
    assert json.loads(a["components"])["console_server_ports"][3] == {"name": "P4", "type": "de-9"}
    assert {"part_number", "components", "weight_kg"} <= set(row.managed_fields)
