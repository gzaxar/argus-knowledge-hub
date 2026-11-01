"""The system catalogue (app/catalogue/system.py, docs/system-catalogue.md): one workspace designated, found by
the setting rather than a guess, holding Vendors and Product Models only, and protected from deletion,
transfer, bundle export and hanging from another workspace."""
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import OidcIdentity, get_identity
from app.catalogue import system
from app.catalogue.install import catalogue_workspace
from app.db import SessionLocal
from app.main import app
from app.models.asset import Asset
from app.models.schema import Schema
from app.models.user import User
from app.models.workspace import Workspace
from app.packages import install as packages
from app.services import catalogue_mapping as cm
from app.services.asset_types import ensure_asset_types


@pytest.fixture()
def w():
    """A catalogue workspace of its own, designated for the test (the installation's is set aside and put back)."""
    t = secrets.token_hex(3)
    cat, unit_ws = f"syscat-{t}", f"sysunits-{t}"
    db = SessionLocal()
    before = system.designated(db)
    if before:
        db.get(Workspace, before).role = None
        db.flush()
    db.add_all([Workspace(id=cat, name="Catalogue"), Workspace(id=unit_ws, name="Units")])
    db.flush()
    ensure_asset_types(db, cat)
    ensure_asset_types(db, unit_ws)
    admin = User(id=str(uuid.uuid4()), email=f"admin-{t}@argus.test", is_admin=True)
    plain = User(id=str(uuid.uuid4()), email=f"user-{t}@argus.test", is_admin=False)
    db.add_all([admin, plain])
    db.commit()
    model_schema, vendor_schema = cm.catalogue_types(db, cat)
    other_type = db.scalar(select(Schema).where(Schema.workspace_id == cat, Schema.applies_to == "objects",
                                                Schema.name.notin_(("Product Model", "Vendor", "Asset"))).limit(1))
    for u in (admin, plain):
        db.refresh(u)
        db.expunge(u)
    yield {"db": db, "cat": cat, "units": unit_ws, "admin": admin, "plain": plain, "model": model_schema,
           "vendor": vendor_schema, "other": other_type, "before": before}
    db.rollback()
    for ws in (cat, unit_ws):
        row = db.get(Workspace, ws)
        if row is not None:
            row.role = None
    db.commit()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    for ws in (cat, unit_ws):
        row = db.get(Workspace, ws)
        if row is not None:
            db.delete(row)
    for u in (admin, plain):
        db.delete(db.get(User, u.id))
    db.commit()
    if before:
        db.get(Workspace, before).role = system.ROLE
        db.commit()
    db.close()


def as_user(user):
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=user)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_overrides():
    yield
    app.dependency_overrides.pop(get_identity, None)


def test_the_catalogue_is_the_designated_workspace_not_a_guess(w):
    db = w["db"]
    assert catalogue_workspace(db) is None            # holds the global Asset type? Not designated: not it.
    system.designate(db, w["cat"])
    db.commit()
    assert catalogue_workspace(db) == w["cat"] and system.is_catalogue(db, w["cat"])
    with pytest.raises(system.CatalogueProtected, match="already the installation's catalogue"):
        system.designate(db, w["units"])
    assert system.designate_if_none(db, w["units"]) is False


def test_a_workspace_holding_other_records_is_not_designated(w):
    db = w["db"]
    db.add(Asset(uid=str(uuid.uuid4()), workspace_id=w["units"], schema_uid=w["other"].uid,
                 key=f"U-{uuid.uuid4().hex[:6]}", name="a unit", type=w["other"].name, attributes={}))
    db.commit()
    with pytest.raises(system.CatalogueProtected, match="holds records that are not Vendors"):
        system.designate(db, w["units"])
    assert system.designate_if_none(db, w["units"]) is False


def test_the_catalogue_holds_vendors_and_product_models_only(w):
    db = w["db"]
    system.designate(db, w["cat"])
    db.commit()
    client = as_user(w["admin"])
    h = {"X-Workspace-Id": w["cat"]}
    ok = client.post("/v1/assets", headers=h, json={"uid": str(uuid.uuid4()), "schema_uid": w["vendor"].uid,
                                                     "name": "Moxa", "attributes": {}})
    assert ok.status_code == 201, ok.text
    refused = client.post("/v1/assets", headers=h, json={"uid": str(uuid.uuid4()), "schema_uid": w["other"].uid,
                                                          "name": "a unit", "attributes": {}})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "catalogue_workspace"
    # Whatever writes it — an import, a script — the flush refuses it too.
    db.add(Asset(uid=str(uuid.uuid4()), workspace_id=w["cat"], schema_uid=w["other"].uid,
                 key=f"X-{uuid.uuid4().hex[:6]}", name="smuggled", type=w["other"].name, attributes={}))
    with pytest.raises(system.CatalogueProtected, match="Vendors and Product Models only"):
        db.flush()
    db.rollback()


def test_the_catalogue_is_not_deleted_transferred_exported_or_hung(w):
    db = w["db"]
    system.designate(db, w["cat"])
    db.commit()
    client = as_user(w["admin"])
    r = client.delete(f"/v1/workspaces/{w['cat']}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "catalogue_workspace"
    r = client.post("/v1/admin/bundles/exports", json={"workspace_id": w["cat"]})
    assert r.status_code == 422 and "bundle" in r.json()["detail"]["error"]
    r = client.post("/v1/transfers", headers={"X-Workspace-Id": w["units"]},
                    json={"target_workspace_id": w["cat"], "mode": "copy", "type_uids": [], "include_instances": False,
                          "asset_uids": [], "document_uids": [], "issue_uids": []})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "catalogue_workspace"
    with pytest.raises(packages.PackageProblem, match="cannot be made to hang"):
        packages.plan(db, w["cat"], ["core-objects"], catalogue_workspace_id=w["units"])
    db.rollback()
    assert db.get(Workspace, w["cat"]) is not None


def test_status_says_what_it_holds_and_what_depends_on_it_for_administrators(w):
    db = w["db"]
    system.designate(db, w["cat"])
    vendor = Asset(uid=str(uuid.uuid4()), workspace_id=w["cat"], schema_uid=w["vendor"].uid, key=f"V-{uuid.uuid4().hex[:6]}",
                   name="Moxa", type="Vendor", attributes={}, is_global=True)
    model = Asset(uid=str(uuid.uuid4()), workspace_id=w["cat"], schema_uid=w["model"].uid, key=f"M-{uuid.uuid4().hex[:6]}",
                  name="NPort 5450", type="Product Model", attributes={"vendor_ref": vendor.uid}, is_global=True)
    other = db.scalar(select(Schema).where(Schema.workspace_id == w["units"], Schema.applies_to == "objects",
                                           Schema.name.notin_(("Product Model", "Vendor", "Asset"))).limit(1))
    db.add_all([vendor, model])
    db.flush()
    db.add(Asset(uid=str(uuid.uuid4()), workspace_id=w["units"], schema_uid=other.uid, key=f"U-{uuid.uuid4().hex[:6]}",
                 name="serial server 1", type=other.name, attributes={"product_model": model.uid}))
    db.commit()
    s = system.status(db)
    assert s["designated"] == w["cat"] and s["records"] == {"Vendor": 1, "Product Model": 1}
    assert s["other_records"] == {} and s["not_shared"] == 0 and s["units"] == {w["units"]: 1}

    assert as_user(w["plain"]).get("/v1/admin/catalogue").status_code == 403
    r = as_user(w["admin"]).get("/v1/admin/catalogue")
    assert r.status_code == 200 and r.json()["designated"] == w["cat"]
    r = as_user(w["admin"]).post("/v1/admin/catalogue/designate", json={"workspace_id": w["units"]})
    assert r.status_code == 422 and "already" in r.json()["detail"]["error"]


def test_the_workspace_lists_say_which_is_the_catalogue(w):
    db = w["db"]
    system.designate(db, w["cat"])
    db.commit()
    mine = {x["id"]: x for x in as_user(w["admin"]).get("/v1/me/workspaces").json()}
    assert mine[w["cat"]]["role"] == "catalogue" and mine[w["units"]]["role"] is None


def test_maintainers_are_its_curators_and_owners_and_everyone_reads(w):
    from datetime import datetime, timezone

    from app.models.role import RoleBinding
    from app.services.roles import ensure_system_roles
    db = w["db"]
    system.designate(db, w["cat"])
    ensure_system_roles(db)
    db.commit()
    plain = w["plain"]
    assert system.may_maintain(db, w["admin"]) and not system.may_maintain(db, plain)
    reader = as_user(plain)
    assert reader.get("/v1/me").json()["catalogue_maintainer"] is False
    assert reader.get("/v1/catalogue/collections/models").status_code == 200        # everyone reads
    assert reader.post("/v1/catalogue/collections/preview", json={"collections": []}).status_code == 403
    assert reader.get("/v1/admin/catalogue").status_code == 403

    db.add(RoleBinding(workspace_id=w["cat"], subject_type="user", subject_id=plain.id, role_id="viewer",
                       created_at=datetime.now(timezone.utc)))
    db.commit()
    assert not system.may_maintain(db, plain)                                        # a viewer reads only
    db.add(RoleBinding(workspace_id=w["cat"], subject_type="user", subject_id=plain.id, role_id="curator",
                       created_at=datetime.now(timezone.utc)))
    db.commit()
    assert system.may_maintain(db, plain)
    curator = as_user(plain)
    assert curator.get("/v1/me").json()["catalogue_maintainer"] is True
    assert curator.get("/v1/admin/catalogue").status_code == 200
    r = curator.post("/v1/catalogue/collections/preview", json={"collections": []})
    assert r.status_code != 403, r.text
    assert curator.post("/v1/admin/catalogue/designate", json={"workspace_id": w["units"]}).status_code == 403


def test_a_workspace_is_offered_the_models_of_its_domains(w):
    from app.catalogue.loader import load
    from app.models.catalogue_entry import CatalogueEntry, CatalogueInstallation
    from app.models.package import WorkspacePackage
    db = w["db"]
    system.designate(db, w["cat"])

    def model(name):
        a = Asset(uid=str(uuid.uuid4()), workspace_id=w["cat"], schema_uid=w["model"].uid,
                  key=f"M-{uuid.uuid4().hex[:6]}", name=name, type="Product Model", attributes={}, is_global=True)
        db.add(a)
        db.flush()
        return a
    gauge, switch, old, local = model("PKR 251"), model("NPort 5450"), model("Old thing"), model("Made here")
    for cid, domains in (("vacuum", ["vacuum-cryo"]), ("it-devices", ["it"]), ("legacy", None)):
        db.add(CatalogueInstallation(workspace_id=w["cat"], collection_id=cid, version="0.1.0", checksum="x",
                                     result={}, installed_by="t", domains=domains))
    for rec, cid in ((gauge, "vacuum"), (switch, "it-devices"), (old, "legacy")):
        db.add(CatalogueEntry(catalogue_id=f"{cid}/{rec.name}", record_uid=rec.uid, workspace_id=w["cat"],
                              kind="model", collection_id=cid, collection_version="0.1.0", collection_checksum="x"))
    db.query(WorkspacePackage).filter(WorkspacePackage.workspace_id == w["units"]).delete()
    db.add(WorkspacePackage(workspace_id=w["units"], package_id="it", version="1.1.0", checksum="x"))
    db.commit()

    out = system.offered(db, w["units"])
    assert out["hidden"] == [gauge.uid]                      # vacuum is not its domain; IT, legacy, local are
    assert out["collections"]["legacy"]["offered"] is True
    r = as_user(w["admin"]).get("/v1/catalogue/collections/offered", headers={"X-Workspace-Id": w["units"]})
    assert r.status_code == 200 and r.json()["hidden"] == [gauge.uid]
    assert system.offered(db, w["cat"])["hidden"] == []      # the catalogue itself sees everything

    # A collection's domain may name several packages, or `catalogue` for every workspace.
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "motion"
        root.mkdir()
        (root / "collection.yaml").write_text(
            "id: motion\nversion: 0.1.0\nname: M\nowner: o\nlicense: CC0-1.0\n"
            "domain: [accelerator, optics-alignment]\ncontents: []\n")
        c = load(root)
        assert c.domains == ["accelerator", "optics-alignment"] and c.domain == "accelerator, optics-alignment"


def test_a_model_is_edited_from_any_workspace_by_a_maintainer_and_stray_records_are_named(w):
    from datetime import datetime, timezone

    from app.models.role import RoleBinding
    from app.services.roles import ensure_system_roles
    db = w["db"]
    stray = Asset(uid=str(uuid.uuid4()), workspace_id=w["cat"], schema_uid=w["other"].uid,
                  key=f"S-{uuid.uuid4().hex[:6]}", name="an area", type=w["other"].name, attributes={})
    db.add(stray)
    db.commit()                                    # made before the catalogue was designated
    db.get(Workspace, w["cat"]).role = system.ROLE
    ensure_system_roles(db)
    model = Asset(uid=str(uuid.uuid4()), workspace_id=w["cat"], schema_uid=w["model"].uid, key=f"M-{uuid.uuid4().hex[:6]}",
                  name="Hi Scroll 6", type="Product Model", attributes={}, is_global=True)
    db.add(model)
    db.commit()
    assert system.status(db)["other_record_list"] == [{"uid": stray.uid, "key": stray.key, "name": "an area",
                                                        "type": w["other"].name}]

    # From another workspace, with the catalogue's header: a reader may not, a curator may.
    plain = w["plain"]
    db.add(RoleBinding(workspace_id=w["units"], subject_type="user", subject_id=plain.id, role_id="curator",
                       created_at=datetime.now(timezone.utc)))
    db.commit()
    body = {"name": "HiScroll 6", "attributes": {}, "schema_uid": w["model"].uid, "is_global": True}
    client = as_user(plain)
    assert client.put(f"/v1/assets/{model.uid}", json=body, headers={"X-Workspace-Id": w["units"]}).status_code == 404
    assert client.put(f"/v1/assets/{model.uid}", json=body, headers={"X-Workspace-Id": w["cat"]}).status_code == 403
    db.add(RoleBinding(workspace_id=w["cat"], subject_type="user", subject_id=plain.id, role_id="curator",
                       created_at=datetime.now(timezone.utc)))
    db.commit()
    r = client.put(f"/v1/assets/{model.uid}", json=body, headers={"X-Workspace-Id": w["cat"]})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Asset, model.uid).name == "HiScroll 6"
