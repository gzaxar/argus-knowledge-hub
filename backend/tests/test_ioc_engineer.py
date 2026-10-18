"""The IOC engineer: the catalogue read from an infn-epics-ioc checkout, and the tools that answer from it.

Two things matter. That a render here fails where the pod would fail — an entity type the image does not
compile, a missing parameter, a template the image does not have — because the point is to find that out
before an ArgoCD sync rather than after. And that what passes here is what the pod renders: the same
template resolution and the same Jinja2 semantics as jnjrender, so an empty variable stays empty.
"""
import json
import textwrap

import pytest

from app.ioc_engineer import catalog, tools
from app.services import mcp_tools


def _write(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")


@pytest.fixture()
def checkout(tmp_path, monkeypatch):
    """A tiny infn-epics-ioc: one driver built into the image, one only commented out, one template."""
    repo = tmp_path / "infn-epics-ioc"
    _write(repo, "Dockerfile", """
        WORKDIR ${SOURCE_FOLDER}/ibek-support-infn
        COPY ibek-support-infn/ ./
        RUN ansible.sh gauge && \\
            ansible.sh other
        # RUN ansible.sh legacy
    """)
    _write(repo, "ibek-support-infn/gauge/gauge.install.yml", """
        module: gauge-ioc
        organization: https://github.com/infn-epics/
        version: v1.2
        dbds: [asyn.dbd, stream.dbd]
        libs: [asyn, stream]
    """)
    _write(repo, "ibek-support-infn/gauge/gauge.ibek.support.yaml", """
        module: gauge
        entity_models:
          - name: controller
            description: A gauge controller
            parameters:
              name: {type: id, description: Asyn port}
              IP: {type: str, description: Address, default: 127.0.0.1}
              PORT: {type: int, description: TCP port, default: 4001}
            pre_init:
              - value: drvAsynIPPortConfigure("{{name}}", "{{IP}}:{{PORT}}")
          - name: sensor
            description: One channel
            parameters:
              controller: {type: object, description: The controller}
              P: {type: str, description: Prefix}
              unit: {type: enum, description: Unit, values: {mbar: null, Pa: null}, default: mbar}
            databases:
              - file: gauge.template
                args: {P: null, PORT: "{{controller}}"}
    """)
    _write(repo, "ibek-support-infn/legacy/legacy.install.yml", "module: legacy\norganization: https://x/\n")
    _write(repo, "ibek-support-infn/legacy/legacy.ibek.support.yaml", """
        module: legacy
        entity_models:
          - name: device
            description: Old
            parameters: {P: {type: str, description: Prefix}}
    """)
    _write(repo, "ibek-support/_ansible/epics.ibek.support.yaml", """
        module: epics
        entity_models:
          - name: PostStartupCommand
            description: After iocInit
            parameters: {command: {type: str, description: Command, default: ""}}
    """)
    _write(repo, "ibek-templates/templates/vac/gauge/gauge.yaml.j2", """
        ioc_name: {{ iocname }}
        description: gauges
        entities:
        - type: gauge.controller
          name: "{{ iocname }}_port"
          IP: "{{ server }}"
          PORT: {{ port | default(4001) }}
        {%- for d in devices %}
        - type: gauge.sensor
          controller: "{{ iocname }}_port"
          P: "{{ iocprefix }}:{{ d.name }}"
        {%- if devtype == "legacy" %}
        - type: legacy.device
          P: "{{ iocprefix }}"
        {%- elif devtype == "tpg" %}
        {%- endif %}
        {%- endfor %}
        - type: epics.PostStartupCommand
          command: dbl
    """)
    _write(repo, "ibek-templates/tests/vac-gauge-test.yaml", """
        iocname: vac-gauge-test
        template: gauge
        devtype: tpg
        iocprefix: TEST:VAC
        server: 10.0.0.1
        devices:
          - name: G1
    """)
    _write(repo, "docs/architecture.md", "# Arch\n\n## 1. The big picture\n\nOne image.\n\n## 3. ibek-support-infn\n\nDrivers.\n")
    # A multi-source beamline, as SPARC and BTF are: two value files, iocDefaults per template, iocparam.
    line = tmp_path / "epik8s-test"
    _write(line, "deploy/templates/epik8.yaml", """
        spec:
          sources:
            - helm:
                valueFiles:
                  - $beamline/deploy/values.yaml
                  - $beamline/deploy/values-vac.yaml
    """)
    _write(line, "deploy/values.yaml", """
        beamline: testline
        ioc_version: v9.9
        iocDefaults:
          gauge: {devtype: tpg, autosync: true, port: 4002}
        epicsConfiguration:
          iocs:
            vgauge01: {name: vgauge01, template: gauge, iocprefix: TL:VAC, devices: [{name: G1}], autosync: false,
                       devgroup: vac}
    """)
    _write(line, "deploy/values-vac.yaml", """
        epicsConfiguration:
          iocs:
            vgauge01: {name: vgauge01, template: gauge, iocprefix: TL:VAC, devices: [{name: G1}], autosync: false,
                       iocparam: [{name: server, value: 10.2.2.2}]}
            vgauge02: {name: vgauge02, template: gauge, devtype: legacy, iocprefix: TL:VAC, server: h,
                       devices: [{name: G9}]}
            remote01: {name: remote01, template: gauge, host: box.example.org}
            off01: {name: off01, template: gauge, disable: true}
    """)
    out = tmp_path / "catalog.json.gz"
    catalog.write(catalog.build(repo, beamlines=(str(line),)), out)
    monkeypatch.setenv("ARGUS_IOC_CATALOG", str(out))
    catalog.load.cache_clear()
    yield repo
    catalog.load.cache_clear()


def test_the_catalogue_says_where_a_driver_comes_from_and_whether_the_image_has_it(checkout):
    m = tools.ioc_get_module(None, "ws", "gauge")
    assert m["found"] and m["git_url"] == "https://github.com/infn-epics/gauge-ioc.git" and m["version"] == "v1.2"
    assert m["built"]["in_image"] and m["built"]["dockerfile"] == "Dockerfile"
    assert {e["type"] for e in m["entity_models"]} == {"gauge.controller", "gauge.sensor"}
    assert m["templates_using_it"] == ["gauge"]
    legacy = tools.ioc_get_module(None, "ws", "legacy")
    assert not legacy["built"]["in_image"] and legacy["built"]["commented_out_in"] == ["Dockerfile"]


def test_an_entity_model_comes_with_its_parameters_and_availability(checkout):
    e = tools.ioc_get_entity_model(None, "ws", "gauge.sensor")
    assert e["parameters"]["controller"] == {"type": "object", "description": "The controller", "required": True}
    assert e["parameters"]["unit"]["values"] == ["mbar", "Pa"]
    assert e["availability"]["in_image"]
    missing = tools.ioc_get_entity_model(None, "ws", "gauge.nope")
    assert not missing["found"] and "gauge.sensor" in missing["same_module"]


def test_the_template_knows_its_branches_and_what_it_emits(checkout):
    t = tools.ioc_get_template(None, "ws", "gauge")
    assert t["devtypes"] == ["legacy", "tpg"]
    emits = {e["type"]: e["in_image"] for e in t["emits"]}
    assert emits == {"epics.PostStartupCommand": True, "gauge.controller": True, "gauge.sensor": True,
                     "legacy.device": False}
    assert t["examples"] == ["vac-gauge-test"] and t["resolution"]["kind"] == "file"


def test_a_good_entry_renders_and_passes(checkout):
    fixture = tools.ioc_get_example(None, "ws", "vac-gauge-test")["source"]
    r = tools.ioc_render(None, "ws", fixture)
    assert r["ok"], r
    out = r["outputs"][0]
    assert out["entities"] == ["gauge.controller", "gauge.sensor", "epics.PostStartupCommand"]
    assert 'IP: "10.0.0.1"' in out["yaml"] and out["rendered_empty"] == []


def test_a_branch_the_image_does_not_compile_fails_before_the_pod_does(checkout):
    r = tools.ioc_render(None, "ws", "template: gauge\ndevtype: legacy\niocprefix: T\nserver: h\ndevices: [{name: A}]\n")
    assert not r["ok"]
    assert any("legacy.device is defined but not compiled into the image" in e for e in r["outputs"][0]["errors"])


def test_a_missing_key_is_named_rather_than_silently_rendered_as_nothing(checkout):
    r = tools.ioc_render(None, "ws", "template: gauge\ndevtype: tpg\niocprefix: T\ndevices: [{name: A}]\n")
    assert "server" in r["outputs"][0]["rendered_empty"]
    assert any("iocname is injected by epik8s-chart" in n for n in r["notes"])


def test_an_unquoted_missing_value_is_a_null_ibek_refuses(checkout):
    source = "ioc_name: x\nentities:\n- type: gauge.controller\n  name: p\n  IP: {{ ip }}\n"
    r = tools.ioc_render(None, "ws", "iocname: x\n", template_source=source)
    assert not r["ok"] and r["outputs"][0]["rendered_empty"] == ["ip"]
    assert any(".IP is empty (null)" in e for e in r["outputs"][0]["errors"])


def test_a_pasted_beamline_block_is_read_as_its_one_ioc(checkout):
    block = """
    epicsConfiguration:
      iocs:
        vgauge01:
          template: gauge
          devtype: tpg
          iocprefix: SPARC:VAC
          server: 10.0.0.2
          devices: [{name: G1}, {name: G2}]
    """
    r = tools.ioc_render(None, "ws", textwrap.dedent(block))
    assert r["ok"] and r["outputs"][0]["yaml"].startswith("ioc_name: vgauge01")


def test_an_iocs_entry_pasted_with_its_name_is_read_as_that_ioc(checkout):
    r = tools.ioc_render(None, "ws", "vgauge02:\n  template: gauge\n  devtype: tpg\n  iocprefix: T\n"
                                     "  server: h\n  devices: [{name: A}]\n")
    assert r["ok"] and r["outputs"][0]["yaml"].startswith("ioc_name: vgauge02")


def test_an_unknown_template_is_exit_code_seven(checkout):
    r = tools.ioc_render(None, "ws", "template: nothing-like-it\n")
    assert not r["ok"] and "code 7" in r["errors"][0]


def test_the_instance_check_finds_what_ibek_would_refuse(checkout):
    report = tools.ioc_validate(None, "ws", textwrap.dedent("""
        ioc_name: x
        entities:
          - {type: gauge.controller, name: p1, PORT: "four"}
          - {type: gauge.controller, name: p1}
          - {type: gauge.sensor, controller: p9, P: X, unit: bar, colour: red}
          - {type: gauge.sensor, controller: p1}
          - {type: gauge.nothing}
    """))
    errors = " | ".join(report["errors"])
    assert "PORT expects an int" in errors
    assert "id 'p1' is already used" in errors
    assert "unit must be one of ['mbar', 'Pa']" in errors
    assert "refers to 'p9'" in errors
    assert "missing required parameter P" in errors
    assert "unknown entity type gauge.nothing; module gauge defines gauge.controller, gauge.sensor" in errors
    assert any("colour" in w for w in report["warnings"])


def test_the_sandbox_keeps_values_from_reaching_python(checkout):
    r = tools.ioc_render(None, "ws", "iocname: x\n",
                         template_source="{{ ''.__class__.__mro__[1].__subclasses__() }}")
    assert not r["ok"] and "SecurityError" in r["outputs"][0]["error"]


def test_a_scaffolded_driver_agrees_with_itself(checkout):
    s = tools.ioc_scaffold_driver(None, "ws", folder="newgauge", repository="newgauge-ioc", protocol="stream",
                                  group="vac", db_template="newgauge.template")
    assert set(s["files"]) == {
        "ibek-support-infn/newgauge/newgauge.install.yml",
        "ibek-support-infn/newgauge/newgauge.ibek.support.yaml",
        "ibek-templates/templates/vac/newgauge/newgauge.yaml.j2",
        "ibek-templates/tests/vac-newgauge-test.yaml",
    }
    assert s["self_check"]["ok"], s["self_check"]
    assert "module: newgauge-ioc" in s["files"]["ibek-support-infn/newgauge/newgauge.install.yml"]
    assert "ansible.sh newgauge" in s["dockerfile"]


def test_search_and_guide(checkout):
    hits = tools.ioc_search(None, "ws", "gauge")["results"]
    assert {h["kind"] for h in hits} >= {"module", "entity_model", "template", "example"}
    guide = tools.ioc_guide(None, "ws", "ibek-support-infn")
    assert guide["section"].startswith("3.") and "Drivers." in guide["text"]


def test_the_tools_are_served_over_mcp_and_to_ask_argus(checkout):
    names = {t["name"] for t in mcp_tools.catalogue()}
    assert {"ioc_search", "ioc_get_module", "ioc_get_entity_model", "ioc_get_template", "ioc_get_example",
            "ioc_render", "ioc_validate", "ioc_scaffold_driver", "ioc_guide", "ioc_list_beamline",
            "ioc_get_beamline_ioc", "ioc_check_beamline"} <= names
    found = json.loads(mcp_tools.call(None, "ws", "ioc_get_module", {"name": "gauge-ioc"}))
    assert found["found"] and found["folder"] == "gauge"


def test_the_bundled_snapshot_renders_its_own_fixtures(monkeypatch):
    """The snapshot that ships: the fixtures of templates whose drivers the image builds render clean."""
    monkeypatch.delenv("ARGUS_IOC_CATALOG", raising=False)
    catalog.load.cache_clear()
    try:
        cat = catalog.load()
        assert len(cat["templates"]) > 20 and len(cat["entity_models"]) > 300
        assert any(b["name"] == "eli" and len(b["iocs"]) > 20 for b in cat["beamlines"])
        for name in ("ps-ocem-modbusps-test", "ps-tti-test", "agilent-vac-xgs600-test", "motor-pigcs2-test"):
            r = tools.ioc_render(None, "ws", tools.ioc_get_example(None, "ws", name)["source"])
            assert r["ok"], (name, r)
    finally:
        catalog.load.cache_clear()


def test_a_beamline_is_read_from_its_value_files_in_order(checkout):
    listed = tools.ioc_list_beamline(None, "ws")
    assert [b["name"] for b in listed["beamlines"]] == ["testline"]
    line = tools.ioc_list_beamline(None, "ws", "testline")
    assert line["value_files"] == ["deploy/values.yaml", "deploy/values-vac.yaml"]
    modes = {r["name"]: (r["mode"], r["disabled"]) for r in line["iocs"]}
    assert modes == {"off01": ("template", True), "remote01": ("host", False), "vgauge01": ("template", False),
                     "vgauge02": ("template", False)}


def test_an_ioc_is_given_what_the_chart_and_the_configmap_give_it(checkout):
    ioc = tools.ioc_get_beamline_ioc(None, "ws", "testline", "vgauge01")
    d = ioc["deployed"]
    assert ioc["defaults_key"] == "gauge" and d["devtype"] == "tpg" and d["port"] == 4002
    assert d["server"] == "10.2.2.2" and d["devgroup"] == "vac"  # iocparam; the files' maps merged
    assert d["iocname"] == "vgauge01" and d["beamline"] == "testline" and d["ioc_version"] == "v9.9"
    assert d["config_dir"] == "/epics/ioc/config"
    # Sprig's mergeOverwrite: false in the entry never replaces true from iocDefaults.
    assert d["autosync"] is True and any("autosync: False" in x for x in ioc["ignored_by_merge"])
    assert ioc["render"]["ok"] and "PORT: 4002" in ioc["render"]["outputs"][0]["yaml"]


def test_a_beamline_check_names_what_its_next_sync_would_break(checkout):
    report = tools.ioc_check_beamline(None, "ws", "testline")
    assert report["passed"] == 1
    assert [f["ioc"] for f in report["failed"]] == ["vgauge02"]
    assert "legacy.device is defined but not compiled" in report["failed"][0]["errors"][0]
    assert {s["ioc"]: s["why"] for s in report["skipped"]} == {"off01": "disabled", "remote01": "host"}
    assert report["ignored_by_merge"][0]["ioc"] == "vgauge01"


def test_a_new_entry_can_be_rendered_with_a_beamlines_defaults(checkout):
    r = tools.ioc_render(None, "ws", "name: vgauge09\ntemplate: gauge\niocprefix: TL\nserver: s\ndevices: [{name: A}]\n",
                         beamline="testline")
    assert r["ok"] and any("iocDefaults.gauge of testline" in n for n in r["notes"])
    assert "PORT: 4002" in r["outputs"][0]["yaml"]


def test_a_published_catalogue_is_fetched_and_its_last_copy_kept(checkout, tmp_path, monkeypatch):
    import gzip as gz
    import requests

    body = (tmp_path / "catalog.json.gz").read_bytes()
    calls = []

    class Response:
        def __init__(self, content, status=200):
            self.content, self.status_code = content, status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(str(self.status_code))

    monkeypatch.setattr(requests, "get", lambda url, timeout: calls.append(url) or Response(body))
    monkeypatch.setenv("ARGUS_IOC_CATALOG", "https://example.org/ioc-catalog.json.gz")
    monkeypatch.setenv("ARGUS_IOC_CATALOG_CACHE", str(tmp_path / "cache" / "c.json.gz"))
    monkeypatch.setenv("ARGUS_IOC_CATALOG_TTL", "0")
    catalog.load.cache_clear()
    assert catalog.load()["loaded_from"].startswith("https://example.org/")
    assert tools.ioc_get_module(None, "ws", "gauge")["found"]
    # GitHub down: the last copy fetched answers, and says so.
    monkeypatch.setattr(requests, "get", lambda url, timeout: Response(b"", 503))
    later = catalog.load()
    assert later["loaded_from"].endswith("c.json.gz") and "could not fetch" in later["problems"][0]
    assert tools.ioc_get_module(None, "ws", "gauge")["found"] and calls
    assert gz.decompress((tmp_path / "cache" / "c.json.gz").read_bytes())
