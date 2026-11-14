"""Rack layouts and the demos (docs/rack-elevation.md, "The demos" and "Updating an imported demo"): the demos come with
their units in their racks, coherent and without overlaps; their plans' drawings carry no unit markers; the layout
applies again to an imported demo — renamed or not — changing nothing that is already so."""
import json
import secrets
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.bundle.core import NAMESPACE
from app.db import SessionLocal
from app.main import app
from app.models.indoor import FloorPlan
from app.services import rack_layout
from tests.test_workspace_bundles import _drop, admin  # noqa: F401 — an administrator applies demos

client = TestClient(app)
LAYOUTS = Path(__file__).resolve().parents[1] / "scripts" / "demo_rack_layouts"


def _apply_demo(name: str, ws: str) -> None:
    r = client.post(f"/v1/admin/bundles/demos/{name}/apply", json={"workspace_id": ws, "name": f"Racks {ws}"})
    assert r.status_code == 200 and r.json()["ok"], r.text


@pytest.mark.parametrize("name", ["it-services", "medium-linac"])
def test_a_demo_comes_with_its_racks_filled_and_its_plans_drawn_without_units(admin, name):  # noqa: F811
    layout = json.loads((LAYOUTS / f"{name}.json").read_text())
    ws = f"rk-{secrets.token_hex(3)}"
    try:
        _apply_demo(name, ws)
        h = {"X-Workspace-Id": ws}
        for spec in layout["racks"]:
            rack = spec["rack"] if client.get(f"/v1/racks/{spec['rack']}", headers=h).status_code == 200 \
                else str(uuid.uuid5(NAMESPACE, f"{ws}:{spec['rack']}"))
            view = client.get(f"/v1/racks/{rack}", headers=h).json()
            assert view["problems"] == [], (spec["rack"], view["problems"])
            assert len(view["mountings"]) == len(spec["units"]), spec["rack"]
            assert [c["name"] for c in view["unplaced"] if c["type"] != "Computing Node"] == [], spec["rack"]
        db = SessionLocal()
        plans = list(db.query(FloorPlan).filter(FloorPlan.workspace_id == ws))
        drawings = [Path(p.storage_path).read_text() for p in plans]
        db.close()
        assert drawings and all('stroke="#1e293b"' not in d for d in drawings)
        # The racks are the points; the units they hold are not.
        layers = [client.get(f"/v1/plans/{p.uid}/layers", headers=h).json() for p in plans]
        assert sum(lyr["in_racks"] for lyr in layers) >= sum(len(s["units"]) for s in layout["racks"]) // 2
        held = {u for lyr in layers for u in lyr["held"]}
        assert not held & {i["uid"] for lyr in layers for i in lyr["items"]}

        # The layout applied again — as to a demo imported earlier — changes nothing.
        db = SessionLocal()
        again = rack_layout.apply(db, ws, layout, actor="test")
        db.rollback()
        db.close()
        assert again["changed"] == [] and again["missing"] == [] and again["refused"] == []
    finally:
        _drop(ws)


def test_the_tunnel_finds_each_supply_in_its_rack(admin):  # noqa: F811
    ws = f"rk-t-{secrets.token_hex(3)}"
    try:
        _apply_demo("medium-linac", ws)
        h = {"X-Workspace-Id": ws}
        main = next(p for p in client.get("/v1/beam-paths", headers=h).json() if "main dump" in p["name"])
        t = client.get(f"/v1/beam-paths/{main['uid']}/tunnel", headers=h).json()
        q1 = next(e for e in t["elements"] if e["name"] == "QUA01")
        supply = q1["hardware"][0]["supplies"][0]
        assert supply["rack"] and supply["rack"]["name"].startswith("Rack A12-1"), supply
        rack = client.get(f"/v1/racks/{supply['rack']['uid']}", headers=h).json()
        at = next(m for m in rack["mountings"] if m["asset"] and m["asset"]["uid"] == supply["uid"])
        assert (at["start_u"], at["height_u"], at["face"]) == (40, 3, "front")
        assert t["rooms"] and t["rooms"][0]["name"] == "Linac Bunker"
    finally:
        _drop(ws)


def test_a_layout_moves_what_differs_and_reads_renamed_identifiers(admin):  # noqa: F811
    """A second clone of a demo renames identifiers taken by the first: the layout still finds them. A unit moved by
    hand goes back where the layout says, and only that changes."""
    first, second = f"rk-a-{secrets.token_hex(3)}", f"rk-b-{secrets.token_hex(3)}"
    layout = json.loads((LAYOUTS / "it-services.json").read_text())
    try:
        _apply_demo("it-services", first)
        _apply_demo("it-services", second)
        h = {"X-Workspace-Id": second}
        rack = str(uuid.uuid5(NAMESPACE, f"{second}:nf-rack-a02"))
        hv = str(uuid.uuid5(NAMESPACE, f"{second}:nf-hv-01"))
        moved = client.post(f"/v1/racks/{rack}/apply", headers=h,
                            json={"operations": [{"op": "place", "asset_uid": hv, "start_u": 30, "height_u": 2}]})
        assert moved.status_code == 200, moved.text
        db = SessionLocal()
        report = rack_layout.apply(db, second, layout, actor="test")
        db.commit()
        db.close()
        assert report["missing"] == [] and report["refused"] == []
        assert report["changed"] == ["Rack R-A02: Hypervisor host 01: U30–U31 front → U20–U21 front"]
        history = client.get(f"/v1/racks/{rack}/history", headers=h).json()
        assert [r["start_u"] for r in history if r["asset"] and r["asset"]["uid"] == hv][:3] == [20, 30, 20]
    finally:
        _drop(first, second)
