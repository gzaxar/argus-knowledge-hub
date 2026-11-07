"""Simulator files to the canonical beam model (app/beam_converters): MAD-X sequences, lines and TFS tables,
Elegant and Bmad lattices, Xsuite lines and Accelerator Toolbox lattices. The same ring written six ways must give
the same model (argus.beam-model/2); the survey from lengths and bends must close a ring; what the simulator said
survives as native data with per-value provenance; what a converter cannot read is said, not guessed; and a
converted model imports.
"""
import math
from pathlib import Path

import pytest

from app import beam_converters as bc
from app.beam_model_core.validation import load

F = Path(__file__).parent / "fixtures" / "beam_model"
RING = ("dafne_accumulator.madx", "dafne_accumulator.lte", "dafne_accumulator_twiss.tfs", "dafne_accumulator.bmad",
        "dafne_accumulator.xsuite.json", "dafne_accumulator.at.json")


def conv(name: str, **opts) -> dict:
    return bc.convert(name, (F / name).read_text(), bc.Options(**opts))


def order(d: dict, i: int = 0) -> list[str]:
    return [p if isinstance(p, str) else p["component"] for p in d["paths"][i]["placements"]]


def comps(d: dict) -> dict:
    return {c["id"]: c for c in d["components"]}


def valid(d: dict):
    doc, rep = load({k: v for k, v in d.items() if k != "conversion"})
    assert rep.ok, rep.errors
    return doc, rep


def test_the_same_ring_written_six_ways_is_one_model():
    docs = [conv(n, model_id="acc") for n in RING]
    orders = [order(d) for d in docs]
    assert all(o == orders[0] for o in orders) and len(orders[0]) == 54
    for d in docs:
        counts = {}
        for e in d["components"]:
            counts[e["type"]] = counts.get(e["type"], 0) + 1
        # The accumulator's own counts: what the layout of the real machine shows.
        assert counts == {"bpm": 12, "kicker": 4, "septum": 2, "corrector": 8, "dipole": 8, "quadrupole": 12,
                          "sextupole": 8}, d["provenance"]
        assert d["schema_version"] == "argus.beam-model/2"
        assert d["paths"][0]["topology"] == "closed" and abs(d["paths"][0]["length"] - 32.56) < 1e-6
        v = d["datasets"][0]["values"]["QUAA101"]
        assert v["physics"]["k1"] == pytest.approx(4.30926) and v["physics"]["length"] == 0.3
        assert abs(v["s"] - docs[0]["datasets"][0]["values"]["QUAA101"]["s"]) < 1e-6
        assert d["conversion"]["survey_closure_m"] < 1e-6
        _doc, rep = valid(d)                                                    # each is a valid canonical model
        assert "LATTICE" in rep.levels


def test_the_survey_closes_a_ring_and_places_its_dipoles():
    d = conv("dafne_accumulator.madx")
    assert d["conversion"]["ring"] and d["conversion"]["survey_closure_m"] < 1e-6
    assert d["conversion"]["total_bend"] == pytest.approx(2 * math.pi)
    values = d["datasets"][0]["values"]
    # After the first quadrant the heading has turned 90°; a full turn brings it back.
    assert values["DIPA21"]["geometry"]["yaw"] == pytest.approx(math.pi / 2, abs=1e-6)
    assert values["SPTA1001"]["geometry"] == {"x": 0.0, "y": 0.0, "yaw": 0.0}


def test_madx_keeps_what_the_simulator_says_and_names_what_it_is():
    d = conv("dafne_accumulator.madx")
    by = comps(d)
    assert by["KCKA1001"]["type"] == "kicker" and by["KCKA1001"]["native"] == {
        "format": "madx", "type": "HKICKER", "name": "KCKA1001", "file": "dafne_accumulator.madx"}
    assert "pulsed" in by["KCKA1001"]["capabilities"] and "horizontal_steering" in by["KCKA1001"]["capabilities"]
    assert by["SPTA1001"]["type"] == "septum" and by["SPTA1001"]["native"]["type"] == "RBEND"
    assert by["CHV11"]["type"] == "corrector"
    assert {"horizontal_steering", "vertical_steering"} <= set(by["CHV11"]["capabilities"])
    assert by["BPSA11"]["observes"] == ["beam.position.x", "beam.position.y"]
    dip = d["datasets"][0]["values"]["DIPA11"]
    assert dip["physics"]["angle"] == pytest.approx(math.pi / 4) and dip["native"]["parameters"]["ANGLE"] == pytest.approx(math.pi / 4)
    beam = d["beams"][0]
    assert beam["species"] == "electron" and beam["reference_energy"] == 0.51 and beam["charge"] == -1
    assert d["datasets"][0]["values"]["QUAA101"]["provenance"]["k1"] == {
        "source": "madx", "file": "dafne_accumulator.madx", "symbol": "K1"}


def test_madx_markers_are_kept_and_what_the_simulation_does_not_compute_is_named():
    """A lattice places pumps, valves and gauges as markers: MAD-X computes nothing for them, but they are on
    the beam line, and the beam model keeps them — typed by their name when it follows the usual conventions."""
    text = """
    qf: quadrupole, l=0.4, k1=1.2;
    vpi01: marker;  vv01: marker;  vgc01: marker;  ip1: marker;  mstart: marker;
    tl: sequence, l=6, refer=entry;
      mstart, at=0;
      q1: qf, at=1;
      vpi01, at=2;
      vv01, at=3;
      vgc01, at=4;
      ip1, at=5;
    endsequence;
    """
    d = bc.convert("tl.madx", text, bc.Options(beamline="tl"))
    valid(d)
    by = comps(d)
    assert order(d) == ["MSTART", "Q1", "VPI01", "VV01", "VGC01", "IP1"]
    assert by["VPI01"]["type"] == "pump_port" and by["VV01"]["type"] == "gate_valve"
    assert by["VGC01"]["type"] == "gauge_port"
    assert by["IP1"]["type"] == "marker" and by["MSTART"]["type"] == "marker", "a marker it cannot name stays one"
    assert by["VPI01"]["native"]["type"] == "MARKER"
    assert d["datasets"][0]["values"]["VPI01"]["s"] == pytest.approx(2)
    dropped = bc.convert("tl.madx", text, bc.Options(beamline="tl", keep_markers=False))
    assert order(dropped) == ["Q1"], "left out only when asked"


def test_madx_language_variables_inheritance_refer_from_and_lines():
    text = """
    ! a transfer line, two ways
    lq := 0.2 * 2;  kf = 1.5;  kd = -kf;
    qf: quadrupole, l=lq, k1=kf;   qd: qf, k1=kd;      // qd inherits l from qf
    m1: monitor;
    bend: sbend, l=1.0, angle=0.1;
    tl: sequence, l=10, refer=entry;
      q1: qf, at=1;
      b1: bend, at=3;
      q2: qd, at=2, from=b1;
      m1, at=9;
    endsequence;
    cell: line=(qf, d1, qd, d1);
    d1: drift, l=0.5;
    arc: line=(2*cell, -(m1, bend));
    """
    seq = bc.convert("tl.madx", text, bc.Options(beamline="tl"))
    vals = seq["datasets"][0]["values"]
    assert order(seq) == ["Q1", "B1", "Q2", "M1"] and seq["paths"][0]["topology"] == "open"
    # q1 is an instance of the user's qf: qf is its definition and family
    assert comps(seq)["Q1"]["definition"] == "QF" and comps(seq)["Q2"]["family"] == "QD"
    assert vals["Q1"]["s"] == 1 and vals["Q2"]["s"] == 5                      # refer=entry; at 2 from b1 at 3
    assert vals["Q2"]["physics"] == {"length": 0.4, "k1": -1.5}               # inherited length, deferred lq
    line = bc.convert("tl.madx", text, bc.Options(beamline="arc"))
    assert order(line) == ["QF", "QD", "QF#2", "QD#2", "BEND", "M1"]           # repeats, then reversed
    assert comps(line)["QF#2"]["definition"] == "QF" and "QF" in {x["id"] for x in line["definitions"]}
    lv = line["datasets"][0]["values"]
    assert lv["QF#2"]["s"] == pytest.approx(1.8) and lv["BEND"]["s"] == pytest.approx(3.6)


def test_elegant_reads_rpn_and_continuations():
    text = """
    % 0.5 sto halfl
    Q1: KQUAD, L="halfl 2 *", &
        K1=8.2
    D1: DRIF, L=0.25
    B1: CSBEND, L=0.5, ANGLE="pi 18 /"
    W1: WATCH, FILENAME="w1.sdds"
    L1: LINE=(Q1, D1, B1, W1, D1, Q1)
    """
    d = bc.convert("x.lte", text, bc.Options(keep_markers=False))
    assert order(d) == ["Q1", "B1", "Q1#2"]                                    # drifts and watch points left out
    v = d["datasets"][0]["values"]
    assert v["Q1"]["physics"] == {"length": 1.0, "k1": 8.2} and v["B1"]["s"] == pytest.approx(1.25)
    assert v["B1"]["physics"]["angle"] == pytest.approx(math.pi / 18) and v["Q1#2"]["s"] == pytest.approx(2.0)
    with_markers = bc.convert("x.lte", text)                                    # kept unless asked otherwise
    assert "W1" in order(with_markers)
    v1 = bc.convert("x.lte", text, bc.Options(output="1", keep_markers=False))                    # the old form, when asked
    assert v1["format"] == "argus.beam-model/1" and v1["paths"][0]["elements"] == ["Q1", "B1", "Q1#2"]


@pytest.mark.parametrize("name, text, problem", [
    ("a.madx", "q: quadrupole, l=1;", "no SEQUENCE or LINE"),
    ("a.madx", "l: line=(q, nope);\nq: quadrupole, l=1;", "nope, which is not defined"),
    ("a.madx", "q: quadrupole, l=1, k1=1 +* 2;\nl: line=(q);", "cannot read the expression"),
    ("a.tfs", "@ NAME %s x\n* FOO BAR\n1 2", "needs the columns NAME and S"),
    ("a.xyz", "nothing a simulator wrote", "cannot tell which simulator"),
])
def test_what_cannot_be_read_is_said(name, text, problem):
    with pytest.raises(bc.ConversionError) as e:
        bc.convert(name, text)
    assert problem in str(e.value)


def test_a_converter_can_be_added():
    calls = []
    bc.register(bc.Converter(name="toy", label="Toy", extensions=(".toy",), detect=lambda t: t.startswith("TOY"),
                             convert=lambda text, filename, o: calls.append(filename) or conv("dafne_accumulator.madx")))
    try:
        assert bc.find("x.toy", "TOY").name == "toy"
        assert bc.convert("x.toy", "TOY")["paths"][0]["topology"] == "closed" and calls == ["x.toy"]
    finally:
        bc._REGISTRY.pop("toy")


def test_a_converted_file_imports_through_the_api(db_world):
    from tests.test_beam_model import client
    h = db_world
    formats = {f["name"] for f in client.get("/v1/beam-model/formats", headers=h).json()}
    assert {"argus", "madx", "madx-tfs", "elegant", "bmad", "xsuite", "at"} <= formats
    assert client.get("/v1/beam-model/schema", headers=h).json()["title"].startswith("ARGUS canonical beam model")
    out = client.post("/v1/beam-model/convert", headers=h, json={
        "filename": "dafne_accumulator_twiss.tfs", "content": (F / "dafne_accumulator_twiss.tfs").read_text(),
        "options": {"model_id": "acc-twiss", "system_kind": "Accumulator"}}).json()
    assert out["check"]["ok"] and out["report"]["ring"] and out["model"]["systems"][0]["kind"] == "Accumulator"
    done = client.post("/v1/beam-model/import", headers=h, json=out["model"])
    assert done.status_code == 200, done.text
    ring = next(p for p in client.get("/v1/beam-paths", headers=h).json() if p["name"] == "ACC")
    graph = client.get(f"/v1/beam-paths/{ring['uid']}/graph", headers=h).json()
    q = next(n for n in graph["nodes"] if n["name"] == "QUAA101")
    assert q["optics"]["beta_x"] > 0 and q["geometry"]["yaw"] is not None and graph["topology"] == "closed"
    dip = next(n for n in graph["nodes"] if n["name"] == "DIPA11")
    assert dip["angle"] == pytest.approx(math.pi / 4)
    bad = client.post("/v1/beam-model/convert", headers=h, json={"filename": "x.madx", "content": "q: quadrupole;"})
    assert bad.status_code == 422


@pytest.fixture()
def db_world():
    import secrets
    import uuid
    from app.auth import OidcIdentity, get_identity
    from app.db import SessionLocal
    from app.main import app
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.services.asset_types import ensure_asset_types
    t = secrets.token_hex(4)
    ws = f"bmc-{t}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name="Converters"))
    db.flush()
    ensure_asset_types(db, ws)
    admin = User(id=str(uuid.uuid4()), email=f"bmc-{t}@argus.test", is_admin=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    db.close()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
    yield {"X-Workspace-Id": ws}
    app.dependency_overrides.pop(get_identity, None)
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    db.delete(db.get(Workspace, ws))
    db.commit()
    db.close()


def test_bmad_reads_variables_inheritance_parameters_and_limits():
    text = """
    parameter[particle] = proton
    parameter[p0c] = 2.0e9
    kq = 1.5   ! a variable
    qf: quadrupole, l = 0.4, k1 = kq
    qd: qf, k1 = -kq            ! inherits l
    b1: sbend, l = 2.0, g = 0.05
    col: rcollimator, l = 0.2, x_limit = 0.02, y_limit = 0.005
    call, file = more.bmad
    d: drift, l = 0.5
    cell: line = (qf, d, b1, d, qd, col)
    use, cell
    """
    d = bc.convert("cell.bmad", text)
    _doc, rep = valid(d)
    assert order(d) == ["QF", "B1", "QD", "COL"]
    v = d["datasets"][0]["values"]
    assert v["QD"]["physics"] == {"length": 0.4, "k1": -1.5} and v["B1"]["physics"]["angle"] == pytest.approx(0.1)
    assert v["B1"]["s"] == pytest.approx(0.9)
    by = comps(d)
    assert by["QD"]["family"] == "QF" and by["QD"]["native"]["location"] == "cell.bmad:6"
    assert by["COL"]["boundaries"][0]["profile"] == {"shape": "rectangle", "half_width_x": 0.02, "half_height_y": 0.005}
    assert d["beams"][0]["species"] == "proton" and d["beams"][0]["reference_energy"] == pytest.approx(2.0)
    assert any("call" in x for x in d["conversion"]["not_executed"])


def test_xsuite_reads_a_line_with_apertures():
    line = {"element_names": ["ap0", "q1", "d1", "mb", "d2", "mcb1", "ip"],
            "elements": {"ap0": {"__class__": "LimitEllipse", "a": 0.03, "b": 0.02},
                         "q1": {"__class__": "Quadrupole", "length": 0.5, "k1": 0.8},
                         "d1": {"__class__": "Drift", "length": 1.0},
                         "mb": {"__class__": "Bend", "length": 2.0, "angle": 0.02},
                         "d2": {"__class__": "Drift", "length": 0.5},
                         "mcb1": {"__class__": "Multipole", "knl": [1e-4], "ksl": [0.0]},
                         "ip": {"__class__": "Marker"}},
            "particle_ref": {"mass0": 938.27208816e6, "q0": 1.0, "p0c": [7e12]}}
    import json
    d = bc.convert("lhc.json", json.dumps(line), bc.Options(keep_markers=True))
    doc, rep = valid(d)
    assert order(d) == ["Q1", "MB", "MCB1", "IP"]
    assert comps(d)["MCB1"]["type"] == "corrector" and comps(d)["IP"]["type"] == "marker"
    assert d["datasets"][0]["values"]["MB"]["s"] == pytest.approx(1.5)
    assert d["boundaries"][0]["profile"]["shape"] == "ellipse" and d["boundaries"][0]["path"] == d["paths"][0]["id"]
    assert d["beams"][0]["species"] == "proton" and d["beams"][0]["reference_momentum"] == pytest.approx(7000)
    from app.beam_model_core.queries import limiting_aperture
    assert limiting_aperture(doc, d["paths"][0]["id"])["limit_y"]["value"] == 0.02


def test_accelerator_toolbox_reads_families_polynomials_and_apertures():
    import json
    lattice = {"atjson": 1, "properties": {"name": "ring", "energy": 3e9, "particle": {"name": "electron"}},
               "elements": [{"Class": "Quadrupole", "FamName": "QF", "Length": 0.3, "PolynomB": [0, 1.2],
                             "PassMethod": "StrMPoleSymplectic4Pass", "EApertures": [0.03, 0.015]},
                            {"Class": "Drift", "FamName": "DR", "Length": 1.0, "PassMethod": "DriftPass"},
                            {"Class": "Sextupole", "FamName": "SF", "Length": 0.2, "PolynomB": [0, 0, 5.0],
                             "PassMethod": "StrMPoleSymplectic4Pass"},
                            {"Class": "Quadrupole", "FamName": "QF", "Length": 0.3, "PolynomB": [0, 1.2],
                             "PassMethod": "StrMPoleSymplectic4Pass"},
                            {"Class": "RFCavity", "FamName": "RF", "Length": 0, "Voltage": 1e6, "Frequency": 5e8,
                             "HarmNumber": 400, "PassMethod": "RFCavityPass"}]}
    d = bc.convert("ring.json", json.dumps(lattice))
    valid(d)
    assert order(d) == ["QF", "SF", "QF#2", "RF"]
    by = comps(d)
    assert by["QF#2"]["definition"] == "QF" and by["QF"]["boundaries"][0]["profile"]["semi_axis_y"] == 0.015
    v = d["datasets"][0]["values"]
    assert v["SF"]["physics"]["k2"] == pytest.approx(10.0)                    # PolynomB[2] is k2/2
    assert v["RF"]["physics"]["harmonic"] == 400 and d["beams"][0]["reference_energy"] == pytest.approx(3.0)


# --- A file with several sequences: one model, a path each, an element once --------------------------------

MULTI = """
Q1: QUADRUPOLE, L=0.2, K1=1.5;
B_IN: SBEND, L=1.0, ANGLE=-PI/4;
B_OUT: SBEND, L=1.0, ANGLE=+PI/4;
M1: MARKER;
CLASH: QUADRUPOLE, L=0.2;
INJ: SEQUENCE, L=5, REFER=CENTRE;
  START_I: MARKER, AT=0;
  Q1, AT=1;
  B_IN, AT=2;
  M1, AT=3;
ENDSEQUENCE;
EXT: SEQUENCE, L=4, REFER=CENTRE;
  START_E: MARKER, AT=0;
  B_OUT, AT=1;
  Q1, AT=3;
ENDSEQUENCE;
"""


def test_every_sequence_becomes_a_path_and_an_element_stays_one_component():
    d = bc.convert("transfer.seq", MULTI)
    report = d.pop("conversion")
    valid(d)
    assert d["model"]["id"] == "transfer" and len(d["systems"]) == 1
    assert [p["id"] for p in d["paths"]] == ["inj", "ext"] and {p["system"] for p in d["paths"]} == {"transfer"}
    ids = [c["id"] for c in d["components"]]
    assert len(ids) == len(set(ids)) and ids.count("Q1") == 1
    assert report["sequences"] == ["inj", "ext"] and report["elements"] == len(ids) and report["placements"] == 7
    values = {x["path"]: x["values"] for x in d["datasets"]}
    assert values["inj"]["Q1"]["s"] == pytest.approx(0.9) and values["ext"]["Q1"]["s"] == pytest.approx(2.9)
    assert report["differs"] == [] and report["conflicts"] == []


def test_name_endings_make_one_magnet_that_keeps_its_angle_on_each_path():
    apart = comps(bc.convert("transfer.seq", MULTI))
    assert "B_IN" in apart and "B_OUT" in apart and "B" not in apart, "only when asked"
    d = bc.convert("transfer.seq", MULTI, bc.Options(same_element_suffixes="_IN, _OUT"))
    report = d.pop("conversion")
    valid(d)
    by = comps(d)
    assert "B" in by and "B_IN" not in by and "B_OUT" not in by
    values = {x["path"]: x["values"]["B"] for x in d["datasets"]}
    assert values["inj"]["physics"]["angle"] == pytest.approx(-math.pi / 4)
    assert values["ext"]["physics"]["angle"] == pytest.approx(math.pi / 4)
    assert values["inj"]["native"]["name"] == "B_IN", "the label in the file can still be found"
    assert [(x["component"], x["parameter"]) for x in report["differs"]] == [("B", "angle")]


def test_the_longest_ending_is_taken_first():
    text = "D_TL_IN: SBEND, L=1, ANGLE=0.1; D_TR_OUT: SBEND, L=1, ANGLE=0.2;" \
           "A: SEQUENCE, L=2; D_TL_IN, AT=1; ENDSEQUENCE; B: SEQUENCE, L=2; D_TR_OUT, AT=1; ENDSEQUENCE;"
    d = bc.convert("t.seq", text, bc.Options(same_element_suffixes="_IN, _OUT, _TL_IN, _TR_OUT"))
    assert [c["id"] for c in d["components"]] == ["D"]


def test_a_name_with_two_types_is_reported_and_the_first_stays():
    text = MULTI + """
    A1: QUADRUPOLE, L=0.2;
    A1_X: SBEND, L=0.2, ANGLE=0.1;
    TWO: SEQUENCE, L=1; A1, AT=0.5; ENDSEQUENCE;
    THREE: SEQUENCE, L=1; A1_X, AT=0.5; ENDSEQUENCE;
    """
    d = bc.convert("transfer.seq", text, bc.Options(same_element_suffixes="_X"))
    report = d.pop("conversion")
    assert report["conflicts"] == [{"component": "A1", "kept": "quadrupole", "also": "dipole", "path": "three"}]
    assert comps(d)["A1"]["type"] == "quadrupole"


def test_one_sequence_can_still_be_chosen_and_use_still_chooses():
    only = bc.convert("transfer.seq", MULTI, bc.Options(beamline="inj"))
    assert [p["id"] for p in only["paths"]] == ["inj"]
    assert only["conversion"]["sequences"] == ["inj", "ext"] and only["conversion"]["chosen"] == "inj"
    used = bc.convert("transfer.seq", MULTI + "USE, SEQUENCE=EXT;")
    assert [p["id"] for p in used["paths"]] == ["ext"]


def test_a_file_with_one_sequence_reads_as_before():
    d = bc.convert("tl.seq", "Q: QUADRUPOLE, L=1; S: SEQUENCE, L=2; Q, AT=1; ENDSEQUENCE;")
    assert [p["id"] for p in d["paths"]] == ["s"] and "sequences" not in d["conversion"]
    assert d["systems"][0]["id"] == "s"


def test_a_multi_sequence_file_imports_as_one_record_per_element(db_world):
    from tests.test_beam_model import client
    h = db_world
    out = client.post("/v1/beam-model/convert", headers=h, json={
        "filename": "transfer.seq", "content": MULTI, "options": {"same_element_suffixes": "_IN,_OUT"}}).json()
    assert out["check"]["ok"], out["check"]
    done = client.post("/v1/beam-model/import", headers=h, json=out["model"])
    assert done.status_code == 200, done.text
    paths = [p for p in client.get("/v1/beam-paths", headers=h).json() if p["name"] in ("INJ", "EXT")]
    assert len(paths) == 2
    nodes = {p["name"]: {n["name"]: n for n in client.get(f"/v1/beam-paths/{p['uid']}/graph", headers=h).json()["nodes"]}
             for p in paths}
    assert nodes["INJ"]["Q1"]["uid"] == nodes["EXT"]["Q1"]["uid"], "one record on both paths"
    assert nodes["INJ"]["B"]["uid"] == nodes["EXT"]["B"]["uid"]
    assert nodes["INJ"]["B"]["angle"] == pytest.approx(-math.pi / 4)
    assert nodes["EXT"]["B"]["angle"] == pytest.approx(math.pi / 4)
    assert nodes["EXT"]["Q1"]["s"] == pytest.approx(2.9)
