"""The demo floor plans, drawn as a room schedule (scripts/demo_plan_drawing.py): the geometry does not move, every
room's name fits inside it, and drawing again changes nothing."""
import html
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("demo_plan_drawing", ROOT / "scripts" / "demo_plan_drawing.py")
drawing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drawing)

FIRST = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 300" width="700" height="300">
<rect x="0" y="0" width="700" height="300" fill="#ffffff"/>
<rect x="2" y="2" width="696" height="236" fill="#f8fafc" stroke="#0f172a" stroke-width="6"/>
<rect x="40" y="140" width="440" height="80" fill="#fee2e2" stroke="#334155" stroke-width="3"/>
<text x="260" y="170" font-size="34" font-weight="bold">Linac Bunker</text>
<text x="260" y="204" font-size="20" fill="#475569">A0.01</text>
<rect x="590" y="140" width="70" height="80" fill="#e0f2fe" stroke="#334155" stroke-width="3"/>
<text x="625" y="170" font-size="14" font-weight="bold">RF and Vacuum Service Area</text>
<text x="625" y="184" font-size="8" fill="#475569">A0.12</text>
<polyline points="60,180 370,180" fill="none" stroke="#dc2626" stroke-width="6" stroke-dasharray=""/>
<text x="70" y="168" font-size="18" fill="#dc2626">e- beam axis (s = 0 at the gun)</text>
<g transform="translate(650,60)"><polygon points="0,-30 10,0 -10,0" fill="#0f172a"/><text x="0" y="22">N</text></g>
<text x="12" y="265" font-size="20" fill="#0f172a" font-weight="bold">Accelerator Building — ground floor</text>
<text x="12" y="290" font-size="15" fill="#b91c1c">Synthetic demo plan — not a real building · scale 1 m = 10 px</text>
</svg>"""


def boxes(svg: str) -> list[list[float]]:
    return [r["box"] for r in drawing.read(svg)["rooms"]]


def test_a_first_generation_drawing_is_redrawn_in_place():
    out = drawing.redraw(FIRST)
    assert 'viewBox="0 0 700 300"' in out                                   # same size: placed points stay put
    assert boxes(out) == [[40, 140, 440, 80], [590, 140, 70, 80]]          # the rooms where they were
    assert '<rect x="40" y="140" width="440" height="80"' in out
    assert "LINAC BUNKER" in out and "A0.01 · 352 m²" in out              # name, number and area (1 m = 10 px)
    assert ">RF AND<" in out or ">RF AND VACUUM<" in out                    # a long name wraps to fit its room
    assert 'fill="url(#hatch)"' in out                                      # the bunker's shielding
    assert "e- beam axis (s = 0 at the gun)" in out and 'points="60,180 370,180"' in out
    assert "not a real building" in out
    assert drawing.redraw(out) == out                                       # again: nothing changes


@pytest.mark.parametrize("demo", ["medium-linac", "it-services"])
def test_the_demo_plans_are_drawn_so_and_their_names_fit(demo):
    base = ROOT / "demo_workspaces" / demo
    for line in (base / "records" / "floor_plans.jsonl").read_text().splitlines():
        plan = json.loads(line)
        digest = plan["storage_path"]["$file"]
        svg = (base / "files" / digest[:2] / digest).read_text()
        assert drawing.MARK in svg, f"{plan['name']} is not drawn by scripts/demo_plan_drawing.py"
        # Drawn again it is the same building; only its labels may sit elsewhere, clear of what is placed now.
        assert drawing.read(drawing.redraw(svg)) == drawing.read(svg)
        assert f'viewBox="0 0 {plan["width_px"]:g} {plan["height_px"]:g}"' in svg
        model = drawing.read(svg)
        for room in model["rooms"]:
            x, y, w, h = room["box"]
            fs, lines = drawing._fit(room["name"], w, h)
            assert max(len(s) for s in lines) * fs * 0.64 <= w - 6, (plan["name"], room["name"])
            pill = re.search(rf'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" rx="3"[^>]*/>\s*'
                             rf'<text x="[\d.]+"[^>]*>(?:{re.escape(html.escape(lines[0]))}|'
                             rf'{re.escape(html.escape(room["name"].upper().split()[0]))})</text>', svg)
            assert pill, (plan["name"], room["name"])
            px, py, pw, ph = (float(v) for v in pill.groups())
            assert x <= px and px + pw <= x + w and y <= py and py + ph <= y + h, (plan["name"], room["name"])
            under = [p for p in points(base, plan["uid"]) if px - 4 <= p[0] <= px + pw + 4 and py - 4 <= p[1] <= py + ph + 4]
            assert len(under) <= covered.get((demo, room["name"]), 0), (plan["name"], room["name"], under)


# A label is put where no point of the plan covers it; in a room too full for that, as few as can be.
covered: dict = {("medium-linac", "Klystron Gallery (RF)"): 1,        # 19 points in 32 m × 6 m
                 ("medium-linac", "RF and Vacuum Service Area"): 2}   # 10 points in 7 m × 8 m


def points(base: Path, plan_uid: str) -> list:
    """The points ARGUS draws over a plan of a bundle: what is placed on it, a unit in a rack shown as its rack."""
    def rows(name):
        return [json.loads(x) for x in (base / "records" / f"{name}.jsonl").read_text().splitlines() if x.strip()]
    live = [m for m in rows("rack_mountings") if m["state"] == "confirmed" and not m["valid_until"]]
    racks = {m["rack_uid"] for m in live} | {a["uid"] for a in rows("assets") if a["type"] == "Rack"}
    mounted = {m["asset_uid"] for m in live if m["asset_uid"]}
    return [(p["plan_x"], p["plan_y"]) for p in rows("indoor_placements")
            if p["plan_uid"] == plan_uid and p["state"] == "confirmed" and not p["valid_until"]
            and p["plan_x"] is not None and p["asset_uid"] not in mounted
            and (p["asset_uid"] in racks or p.get("place_uid") not in racks)]
