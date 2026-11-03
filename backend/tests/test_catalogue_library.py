"""The library of the pinned sources (app/catalogue/library.py, docs/netbox-whole-library.md N2b): searched for a
picker — installed models first, then the library's — and a model installed the first time someone picks it,
with its vendor; a same-named vendor record linked, a look-alike model never overwritten; a partly installed
collection never counts as installed."""
import secrets
import uuid
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import OidcIdentity, get_identity
from app.catalogue import install as inst
from app.catalogue import library
from app.db import SessionLocal
from app.main import app
from app.models.asset import Asset
from app.models.catalogue_entry import CatalogueEntry, CatalogueInstallation
from app.models.package import WorkspacePackage
from app.models.user import User
from app.models.workspace import Workspace
from app.services import catalogue_mapping as cm
from app.services.asset_types import ensure_asset_types

REQ = {"packages": {"core-objects": ">=2.1,<3", "it": ">=1.1,<2"}}


def _collection(root: Path, cid: str, origin=None, domain="it", vendors=None, models=None) -> None:
    d = root / cid
    d.mkdir(parents=True, exist_ok=True)
    contents = []
    for name, items in (("vendors", vendors), ("models", models)):
        if items is not None:
            (d / f"{name}.yaml").write_text(yaml.safe_dump({name: items}, sort_keys=False))
            contents.append(f"{name}.yaml")
    (d / "collection.yaml").write_text(yaml.safe_dump({
        "id": cid, "version": "0.1.0", "name": cid, "domain": domain, "owner": "o", "license": "CC0-1.0",
        **({"origin": origin} if origin else {}), "contents": contents,
        "requires": {**REQ, **({"collections": {"vendors": ">=0.2,<1"}} if cid != "vendors" else {})}}))


@pytest.fixture()
def w(tmp_path, monkeypatch):
    t = secrets.token_hex(3)
    cat, it, other = f"lcat-{t}", f"lit-{t}", f"lother-{t}"
    db = SessionLocal()
    for ws in (cat, it, other):
        db.add(Workspace(id=ws, name=ws))
    db.flush()
    for ws in (cat, it, other):
        ensure_asset_types(db, ws)
    for pid, version in (("core-objects", "2.1.0"), ("it", "1.1.0")):
        db.add(WorkspacePackage(workspace_id=cat, package_id=pid, version=version, checksum="x"))
    db.add(WorkspacePackage(workspace_id=it, package_id="it", version="1.1.0", checksum="x"))
    admin = User(id=str(uuid.uuid4()), email=f"admin-{t}@argus.test", is_admin=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    monkeypatch.setattr(inst, "catalogue_workspace", lambda db: cat)
    root = tmp_path / "tree"
    _collection(root, "vendors", domain="catalogue", vendors=[{"id": "moxa", "name": "Moxa", "aliases": ["Moxa Inc."]}])
    _collection(root, "it-devices", origin="netbox",
                vendors=[{"id": "cisco", "name": "Cisco", "sources": [{"kind": "netbox-devicetype-library",
                                                                      "ref": "device-types/Cisco", "revision": "abc"}]}],
                models=[{"id": "cisco/c9200-24t", "vendor": "cisco", "model_code": "C9200-24T", "name": "Cisco C9200-24T",
                         "part_number": "C9200-24T-E", "specifications": {"network_ports": 28, "rack_units": 1}},
                        {"id": "cisco/c9200-48t", "vendor": "cisco", "model_code": "C9200-48T", "name": "Cisco C9200-48T"},
                        {"id": "moxa/nport-5450", "vendor": "moxa", "model_code": "NPort 5450", "name": "Moxa NPort 5450"}])
    lib = library.index(root)
    model_schema, vendor_schema = cm.catalogue_types(db, cat)
    yield {"db": db, "cat": cat, "it": it, "other": other, "admin": admin, "lib": lib, "model": model_schema,
           "vendor": vendor_schema}
    app.dependency_overrides.pop(get_identity, None)
    db.rollback()
    db.execute(CatalogueEntry.__table__.delete().where(CatalogueEntry.workspace_id == cat))
    db.execute(CatalogueInstallation.__table__.delete().where(CatalogueInstallation.workspace_id == cat))
    db.commit()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    for ws in (cat, it, other):
        db.delete(db.get(Workspace, ws))
    db.delete(db.get(User, admin.id))
    db.commit()
    db.close()


def record(w, schema, name, **attrs) -> Asset:
    from app.ledger import service as ledger
    from app.services import asset_keys
    uid = str(uuid.uuid4())
    ledger.create_record(w["db"], w["cat"], "t", uid=uid, schema_uid=schema.uid,
                         key=asset_keys.allocate(w["db"], w["cat"], schema), name=name, type_name=schema.name,
                         attributes=attrs, is_global=True)
    w["db"].commit()
    return w["db"].get(Asset, uid)


def test_the_index_is_small_and_search_ranks_installed_then_library(w):
    db, lib = w["db"], w["lib"]
    assert {i.catalogue_id for i in lib.items} == {"cisco/c9200-24t", "cisco/c9200-48t", "moxa/nport-5450"}
    assert lib.items[0].vendor_name in ("Cisco", "Moxa")
    record(w, w["model"], "Dell OptiPlex XE2", model_code="OptiPlex XE2", vendor="Dell")
    exact = library.search(db, "C9200-24T", lib=lib)
    assert [x["catalogue_id"] for x in exact["library"]] == ["cisco/c9200-24t", ]     # the code exactly
    family = library.search(db, "c9200", lib=lib)
    assert [x["catalogue_id"] for x in family["library"]] == ["cisco/c9200-24t", "cisco/c9200-48t"]
    assert family["library"][0]["vendor"] == "Cisco" and family["library"][0]["source"] == "netbox"
    assert library.search(db, "C9200-24T-E", lib=lib)["library"][0]["catalogue_id"] == "cisco/c9200-24t"  # part number
    record(w, w["model"], "Our NPort 5450", model_code="NPort-5450", vendor="Moxa")
    twice = library.search(db, "nport 5450", lib=lib)
    assert [x["name"] for x in twice["installed"]] == ["Our NPort 5450"] and twice["library"] == []   # not offered twice
    mine = library.search(db, "optiplex", lib=lib)
    assert [x["name"] for x in mine["installed"]] == ["Dell OptiPlex XE2"] and mine["library"] == []
    assert library.search(db, "x", lib=lib) == {"installed": [], "library": [], "more": False}    # too short


def test_a_workspace_is_offered_its_domains_unless_it_asks_for_every_model(w):
    db, lib = w["db"], w["lib"]
    assert len(library.search(db, "c9200", workspace_id=w["it"], lib=lib)["library"]) == 2
    assert library.search(db, "c9200", workspace_id=w["other"], lib=lib)["library"] == []       # no IT package
    assert len(library.search(db, "c9200", workspace_id=w["other"], every=True, lib=lib)["library"]) == 2


def test_picking_a_library_model_installs_it_and_its_vendor_once(w):
    db, lib = w["db"], w["lib"]
    got = library.install_one(db, "cisco/c9200-24t", actor="u", lib=lib)
    db.commit()
    model = db.get(Asset, got["uid"])
    assert got["installed"] and model.workspace_id == w["cat"] and model.is_global
    assert model.attributes["model_code"] == "C9200-24T"
    # The workspace here has no core-objects 2.3 hardware fields: part number and specifications stay stated by
    # the collection, shown on the model's page.
    rows = {r.catalogue_id: r for r in db.scalars(select(CatalogueEntry).where(CatalogueEntry.workspace_id == w["cat"]))}
    assert set(rows) == {"cisco", "cisco/c9200-24t"}                                      # the vendor came with it
    assert rows["cisco/c9200-24t"].stated.get("model_code") == "C9200-24T"
    assert model.attributes["vendor_ref"] == rows["cisco"].record_uid
    assert inst.installed(db, w["cat"]) == {}                                             # partly: not installed
    partial = db.scalars(select(CatalogueInstallation).where(CatalogueInstallation.workspace_id == w["cat"])).all()
    assert all(p.result["partial"] for p in partial) and {p.collection_id for p in partial} == {"it-devices"}
    again = library.install_one(db, "cisco/c9200-24t", actor="u", lib=lib)
    assert again == {**got, "installed": False}
    found = library.search(db, "C9200-24T", lib=lib)
    assert [x["uid"] for x in found["installed"]] == [got["uid"]] and found["library"] == []   # installed now
    other = library.install_one(db, "cisco/c9200-48t", actor="u", lib=lib)
    db.commit()
    assert db.get(Asset, other["uid"]).attributes["vendor_ref"] == rows["cisco"].record_uid   # the same Cisco


def test_a_vendor_record_by_the_same_name_is_linked_and_a_look_alike_model_is_never_overwritten(w):
    db, lib = w["db"], w["lib"]
    moxa = record(w, w["vendor"], "Moxa Inc.", website="https://moxa.example")
    got = library.install_one(db, "moxa/nport-5450", actor="u", lib=lib)
    db.commit()
    assert db.get(Asset, got["uid"]).attributes["vendor_ref"] == moxa.uid
    db.expire_all()
    assert db.get(Asset, moxa.uid).name == "Moxa Inc."                                    # its own values kept
    cisco = record(w, w["vendor"], "Cisco")
    mine = record(w, w["model"], "Our C9200-48T", model_code="C9200-48T", vendor="Cisco", vendor_ref=cisco.uid)
    with pytest.raises(library.LibraryProblem, match="choose it instead") as e:
        library.install_one(db, "cisco/c9200-48t", actor="u", lib=lib)
    assert e.value.candidate["uid"] == mine.uid
    db.rollback()


def test_the_api_searches_and_installs_for_whoever_may_create_records(w, monkeypatch):
    monkeypatch.setattr(library, "index", lambda root=None: w["lib"])
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=w["admin"])
    client, h = TestClient(app), {"X-Workspace-Id": w["it"]}
    found = client.get("/v1/catalogue/collections/models/search", params={"q": "nport"}, headers=h).json()
    assert [x["catalogue_id"] for x in found["library"]] == ["moxa/nport-5450"]
    r = client.post("/v1/catalogue/collections/models/install-one", json={"catalogue_id": "moxa/nport-5450"}, headers=h)
    assert r.status_code == 200 and r.json()["installed"], r.text
    r = client.post("/v1/catalogue/collections/models/install-one", json={"catalogue_id": "nope/x"}, headers=h)
    assert r.status_code == 422


def test_a_model_made_by_hand_is_linked_to_the_same_one_in_the_sources(w, monkeypatch):
    """Found among the sources although it looks like it (that is the point), linked in place: its empty fields
    filled, its own values kept, its units untouched; refused when either side already has a link."""
    db, lib = w["db"], w["lib"]
    cisco = record(w, w["vendor"], "Cisco")
    mine = record(w, w["model"], "Our C9200-24T", model_code="C9200-24T", vendor="Cisco", vendor_ref=cisco.uid,
                  datasheet_url="https://intranet.example/c9200.pdf")
    assert library.search(db, "C9200-24T", lib=lib)["library"] == []                      # not offered twice
    found = library.search(db, "C9200-24T", lib=lib, sources_only=True)
    assert found["installed"] == [] and [x["catalogue_id"] for x in found["library"]] == ["cisco/c9200-24t"]

    monkeypatch.setattr(library, "index", lambda root=None: lib)
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=w["admin"])
    client, h = TestClient(app), {"X-Workspace-Id": w["it"]}
    r = client.post("/v1/catalogue/collections/models/link", json={"catalogue_id": "cisco/c9200-24t",
                                                                  "record_uid": mine.uid}, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["uid"] == mine.uid and "name" in out["kept"]
    assert {"part_number", "rack_units"} <= set(out["filled"])                        # its hardware, from NetBox
    db.expire_all()
    a = db.get(Asset, mine.uid)
    assert a.name == "Our C9200-24T" and a.attributes["datasheet_url"] == "https://intranet.example/c9200.pdf"
    row = inst.entries(db, w["cat"])["cisco/c9200-24t"]
    assert row.record_uid == mine.uid
    again = client.post("/v1/catalogue/collections/models/link", json={"catalogue_id": "cisco/c9200-48t",
                                                                      "record_uid": mine.uid}, headers=h)
    assert again.status_code == 422 and "already cisco/c9200-24t" in again.json()["detail"]["error"]
    other = record(w, w["model"], "Another C9200-24T", model_code="C9200-24T-X")
    taken = client.post("/v1/catalogue/collections/models/link", json={"catalogue_id": "cisco/c9200-24t",
                                                                      "record_uid": other.uid}, headers=h)
    assert taken.status_code == 409 and taken.json()["detail"]["candidate"]["uid"] == mine.uid


def test_linking_is_for_the_catalogues_maintainers(w, monkeypatch):
    monkeypatch.setattr(library, "index", lambda root=None: w["lib"])
    plain = User(id=str(uuid.uuid4()), email=f"plain-{secrets.token_hex(3)}@argus.test", is_admin=False)
    w["db"].add(plain)
    w["db"].commit()
    w["db"].refresh(plain)
    w["db"].expunge(plain)
    mine = record(w, w["model"], "Our C9200-48T", model_code="C9200-48T")
    try:
        app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=plain)
        r = TestClient(app).post("/v1/catalogue/collections/models/link",
                                 json={"catalogue_id": "cisco/c9200-48t", "record_uid": mine.uid},
                                 headers={"X-Workspace-Id": w["it"]})
        assert r.status_code == 403
    finally:
        w["db"].delete(w["db"].get(User, plain.id))
        w["db"].commit()
