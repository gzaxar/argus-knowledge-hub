"""The IOC engineer and Python IOCs (epik8s-pyioc).

A Python IOC has no template: its entry is checked against the IOC's own pyioc.yaml with the library
pyioc-run uses at pod start, so a check here fails where the pod would. The catalogue reads the IOC's
repository like pyioc-run finds the spec (the package's epik8s.pyioc entry point), and the scaffold is the
generator `pyioc init` uses.
"""
import textwrap

import pytest

from app.ioc_engineer import catalog, tools
from app.services import mcp_tools

pytest.importorskip("epik8s_pyioc")


def _write(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")


@pytest.fixture()
def pyioc_catalog(tmp_path, monkeypatch):
    repo = tmp_path / "infn-epics-ioc"
    _write(repo, "docs/architecture.md", "# Arch\n\n## 1. The big picture\n\nOne image.\n")
    ioc = tmp_path / "spectro"
    _write(ioc, "pyproject.toml", """
        [project]
        name = "spectro-ioc"
        version = "0.3.0"
        [project.entry-points."epik8s.pyioc"]
        spectro = "spectro_ioc"
    """)
    _write(ioc, "src/spectro_ioc/pyioc.yaml", """
        pyioc: 1
        name: spectro
        description: Compact spectrometer
        devgroup: diag
        image: ghcr.io/infn-epics/spectro
        version: 0.3.0
        entrypoint: spectro_ioc.ioc:run
        protocols: [ca]
        parameters:
          log_level: {type: enum, choices: [DEBUG, INFO], default: INFO}
        devices:
          multiple: true
          parameters:
            server: {type: host, aliases: [ip]}
            exposure: {type: float, default: 8.3, min: 0.01, max: 30000, unit: ms}
            trigger_mode: {type: enum, choices: [free, hardware], default: free}
    """)
    _write(ioc, "README.md", "# spectro\n\nA compact spectrometer IOC.\n")
    _write(ioc, "example.yaml", "devtype: spectro\niocprefix: TEST:SPEC\nsimulate: true\n")
    line = tmp_path / "epik8s-line"
    _write(line, "deploy/values.yaml", """
        beamline: testline
        iocDefaults:
          spectro: {devtype: spectro, image: "ghcr.io/infn-epics/spectro:0.3.0", start: pyioc-run, pva: false}
        epicsConfiguration:
          iocs:
            good01: {devtype: spectro, iocprefix: TL:DIAG, server: 10.0.0.5, devices: [{name: CCT01}]}
            bad01: {devtype: spectro, iocprefix: TL:DIAG, exposure: fast,
                    devices: [{name: CCT02, trigger_mode: sometimes, exposre: 3}]}
            tmpl01: {devtype: spectro, template: spectro, iocprefix: TL:DIAG}
            soft01: {devtype: softioc, iocdir: klyloop, iocprefix: TL:SOFT}
    """)
    out = tmp_path / "catalog.json.gz"
    catalog.write(catalog.build(repo, beamlines=(str(line),), pyiocs=(str(ioc),), workdir=tmp_path / "work"), out)
    monkeypatch.setenv("ARGUS_IOC_CATALOG", str(out))
    catalog.load.cache_clear()
    yield
    catalog.load.cache_clear()


def test_the_catalogue_reads_a_python_ioc_like_pyioc_run_finds_it(pyioc_catalog):
    (entry,) = catalog.load()["pyiocs"]
    assert entry["name"] == "spectro"
    assert entry["spec_path"] == "src/spectro_ioc/pyioc.yaml"      # through the entry point
    assert entry["example"].startswith("devtype: spectro") and "compact" in entry["readme"]
    assert entry["problems"] == []


def test_search_and_get_a_python_ioc(pyioc_catalog):
    hits = tools.ioc_search(None, "", "spectrometer")["results"]
    assert {"kind": "pyioc", "name": "spectro"}.items() <= hits[0].items()
    got = tools.ioc_get_pyioc(None, "", "spectro")
    assert got["found"] and got["image"] == "ghcr.io/infn-epics/spectro"
    exposure = next(p for p in got["devices"]["parameters"] if p["name"] == "exposure")
    assert exposure["min"] == 0.01 and exposure["unit"] == "ms" and exposure["default"] == 8.3
    assert "start: pyioc-run" in got["ioc_defaults"] and "pva: false" in got["ioc_defaults"]
    assert {d["ioc"] for d in got["deployed"]} >= {"good01", "bad01"}
    assert not tools.ioc_get_pyioc(None, "", "nothing")["found"]


def test_a_python_ioc_entry_is_checked_as_pyioc_run_will(pyioc_catalog):
    ok = tools.ioc_render(None, "", "cct01: {devtype: spectro, iocprefix: SL:DIAG, devices: [{name: CCT01}]}")
    assert ok["ok"] and ok["kind"] == "pyioc", ok
    assert ok["resolved"]["devices"][0]["prefix"] == "SL:DIAG:CCT01:"
    assert any("iocDefaults" in n for n in ok["notes"])            # the published defaults were applied
    bad = tools.ioc_render(None, "", {"devtype": "spectro", "iocprefix": "X", "exposure": 0,
                                      "trigger_mode": "sometimes"})
    assert not bad["ok"]
    text = " ".join(bad["errors"])
    assert "exposure" in text and "trigger_mode" in text


def test_a_beamline_check_covers_its_python_iocs(pyioc_catalog):
    report = tools.ioc_check_beamline(None, "", "testline")
    failed = {f["ioc"]: f for f in report["failed"]}
    assert "good01" not in failed and report["passed"] >= 1
    assert any("exposure" in e for e in failed["bad01"]["errors"])
    assert "tmpl01" in failed                                       # template: sends it down the ibek branch
    assert {"ioc": "soft01", "why": "git"} in report["skipped"]
    one = tools.ioc_get_beamline_ioc(None, "", "testline", "good01")
    assert one["mode"] == "pyioc" and one["render"]["ok"]
    rows = {r["name"]: r for r in tools.ioc_list_beamline(None, "", "testline")["iocs"]}
    assert rows["good01"]["mode"] == "pyioc" and rows["soft01"]["mode"] == "git"


def test_scaffold_a_python_ioc(pyioc_catalog):
    out = tools.ioc_scaffold_pyioc(None, "", {
        "name": "tpg366", "devgroup": "vac", "transport": "tcp", "default_port": 8000,
        "pvs": [{"name": "Pressure", "type": "float", "access": "ro", "unit": "mbar"},
                {"name": "Unit", "type": "enum", "access": "rw", "choices": ["mbar", "Torr"]},
                {"name": "Reset", "type": "bool", "access": "cmd"}]})
    assert out["self_check"]["ok"], out["self_check"]
    assert "src/tpg366_ioc/ioc.py" in out["files"] and "tests/test_ioc.py" in out["files"]
    assert "start: pyioc-run" in out["ioc_defaults"] and out["already_exists"] is None
    bad = tools.ioc_scaffold_pyioc(None, "", "name: Bad Name\npvs: []\n")
    assert bad["errors"] and bad["example"]["name"] == "tpg366"


def test_the_guide_serves_the_python_ioc_documentation(pyioc_catalog):
    g = tools.ioc_guide(None, "", "pitfalls")
    assert g["section"].startswith("Python IOCs") and "enum_index" in g["text"]
    assert any(s.startswith("Python IOCs: How to") for s in tools.ioc_guide(None, "")["sections"])
    assert tools.ioc_guide(None, "")["catalogue"]["pyiocs"] == ["spectro"]
    by_text = tools.ioc_guide(None, "", "phoebus")          # in no title, in the pitfalls' text
    assert any(k.startswith("Python IOCs: Pitfalls") for k in by_text["mentioned_in"])


def test_the_tools_are_offered_over_mcp():
    for name in ("ioc_get_pyioc", "ioc_scaffold_pyioc"):
        tool = mcp_tools.BY_NAME[name]
        assert callable(tool["handler"]) and tool["inputSchema"]["required"]
    assert "pyioc" in mcp_tools.BY_NAME["ioc_search"]["inputSchema"]["properties"]["kind"]["enum"]
