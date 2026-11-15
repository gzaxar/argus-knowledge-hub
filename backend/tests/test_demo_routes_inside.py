"""Inside a building, a demo cable or pipe runs along the gaps between rooms to the room it serves
(scripts/demo_routes_inside.py): square runs, never across another room, and doing it again changes nothing."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


routes = load("demo_routes_inside")
drawing = load("demo_plan_drawing")

BUILDING = (2.0, 2.0, 696.0, 236.0)
ROOMS = [(40, 140, 440, 80), (160, 60, 320, 60), (40, 60, 100, 60), (40, 20, 440, 30), (500, 20, 160, 100),
         (500, 140, 80, 80), (590, 140, 70, 80)]


def square(points) -> bool:
    return all(a[0] == b[0] or a[1] == b[1] for a, b in zip(points, points[1:]))


def crosses(points, room, pad=1.0) -> bool:
    """Whether a square run goes through the inside of a room (sampled every pixel)."""
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) or 1
        for k in range(n + 1):
            x, y = x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n
            if routes.inside((x, y), room, pad):
                return True
    return False


@pytest.mark.parametrize("line, room", [
    ([(1020, 190), (1020, 40), (600, 20), (400, 60)], (160, 60, 320, 60)),       # cooling water to the gallery
    ([(880, 190), (750, 190), (700, 180), (580, 180)], (500, 140, 80, 80)),       # feeder to the electrical room
    ([(250, -210), (400, -60), (560, 20)], (500, 20, 160, 100)),                  # fibre to the control room
])
def test_a_route_comes_through_the_wall_and_runs_square_to_its_room(line, room):
    new = routes.reroute(line, BUILDING, ROOMS)
    k = next(i for i, p in enumerate(new) if routes.inside(p, BUILDING))
    assert new[:k] == line[:k]                                         # outside the building: as it was
    inner = new[k:]
    assert inner[0][0] in (2.0, 698.0) or inner[0][1] in (2.0, 238.0)    # in through a wall
    assert square(inner)
    assert routes.inside(inner[-1], room, 6)                          # ends well inside the room it serves
    assert not any(crosses(inner, r) for r in ROOMS if r != room)     # through no other room
    assert routes.reroute(new, BUILDING, ROOMS) == new                # again: nothing changes
    assert routes.reroute(list(reversed(new)), BUILDING, ROOMS) == list(reversed(new))    # either way round


def test_nothing_changes_for_a_route_with_both_or_neither_end_inside():
    assert routes.reroute([(10, 10), (30, 10)], BUILDING, ROOMS) is None
    assert routes.reroute([(-10, -10), (-30, -10)], BUILDING, ROOMS) is None


def to_plan(t, lon, lat):
    det = t["a"] * t["e"] - t["b"] * t["d"]
    dl, dt = lon - t["c"], lat - t["f"]
    return ((t["e"] * dl - t["b"] * dt) / det, (t["a"] * dt - t["d"] * dl) / det)


@pytest.mark.parametrize("demo", ["medium-linac", "it-services"])
def test_the_demo_routes_run_square_inside_their_buildings(demo):
    base = ROOT / "demo_workspaces" / demo
    rows = lambda name: [json.loads(x) for x in (base / "records" / f"{name}.jsonl").read_text().splitlines() if x.strip()]
    lines = [f["geometry"]["coordinates"] for f in rows("spatial_features")
             if f["role"] == "route" and f["state"] == "confirmed" and not f["valid_until"]]
    checked = 0
    for plan in rows("floor_plans"):
        if not plan.get("transform"):
            continue
        digest = plan["storage_path"]["$file"]
        model = drawing.read((base / "files" / digest[:2] / digest).read_text())
        if not model.get("building") or not model["rooms"]:
            continue
        building, rooms = tuple(model["building"]), [tuple(r["box"]) for r in model["rooms"]]
        for coords in lines:
            pts = [tuple(round(v, 1) for v in to_plan(plan["transform"], lon, lat)) for lon, lat, *_ in coords]
            ins = [routes.inside(p, building) for p in (pts[0], pts[-1])]
            if ins.count(True) != 1:
                continue
            pts = pts if ins[1] else list(reversed(pts))
            inner = pts[next(i for i, p in enumerate(pts) if routes.inside(p, building)):]
            assert square(inner), (plan["name"], inner)
            if any(routes.inside(pts[-1], r) for r in rooms):
                room = next(r for r in rooms if routes.inside(pts[-1], r))
                assert not any(crosses(inner, r) for r in rooms if r != room), (plan["name"], inner)
                checked += 1
    assert checked >= (4 if demo == "medium-linac" else 2)
