"""Domain packages on the shared core: each alone, in combinations, shared across workspaces, and the
accelerator catalogue split into core-objects, it and accelerator without any workspace noticing."""
import secrets
import shutil
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.ledger import service
from app.models.asset import Relation
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.packages import install as installer
from app.packages import loader
from app.packages.loader import available
from app.packages.validate import validate
from app.services import asset_types

DOMAINS = ("it", "electrical", "hydraulic", "hvac", "plant")
OLD_ACCELERATOR = Path(__file__).parent / "fixtures" / "package_versions" / "accelerator-1.0.0"
RELEASE_1_35_25 = Path(__file__).parent / "fixtures" / "package_versions" / "release-1.35.25"


def _names(package_id: str) -> set[str]:
    from app.packages import defaults
    return {t.name for t in defaults.object_types(package_id)}


@pytest.fixture()
def spaces():
    made: list[str] = []

    def make(prefix="dom") -> str:
        w = f"{prefix}-{secrets.token_hex(3)}"
        db = SessionLocal()
        db.add(Workspace(id=w, name=w))
        db.commit()
        db.close()
        made.append(w)
        return w
    yield make
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    for w in reversed(made):
        row = db.get(Workspace, w)
        if row is not None:
            db.delete(row)
    db.commit()
    db.close()


def _object_names(db, ws) -> list[str]:
    return list(db.scalars(select(Schema.name).where(Schema.workspace_id == ws, Schema.applies_to == "objects")))


def test_every_shipped_package_is_valid_and_no_two_define_the_same_type():
    shipped = available()
    assert {"core-objects", *DOMAINS, "accelerator"} <= set(shipped)
    owners: dict = {}
    for p in shipped.values():
        assert validate(p) == [], p.id
        for t in (p.section("object_types") or {}).get("types") or []:
            assert t["name"] not in owners, f"{t['name']} is in {owners.get(t['name'])} and {p.id}"
            owners[t["name"]] = p.id


@pytest.mark.parametrize("domain", DOMAINS)
def test_each_domain_installs_alone_on_the_core(domain, spaces):
    ws = spaces()
    db = SessionLocal()
    plan = installer.install(db, ws, [domain])
    db.commit()
    names = _object_names(db, ws)
    assert len(names) == len(set(names)), "a type twice"
    assert set(names) == _names(domain), "its types and the core's, and nothing of another domain"
    assert not set(names) & (_names("accelerator") - _names("it") - _names("core-objects"))
    assert "core-objects" in {s.package_id for s in plan.steps}
    db.close()


def test_supported_combinations_share_one_core_without_duplicates(spaces):
    ws = spaces()
    db = SessionLocal()
    installer.install(db, ws, ["accelerator", "plant"])
    installer.install(db, ws, ["it"])                    # already there with the accelerator: nothing new
    db.commit()
    names = _object_names(db, ws)
    assert len(names) == len(set(names))
    assert set(names) == _names("accelerator") | _names("plant")
    from app.packages import defaults
    assert set(installer.installed(db, ws)) == set(defaults.closure("accelerator")) | set(defaults.closure("plant"))
    db.close()


def test_a_shared_domain_catalogue_serves_other_workspaces(spaces):
    catalogue, site = spaces("dom-cat"), spaces("dom-site")
    db = SessionLocal()
    installer.install(db, catalogue, ["electrical"], scope="global")
    installer.install(db, site, ["electrical"], catalogue_workspace_id=catalogue)
    db.commit()
    assert _object_names(db, site) == [], "the site holds no copy of the shared types"
    shared = db.get(Schema, asset_types.type_uid(catalogue, "Circuit Breaker"))
    assert shared.is_global
    assert asset_types.resolve_type_uids(db, site)["Circuit Breaker"] == shared.uid
    assert installer.installed(db, site)["electrical"].options == {"scope": "beamline", "catalogue_workspace_id": catalogue}
    db.close()


def test_a_units_supply_is_a_power_edge_of_the_graph(spaces):
    ws = spaces()
    db = SessionLocal()
    installer.install(db, ws, ["electrical"])
    db.commit()
    board = service.create_record(db, ws, "test", uid=str(uuid.uuid4()), key=f"{ws}-MSB", name="Main board",
                                  schema_uid=asset_types.type_uid(ws, "Switchboard"), type_name="Switchboard",
                                  attributes={"rated_voltage_v": 400, "ip_rating": "IP54"})
    breaker = service.create_record(db, ws, "test", uid=str(uuid.uuid4()), key=f"{ws}-CB-1", name="Breaker 1",
                                    schema_uid=asset_types.type_uid(ws, "Circuit Breaker"), type_name="Circuit Breaker",
                                    attributes={"fed_from": board.uid, "rated_current_a": 63})
    db.commit()
    edges = {(r.from_asset_uid, r.relation_type, r.to_asset_uid) for r in db.scalars(
        select(Relation).where(Relation.from_asset_uid == breaker.uid))}
    assert (breaker.uid, "fed from", board.uid) in edges
    from app.services.causal_model import SEMANTICS
    assert SEMANTICS["fed from"].layer == "power"
    db.close()


def test_a_workspace_on_the_old_catalogue_moves_to_the_split_one_with_nothing_changed(spaces, tmp_path, monkeypatch):
    """accelerator 1.0.0 held the whole catalogue; now it stands on core-objects, it, safety, vacuum-cryo and
    optics-alignment. The types that moved are reported as moved, not removed; every type the workspace had is
    as it was; what is new is only the types those packages add."""
    ws = spaces()
    old = tmp_path / "old"
    old.mkdir()
    shutil.copytree(RELEASE_1_35_25 / "core-facility", old / "core-facility")
    shutil.copytree(OLD_ACCELERATOR, old / "accelerator")
    monkeypatch.setenv("ARGUS_PACKAGES_DIR", str(old))
    loader.reload()
    db = SessionLocal()
    installer.install(db, ws, ["accelerator"])
    db.commit()
    before = {s.uid: (s.name, s.parent_schema_uid, s.attributes) for s in db.scalars(
        select(Schema).where(Schema.workspace_id == ws, Schema.applies_to == "objects"))}
    assert installer.installed(db, ws)["accelerator"].version == "1.0.0" and len(before) == 153
    monkeypatch.delenv("ARGUS_PACKAGES_DIR")
    loader.reload()

    preview = installer.plan(db, ws, ["accelerator"])
    db.rollback()
    steps = {s.package_id: s for s in preview.steps}
    assert steps["accelerator"].action == "upgrade" and steps["accelerator"].result["needs_decision"] == []
    moved = [c for c in steps["accelerator"].result["changes"] if c["what"] == "moved"]
    assert {c["subject"] for c in moved} >= {"Asset", "Item", "Vendor", "Switch", "Server"}
    assert steps["core-objects"].action == "install" and steps["it"].action == "install"

    installer.install(db, ws, ["accelerator"], actor="tester")
    db.commit()
    after = {s.uid: (s.name, s.parent_schema_uid, s.attributes) for s in db.scalars(
        select(Schema).where(Schema.workspace_id == ws, Schema.applies_to == "objects"))}
    # Every type as it was; the it package adds its GLPI provenance fields to the root (an extension).
    unprovenanced = {u: (v[0], v[1], [a for a in v[2] if a["key"] not in ("glpi_url", "glpi_unmapped")])
                     for u, v in after.items() if u in before}
    assert unprovenanced == before, "every type as it was"
    item = next(v for v in after.values() if v[0] == "Item")
    assert {"glpi_url", "glpi_unmapped"} <= {a["key"] for a in item[2]}
    from app.packages import defaults
    now_defined = {t.name for t in defaults.object_types("accelerator")}
    old_names = {v[0] for v in before.values()}
    assert {v[0] for u, v in after.items() if u not in before} == now_defined - old_names
    assert {"Firewall", "Fire Extinguisher", "Cryostat", "Laser Oscillator", "Contract"} <= now_defined - old_names
    rows = installer.installed(db, ws)
    assert rows["accelerator"].version == available()["accelerator"].version
    assert {"core-objects", "it"} <= set(rows)
    db.close()
