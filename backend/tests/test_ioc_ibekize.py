"""An existing IOC repository read into ibek: what its st.cmd, Makefiles and db templates say, said as
install.yml, ibek.support.yaml, a template and a fixture that render against each other.

The repositories here are small and synthetic, written the way the INFN drivers are (makeBaseApp trees with an
example st.cmd), so every inference can be checked against the line it came from.
"""
import textwrap

import pytest
import yaml

from app.ioc_engineer import ibekize


def _write(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")


@pytest.fixture()
def stream_repo(tmp_path):
    """A StreamDevice IOC: an IP port, one template loaded by st.cmd, another by a substitutions file."""
    r = tmp_path / "foo-ps"
    _write(r, "configure/RELEASE", "EPICS_BASE=/epics/base\nASYN=$(SUPPORT)/asyn\nSTREAM=$(SUPPORT)/stream\n")
    _write(r, "fooApp/src/Makefile", """
        TOP=../..
        include $(TOP)/configure/CONFIG
        PROD_IOC = foo
        DBD += foo.dbd
        foo_DBD += base.dbd
        foo_DBD += stream.dbd asyn.dbd drvAsynIPPort.dbd
        foo_LIBS += stream asyn
        foo_LIBS += $(EPICS_BASE_IOC_LIBS)
    """)
    _write(r, "fooApp/Db/Makefile", "DB += foo.template\nDB += foo.proto\nDB += ch.template\n")
    _write(r, "fooApp/Db/foo.proto", "getI { out \"I?\"; in \"%f\"; }\n")
    _write(r, "fooApp/Db/foo.template", """
        record(ai, "$(P):$(R):I_RB") { field(INP, "@foo.proto getI $(PORT)") field(SCAN, "$(SCAN=1 second)") }
        record(ao, "$(P):$(R):I_SP") { field(DRVH, "$(LIMIT)") field(PREC, "$(PREC=3)") }
    """)
    _write(r, "fooApp/Db/ch.template", 'record(ai, "$(P):$(R):CH$(N)") { field(INP, "@foo.proto getI $(PORT)") }\n')
    _write(r, "iocBoot/iocfoo/ch.substitutions", """
        file "ch.template" {
          pattern { P, R, N, PORT }
                  { SPARC, PS01, 1, FOO }
                  { SPARC, PS01, 2, FOO }
        }
    """)
    _write(r, "iocBoot/iocfoo/st.cmd", """
        #!../../bin/linux-x86_64/foo
        < envPaths
        epicsEnvSet("IPADDR", "192.168.1.50")
        epicsEnvSet("STREAM_PROTOCOL_PATH", "$(TOP)/db")
        dbLoadDatabase "$(TOP)/dbd/foo.dbd"
        foo_registerRecordDeviceDriver pdbbase
        drvAsynIPPortConfigure("FOO", "$(IPADDR):4001", 0, 0, 0)
        asynSetOption("FOO", 0, "disconnectOnReadTimeout", "Y")
        fooVendorInit("FOO", 3)
        dbLoadRecords("$(TOP)/db/foo.template", "P=SPARC,R=PS01,PORT=FOO,LIMIT=35")
        dbLoadTemplate("ch.substitutions")
        iocInit
        dbpf "SPARC:PS01:I_SP" "0"
    """)
    return r


def test_install_yml_says_where_it_comes_from_and_what_an_ioc_links(stream_repo):
    out = ibekize.ibekize("https://github.com/infn-epics/foo-ps", "v1.2", folder="fooPS", group="ps",
                          checkout=stream_repo)
    install = yaml.safe_load(out["files"]["ibek-support-infn/fooPS/fooPS.install.yml"])
    assert install["module"] == "foo-ps" and install["organization"] == "https://github.com/infn-epics/"
    assert install["version"] == "v1.2"
    assert install["libs"] == ["stream", "asyn"]                            # not the IOC itself, not base
    assert install["dbds"] == ["stream.dbd", "asyn.dbd", "drvAsynIPPort.dbd"]
    assert install["protocol_files"] == ["db/foo.proto"]                    # installed by Db/Makefile


def test_the_controller_is_the_port_set_up_with_its_address_as_parameters(stream_repo):
    out = ibekize.ibekize("https://github.com/infn-epics/foo-ps", "main", folder="fooPS", checkout=stream_repo)
    support = yaml.safe_load(out["files"]["ibek-support-infn/fooPS/fooPS.ibek.support.yaml"])
    controller = support["entity_models"][0]
    assert controller["name"] == "controller"
    assert controller["parameters"]["IP"]["default"] == "192.168.1.50"     # epicsEnvSet expanded
    assert controller["parameters"]["TCPPORT"] == {"type": "int", "description": "TCP port", "default": 4001}
    lines = controller["pre_init"][0]["value"].splitlines()
    assert lines[0].startswith('epicsEnvSet "STREAM_PROTOCOL_PATH", "/epics/support/configure/protocol/"')
    assert 'drvAsynIPPortConfigure("{{name}}", "{{IP}}:{{TCPPORT}}", 0, 0, 0)' in lines
    assert 'fooVendorInit("{{name}}", 3)' in lines
    assert controller["post_init"][0]["value"].strip() == 'dbpf "SPARC:PS01:I_SP" "0"'
    assert not any("registerRecordDeviceDriver" in l or "dbLoadDatabase" in l for l in lines)
    assert 'fooVendorInit("FOO", 3)' in out["report"]["kept_verbatim"]   # a driver line, said so


def test_each_db_template_is_an_entity_with_a_typed_parameter_per_macro(stream_repo):
    out = ibekize.ibekize("https://github.com/infn-epics/foo-ps", "main", folder="fooPS", checkout=stream_repo)
    models = {m["name"]: m for m in yaml.safe_load(out["files"]["ibek-support-infn/fooPS/fooPS.ibek.support.yaml"])
              ["entity_models"]}
    foo = models["foo"]
    assert list(foo["parameters"]) == ["controller", "P", "R", "SCAN", "LIMIT", "PREC"]
    assert foo["parameters"]["SCAN"]["default"] == "1 second"                # $(SCAN=1 second)
    assert foo["parameters"]["PREC"] == {"type": "int", "description": "PREC macro of foo.template", "default": 3}
    assert foo["parameters"]["LIMIT"]["default"] == 35                       # the value st.cmd starts it with
    assert foo["databases"] == [{"file": "foo.template", "args": {
        "P": "{{P}}", "R": "{{R}}", "PORT": "{{controller}}", "SCAN": "{{SCAN}}", "LIMIT": "{{LIMIT}}",
        "PREC": "{{PREC}}"}}]
    ch = models["ch"]                                                       # from the substitutions file
    assert ch["parameters"]["N"]["type"] == "int" and "default" not in ch["parameters"]["N"]
    assert out["report"]["required_without_example"] == ["ch.N"]
    assert next(e for e in out["report"]["entities"] if e["db"] == "ch.template")["loaded"] == 2


def test_the_drafts_render_against_each_other(stream_repo):
    out = ibekize.ibekize("https://github.com/infn-epics/foo-ps", "main", folder="fooPS", group="ps",
                          checkout=stream_repo)
    check = out["self_check"]
    assert check["ok"], check
    assert check["entities"] == ["fooPS.controller", "fooPS.foo", "fooPS.ch", "epics.PostStartupCommand"]
    fixture = yaml.safe_load(out["files"]["ibek-templates/tests/ps-foops-test.yaml"])
    assert fixture["server"] == "192.168.1.50" and fixture["port"] == 4001 and fixture["template"] == "fooPS"
    assert fixture["devices"] == [{"name": "PS01", "n": 1}]
    assert 'N: {{ device.n | default(n) }}' in out["files"]["ibek-templates/templates/ps/fooPS/fooPS.yaml.j2"]


def test_derived_modbus_ports_are_named_after_the_controller(tmp_path):
    r = tmp_path / "mb"
    _write(r, "mbApp/src/Makefile", "PROD_IOC = mb\nmb_DBD += base.dbd asyn.dbd modbusSupport.dbd\nmb_LIBS += asyn modbus\n")
    _write(r, "mbApp/Db/ps.db", 'record(ai, "$(P):$(R):I") { field(INP, "@asyn($(READ) 0)") }\n'
                                'record(ao, "$(P):$(R):SP") { field(OUT, "@asyn($(WRITE) 0)") }\n')
    _write(r, "iocBoot/iocmb/st.cmd", """
        drvAsynIPPortConfigure("PS_TCP", "10.0.0.5:502", 0, 0, 1)
        modbusInterposeConfig("PS_TCP", 0, 2000, 0)
        drvModbusAsynConfigure("PS_R", "PS_TCP", 1, 4, 0, 8, 0, 1000, "PS")
        drvModbusAsynConfigure("PS_W", "PS_TCP", 1, 6, 0, 1, 0, 1000, "PS")
        dbLoadRecords("db/ps.db", "P=BTF,R=PS1,READ=PS_R,WRITE=PS_W")
    """)
    out = ibekize.ibekize("https://github.com/infn-epics/mb", "main", folder="mb", checkout=r)
    support = yaml.safe_load(out["files"]["ibek-support-infn/mb/mb.ibek.support.yaml"])
    lines = support["entity_models"][0]["pre_init"][0]["value"].splitlines()
    assert lines == ['drvAsynIPPortConfigure("{{name}}", "{{IP}}:{{TCPPORT}}", 0, 0, 1)',
                     'modbusInterposeConfig("{{name}}", 0, 2000, 0)',
                     'drvModbusAsynConfigure("{{name}}_PS_R", "{{name}}", 1, 4, 0, 8, 0, 1000, "PS")',
                     'drvModbusAsynConfigure("{{name}}_PS_W", "{{name}}", 1, 6, 0, 1, 0, 1000, "PS")']
    args = support["entity_models"][1]["databases"][0]["args"]
    assert args["READ"] == "{{controller}}_PS_R" and args["WRITE"] == "{{controller}}_PS_W"
    assert out["self_check"]["ok"], out["self_check"]


def test_a_jinja_name_is_never_an_ioc_level_fallback(tmp_path):
    r = tmp_path / "rg"
    _write(r, "rgApp/Db/rg.template", 'record(ai, "$(P):$(R):X") { field(HOPR, "$(RANGE)") }\n')
    _write(r, "iocBoot/iocrg/st.cmd", 'dbLoadRecords("db/rg.template", "P=A,R=B,RANGE=10")\n')
    out = ibekize.ibekize("https://github.com/infn-epics/rg", "main", folder="rg", checkout=r)
    template = out["files"]["ibek-templates/templates/io/rg/rg.yaml.j2"]
    assert "device.range | default(10)" in template and "default(range)" not in template
    assert out["self_check"]["ok"], out["self_check"]


def test_only_https_on_allowed_hosts(monkeypatch):
    for bad in ("http://github.com/a/b", "file:///etc/passwd", "https://github.com/../b", "git@github.com:a/b",
                "https://evil.example/a/b"):
        with pytest.raises(ibekize.Refused):
            ibekize.check_url(bad)
    assert ibekize.check_url("https://github.com/infn-epics/tti-ps") == "https://github.com/infn-epics/tti-ps.git"
    monkeypatch.setenv("ARGUS_IOC_SOURCE_HOSTS", "git.example.org")
    with pytest.raises(ibekize.Refused):
        ibekize.check_url("https://github.com/infn-epics/tti-ps")
    assert ibekize.ioc_ibekize_repo(None, "ws", "https://github.com/a/b")["error"].startswith("repositories are read")


def test_substitutions_in_both_forms():
    text = textwrap.dedent("""
        file "a.template" {
          pattern { N, PORT }
                  { 1, P1 }
                  { 2, P1 }
        }
        file b.template {
          { N=7, PORT=P2 }
        }
    """)
    assert ibekize.parse_substitutions(text) == [("a.template", {"N": "1", "PORT": "P1"}),
                                                 ("a.template", {"N": "2", "PORT": "P1"}),
                                                 ("b.template", {"N": "7", "PORT": "P2"})]


def test_a_library_with_an_example_ioc_beside_it(tmp_path):
    """ppt-modulator's layout: the IOC links the module's own library, and a dbd of the repository's own that only
    goes into the IOC's dbd is never installed, so the IOC's dbd is the one listed. Names may have hyphens."""
    r = tmp_path / "bcm"
    _write(r, "bcmApp/src/Makefile", """
        LIBRARY_IOC += bcmSupport
        bcmSupport_LIBS += asyn calc
        PROD_IOC = bcm-rf-ioc
        DBD += bcm-rf-ioc.dbd
        bcm-rf-ioc_DBD += base.dbd asyn.dbd calcSupport.dbd bcmMon.dbd
        bcm-rf-ioc_LIBS += bcmSupport asyn calc
    """)
    _write(r, "bcmApp/src/bcmMon.dbd", "registrar(bcmMonRegister)\n")
    libs, dbds, notes = ibekize.libs_and_dbds(r)
    assert libs == ["bcmSupport", "asyn", "calc"]
    assert dbds == ["bcm-rf-ioc.dbd", "asyn.dbd", "calcSupport.dbd"] and "bcmMon.dbd only go" in notes[0]
    _write(r, "bcmApp/src/Makefile", (r / "bcmApp/src/Makefile").read_text() + "DBD += bcmMon.dbd\n")
    assert ibekize.libs_and_dbds(r)[1] == ["bcmMon.dbd", "asyn.dbd", "calcSupport.dbd"]   # installed: alone
