"""Transfers carry indoors, with a reconciliation report first (docs/sites.md rule 5, services/indoor_transfer.py):
floors, plans with their files and fit, eligible placements; a move keeps uids so references hold; the report
says what would not resolve; a stray record moves out of the catalogue, Vendors do not."""
import os
import uuid

import pytest
from sqlalchemy import select

from app.models.indoor import FloorPlan, IndoorPlacement, PlaceLevel
from app.models.transfer_job import TransferJob
from app.models.workspace import Workspace
from app.services import indoor, indoor_transfer, sites, workspace_transfer
from tests.test_sites import _as, _png, _person, lab, make  # noqa: F401  (fixtures)


def _run(db, source, target, mode, assets):
    job = TransferJob(uid=str(uuid.uuid4()), workspace_id=source, target_workspace_id=target, mode=mode)
    db.add(job)
    db.commit()
    workspace_transfer.run_transfer(job.uid, source, target, mode, [], False, list(assets), [], [])
    db.expire_all()
    job = db.get(TransferJob, job.uid)
    assert job.status == "succeeded", job.error
    return job


@pytest.fixture()
def edificio(lab):
    """Like Edificio 2 in the catalogue: a global building in a workspace that is not LNF ('other'), with a
    ground floor, a plan placed on the map, a room inside, SPARC's pump on the plan, and records elsewhere that
    name the building."""
    db, ids, r = lab["db"], lab["ids"], lab["rec"]
    building = make(db, ids["other"], "Building", "Edificio 9")
    building.is_global = True
    room = make(db, ids["other"], "Area", "Room 4")
    room.is_global = True                          # in the catalogue, every record is global
    db.flush()
    indoor.place(db, room, place_uid=building.uid, actor="t")
    level = indoor.save_level(db, building, name="Ground floor", ordinal=0, actor="t")
    plan = indoor.add_plan(db, building, "ground.png", _png(), name="Ground floor", level=level, actor="t")
    indoor.georeference(db, plan, [{"x": 0, "y": 0, "longitude": 12.68, "latitude": 41.82},
                                   {"x": 100, "y": 80, "longitude": 12.681, "latitude": 41.8195}])
    indoor.place(db, r["sparc_pump"], place_uid=room.uid, plan_uid=plan.uid, x=10, y=10, actor="t")
    btf_note = make(db, ids["btf"], "Vacuum Pump", "BTF pump naming it", installed_in=building.uid)
    stranger_ws = f"{ids['other']}-x"
    db.add(Workspace(id=stranger_ws, name=stranger_ws))
    db.flush()
    from app.services import asset_types
    asset_types.ensure_asset_types(db, stranger_ws)
    stranger = make(db, stranger_ws, "Vacuum Pump", "Pump elsewhere naming it", installed_in=building.uid)
    db.commit()
    yield {**lab, "building": building, "room": room, "level": level, "plan": plan, "btf_note": btf_note,
           "stranger": stranger, "stranger_ws": stranger_ws}
    from app.ledger.audit import allow_purge
    db.rollback()
    allow_purge(db)
    db.delete(db.get(Workspace, stranger_ws))
    db.commit()


def test_the_report_says_what_moves_and_what_would_resolve_before_anything_changes(edificio):
    db, ids, e = edificio["db"], edificio["ids"], edificio
    report = indoor_transfer.preview(db, ids["other"], ids["lnf"], "move", {e["building"].uid, e["room"].uid})
    assert {x["name"] for x in report["records"]} == {"Edificio 9", "Room 4"}
    assert all(x["site_shared_after"] for x in report["records"])               # places of a site, afterwards
    assert report["indoors"]["plans"][0]["files_present"] and report["indoors"]["plans"][0]["placed_on_map"]
    assert [p["name"] for p in report["placements"]] == ["Room 4"] and report["placements"][0]["eligible"]
    [inside] = report["placed_inside"]
    assert inside["record"]["name"] == "SPARC pump" and inside["keeps_placement"]   # SPARC is at LNF
    refs = {r["from"]["name"]: r for r in report["references"] if r["kind"] == "attribute"}
    assert refs["BTF pump naming it"]["resolves_after"] and refs["BTF pump naming it"]["resolves_if_not_global"]
    assert refs["Pump elsewhere naming it"]["resolves_after"]                      # global, still
    assert not refs["Pump elsewhere naming it"]["resolves_if_not_global"]          # not at LNF: global keeps it
    assert report["clean"]
    db.expire_all()
    assert db.get(type(e["building"]), e["building"].uid).workspace_id == ids["other"]   # nothing changed


def test_a_move_keeps_uids_floors_plans_files_fit_and_placements(edificio):
    db, ids, e = edificio["db"], edificio["ids"], edificio
    path, fit = e["plan"].storage_path, dict(e["plan"].transform)
    job = _run(db, ids["other"], ids["lnf"], "move", {e["building"].uid, e["room"].uid})
    assert job.counts["indoor_levels"] == 1 and job.counts["indoor_plans"] == 1
    b = db.get(type(e["building"]), e["building"].uid)
    assert b.workspace_id == ids["lnf"] and b.site_shared and b.key == e["building"].key
    plan = db.get(FloorPlan, e["plan"].uid)
    assert plan.workspace_id == ids["lnf"] and plan.storage_path == path and os.path.exists(path)
    assert plan.transform == fit and db.get(PlaceLevel, e["level"].uid).workspace_id == ids["lnf"]
    assert indoor.current(db, e["rec"]["sparc_pump"].uid).plan_uid == plan.uid     # SPARC's pump still on it
    assert indoor.current(db, e["room"].uid).place_uid == b.uid                    # the room still in the building
    assert e["btf_note"].attributes["installed_in"] == b.uid                       # references hold: same uid


def test_a_copy_copies_floors_plans_files_fit_and_places_the_copies(edificio):
    db, ids, e = edificio["db"], edificio["ids"], edificio
    _run(db, ids["other"], ids["lnf"], "copy", {e["building"].uid, e["room"].uid})
    from app.models.asset import Asset
    copy = db.scalar(select(Asset).where(Asset.workspace_id == ids["lnf"],
                                         Asset.attributes["_copy_source_uid"].astext == e["building"].uid))
    room = db.scalar(select(Asset).where(Asset.workspace_id == ids["lnf"],
                                         Asset.attributes["_copy_source_uid"].astext == e["room"].uid))
    [plan] = db.scalars(select(FloorPlan).where(FloorPlan.place_uid == copy.uid)).all()
    assert plan.uid != e["plan"].uid and plan.storage_path != e["plan"].storage_path and os.path.exists(plan.storage_path)
    assert plan.transform == e["plan"].transform and plan.level_uid is not None and plan.workspace_id == ids["lnf"]
    assert indoor.current(db, room.uid).place_uid == copy.uid                      # the copied room in the copy
    assert db.get(FloorPlan, e["plan"].uid).workspace_id == ids["other"]           # the original stays


def test_a_move_ends_a_facility_placement_that_would_no_longer_be_reachable(lab):
    db, ids, r = lab["db"], lab["ids"], lab["rec"]
    plan = indoor.add_plan(db, r["building"], "g.png", _png(), name="G", level=None, actor="t")
    indoor.place(db, r["sparc_pump"], place_uid=r["building"].uid, plan_uid=plan.uid, x=5, y=5, actor="t")
    db.commit()
    report = indoor_transfer.preview(db, ids["lnf"], ids["other"], "move", {r["building"].uid})
    [inside] = report["placed_inside"]
    assert not inside["keeps_placement"] and not report["clean"]
    assert any("SPARC pump" in p for p in report["problems"])
    job = _run(db, ids["lnf"], ids["other"], "move", {r["building"].uid})
    assert job.counts["indoor_placements_ended"] == 1
    ended = db.scalar(select(IndoorPlacement).where(IndoorPlacement.asset_uid == r["sparc_pump"].uid))
    assert ended.state == "withdrawn"


def test_a_stray_record_moves_out_of_the_catalogue_and_a_vendor_does_not(lab):
    from fastapi.testclient import TestClient

    from app.auth import OidcIdentity, get_identity
    from app.catalogue import system
    from app.main import app
    db, ids, r = lab["db"], lab["ids"], lab["rec"]
    before = system.designated(db)
    if before:
        db.get(Workspace, before).role = None
        db.flush()
    db.get(Workspace, ids["other"]).role = system.ROLE
    stray = make(db, ids["other"], "Area", "Edificio 2")
    vendor = make(db, ids["other"], "Vendor", "Moxa")
    db.commit()
    try:
        app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=lab["admin"])
        client, h = TestClient(app), {"X-Workspace-Id": ids["other"]}
        body = {"target_workspace_id": ids["lnf"], "mode": "move", "type_uids": [], "include_instances": False,
                "document_uids": [], "issue_uids": []}
        ok = client.post("/v1/transfers/preview", headers=h, json={**body, "asset_uids": [stray.uid]})
        assert ok.status_code == 200, ok.text
        assert ok.json()["records"][0]["name"] == "Edificio 2" and ok.json()["records"][0]["site_shared_after"]
        refused = client.post("/v1/transfers/preview", headers=h, json={**body, "asset_uids": [vendor.uid]})
        assert refused.status_code == 422 and refused.json()["detail"]["code"] == "catalogue_workspace"
    finally:
        app.dependency_overrides.pop(get_identity, None)
        db.rollback()
        db.get(Workspace, ids["other"]).role = None
        db.flush()
        if before:
            db.get(Workspace, before).role = system.ROLE
        db.commit()
