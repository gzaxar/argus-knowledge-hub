"""A new support module from a description of the device: the makeBaseApp tree, the driver (an asyn port driver
or a StreamDevice protocol), the SNL state programs, the bench IOC and its simulator, and the ibek files.

Nothing here compiles C++ or SNL (the hub has no EPICS toolchain); what can be checked without one is: the
description is refused with every reason, the files name each other consistently (a record the template
defines is the PV the state program assigns, a parameter the driver creates is the one the record links), the
simulator answers the commands, and the ibek drafts render against each other and survive ibekize.
"""
import re
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
import yaml

from app.ioc_engineer import ibekize, scaffold


def _write(out, root):
    for path, text in out["files"].items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def test_the_example_is_a_whole_module_in_the_house_style():
    out = scaffold.scaffold(scaffold.EXAMPLE)
    files = out["files"]
    for path in ("acme-ps/Makefile", "acme-ps/configure/RELEASE", "acme-ps/acmeApp/src/Makefile",
                 "acme-ps/acmeApp/src/acmeDriver.cpp", "acme-ps/acmeApp/src/acmeDriver.h",
                 "acme-ps/acmeApp/src/acmeAutoOn.st", "acme-ps/acmeApp/src/acmeSupport.dbd",
                 "acme-ps/acmeApp/Db/acme.template", "acme-ps/acmeApp/Db/acmeAutoOn.template",
                 "acme-ps/iocBoot/iocacme/st.cmd", "acme-ps/iocBoot/iocacme/st-sim.cmd", "acme-ps/sim/acme_sim.py",
                 "ibek-support-infn/acme-ps/acme-ps.install.yml", "ibek-support-infn/acme-ps/acme-ps.ibek.support.yaml",
                 "ibek-templates/templates/ps/acme/acme.yaml.j2", "ibek-templates/tests/ps-acme-test.yaml"):
        assert path in files, path
    assert "acme-ps/acmeApp/Db/acme.proto" not in files                  # an asyn driver needs no protocol
    release = files["acme-ps/configure/RELEASE"]
    assert "SNCSEQ=$(SUPPORT)/sequencer" in release and "STREAM" not in release
    make = files["acme-ps/acmeApp/src/Makefile"]
    assert "LIBRARY_IOC += acmeSupport" in make and "acmeSupport_SRCS += acmeAutoOn.st" in make
    assert "PROD_IOC = acme" in make and "acme_LIBS += acmeSupport" in make
    assert files["acme-ps/acmeApp/src/acmeSupport.dbd"] == \
        "registrar(acmeDriverRegister)\nregistrar(acmeAutoOnRegistrar)\n"
    assert out["self_check"]["ok"], out["self_check"]
    assert out["module"] == {"name": "acme-ps", "app": "acme", "driver": "asyn", "transport": "ip",
                             "library": "acmeSupport", "state_programs": ["acmeAutoOn"], "ioc": "acme"}


def test_driver_parameters_records_and_state_program_name_the_same_things():
    files = scaffold.scaffold(scaffold.EXAMPLE)["files"]
    cpp, h = files["acme-ps/acmeApp/src/acmeDriver.cpp"], files["acme-ps/acmeApp/src/acmeDriver.h"]
    template = files["acme-ps/acmeApp/Db/acme.template"]
    created = set(re.findall(r'createParam\("(\w+)"', cpp))
    linked = set(re.findall(r"@asyn\(\$\(PORT\),0,\$\(TIMEOUT=1\)\)(\w+)", template))
    assert created == linked == {"CONNECTED", "Current_RB", "Current_SP", "Voltage_RB", "Output_RB", "Output_SP",
                                 "Mode_RB", "Ident_RB"}
    assert 'sscanf(in, "%lf", &v)' in cpp                                    # a float reply read as a double
    assert 'epicsSnprintf(out, sizeof(out), "CURR %f", (double)value)' in cpp
    assert "writeInt32" in h and "writeFloat64" in h and "writeOctet" not in h  # no string setpoint, no override
    assert 'iocshFuncDef configureDef = {"acmeConfigure", 4' in cpp
    records = set(re.findall(r'record\(\w+, "\$\(P\):\$\(R\):([\w:]+)"\)', template +
                             files["acme-ps/acmeApp/Db/acmeAutoOn.template"]))
    snl = files["acme-ps/acmeApp/src/acmeAutoOn.st"]
    assigned = set(re.findall(r'assign \w+ to "\{P\}:\{R\}:([\w:]+)";', snl))
    assert assigned <= records and {"Output_SP", "Output_RB", "Current_SP", "Current_RB", "AutoOn:Start"} <= assigned
    assert 'field(ZNAM, "Off")' in template and 'field(DRVH, "100")' in template
    assert "option +r;" in snl and 'program acmeAutoOn("P=TEST:PS:ACME,R=ACME01,RETRY_DELAY=5")' in snl
    assert "sp_Output = 1;" in snl and "when (rb_Current > 9.5)" in snl      # a state name becomes its index
    st = files["acme-ps/iocBoot/iocacme/st-sim.cmd"]
    assert 'drvAsynIPPortConfigure("ACME01_IO", "127.0.0.1:4001", 0, 0, 0)' in st
    assert 'acmeConfigure("ACME01", "ACME01_IO", 1, 1)' in st and st.rstrip().endswith('RETRY_DELAY=5"')


def test_stream_writes_a_protocol_and_no_library_without_sequences():
    out = scaffold.scaffold({"name": "tc-io", "app": "tc", "driver": "stream", "terminator": "LF", "poll": 2,
                             "parameters": [{"name": "Temp", "read": "T?", "reply": "T=%e", "unit": "C"},
                                            {"name": "Ident", "type": "string", "read": "ID?"},
                                            {"name": "Valve", "type": "enum", "states": ["Closed", "Open"],
                                             "read": "V?", "write": "V %d", "ack": "OK"}]})
    files = out["files"]
    proto = files["tc-io/tcApp/Db/tc.proto"]
    assert "Terminator = LF;" in proto
    assert 'get_Temp { out "T?"; in "T=%e"; }' in proto
    assert 'get_Ident { out "ID?"; in "%#s"; }' in proto                     # the whole reply, spaces included
    assert 'set_Valve { out "V %d"; in "OK"; }' in proto
    template = files["tc-io/tcApp/Db/tc.template"]
    assert '@tc.proto get_Temp $(PORT)' in template and 'field(SCAN, "$(SCAN=2 second)")' in template
    assert 'field(ONVL, "1")' in template and 'field(ONST, "Open")' in template
    assert not any(p.endswith(("Driver.cpp", ".st", "Support.dbd")) for p in files)
    assert "LIBRARY_IOC" not in files["tc-io/tcApp/src/Makefile"]
    install = yaml.safe_load(files["ibek-support-infn/tc-io/tc-io.install.yml"])
    assert install["libs"] == ["asyn", "stream"] and install["protocol_files"] == ["db/tc.proto"]
    assert "tcSupport.dbd" not in install["dbds"]
    assert out["self_check"]["ok"], out["self_check"]


def test_ibek_files_start_the_driver_and_the_state_programs():
    files = scaffold.scaffold(scaffold.EXAMPLE)["files"]
    install = yaml.safe_load(files["ibek-support-infn/acme-ps/acme-ps.install.yml"])
    assert install["libs"] == ["asyn", "seq", "pv", "acmeSupport"]
    assert install["dbds"][-1] == "acmeSupport.dbd" and "protocol_files" not in install
    model = yaml.safe_load(files["ibek-support-infn/acme-ps/acme-ps.ibek.support.yaml"])["entity_models"][0]
    assert model["name"] == "controller" and list(model["parameters"])[:5] == ["name", "P", "R", "IP", "TCPPORT"]
    pre = model["pre_init"][0]["value"]
    assert 'acmeConfigure("{{name}}", "{{name}}_IO", {{POLL}}, {{TIMEOUT}})' in pre
    assert 'asynOctetSetInputEos("{{name}}_IO", 0, "\\r\\n")' in pre
    assert [d["file"] for d in model["databases"]] == ["acme.template", "acmeAutoOn.template"]
    assert model["post_init"][0]["value"] == 'seq acmeAutoOn, "P={{P}},R={{R}},RETRY_DELAY={{RETRY_DELAY}}"\n'
    fixture = yaml.safe_load(files["ibek-templates/tests/ps-acme-test.yaml"])
    assert fixture["template"] == "acme" and [d["name"] for d in fixture["devices"]] == ["ACME01", "ACME02"]


def test_ibekize_reads_the_generated_module_back(tmp_path):
    """The module is an ordinary makeBaseApp tree: the ibekizer finds its library, dbd, port and templates."""
    out = scaffold.scaffold({**scaffold.EXAMPLE, "name": "acme-ps"})
    _write(out, tmp_path)
    back = ibekize.ibekize("https://github.com/infn-epics/acme-ps", "main", folder="acme", group="ps",
                           checkout=tmp_path / "acme-ps")
    install = yaml.safe_load(back["files"]["ibek-support-infn/acme/acme.install.yml"])
    assert "acmeSupport" in install["libs"] and "acmeSupport.dbd" in install["dbds"]
    assert back["self_check"]["ok"], back["self_check"]


def test_the_simulator_answers_the_commands(tmp_path):
    out = scaffold.scaffold(scaffold.EXAMPLE)
    _write(out, tmp_path)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    sim = subprocess.Popen([sys.executable, "-I", str(tmp_path / "acme-ps/sim/acme_sim.py"), "--port", str(port)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                conn = socket.create_connection(("127.0.0.1", port), timeout=2)
                break
            except OSError:
                time.sleep(0.1)
        with conn:
            def ask(line):
                conn.sendall(line.encode() + b"\r\n")
                return conn.recv(256).decode().strip()
            assert ask("*IDN?") == "ACME,PS3000,SIM,1.0"
            conn.sendall(b"CURR 12.500000\r\nOUTP 1\r\n")
            time.sleep(0.2)
            assert float(ask("MEAS:CURR?")) == 12.5 and ask("OUTP?") == "1"
    finally:
        sim.terminate()
        sim.wait(timeout=5)


def test_a_description_that_cannot_become_a_module_comes_back_with_every_reason():
    with pytest.raises(scaffold.Invalid) as e:
        scaffold.scaffold({"name": "Bad Name", "driver": "gpib", "parameters": [
            {"name": "x y", "read": "X?"},
            {"name": "Volt", "read": "V? %d", "write": "V %f %f"},
            {"name": "Out", "type": "bool", "read": "O?", "write": 'O %d\\n'},
            {"name": "Mode", "type": "enum", "states": ["only"], "read": "M?"}],
            "sequences": [{"name": "Go", "steps": [{"set": "Mode", "value": 1}, {"wait": "Volt"},
                                                   {"set": "Volt", "value": "high"}]}]})
    problems = "\n".join(e.value.args[0])
    with pytest.raises(scaffold.Invalid) as e:     # what goes into st.cmd and file paths is checked as well
        scaffold.scaffold({**scaffold.EXAMPLE, "prefix": 'A,B="', "ip": "1.2.3.4; x", "folder": "../x", "group": "x"})
    assert len(e.value.args[0]) == 4
    cpp = scaffold.scaffold({**scaffold.EXAMPLE, "description": 'a */ b\nc "d"'})["files"]["acme-ps/acmeApp/src/acmeDriver.cpp"]
    assert cpp.splitlines()[0] == "/* acmeDriver.cpp - asyn port driver for a * / b c 'd'"
    for expected in ("name 'Bad Name'", "driver 'gpib'", "parameter x y", "Volt.read: a query has no %",
                     "Volt.write 'V %f %f': exactly one conversion", "Out.write", "an enum has 2 to 16 states",
                     "set 'Mode' is not a numeric parameter with a write command", "wait needs one of equals",
                     "'high' is not a number"):
        assert expected in problems, (expected, problems)


def test_the_mcp_tool_answers_with_the_problems_and_an_example():
    from app.services.mcp_tools import TOOLS
    tool = next(t for t in TOOLS if t["name"] == "ioc_scaffold_module")
    refused = tool["handler"](None, "ws", textwrap.dedent("""
        name: x
        parameters: []
    """))
    assert refused["error"] == "the description needs changes" and refused["example"] == scaffold.EXAMPLE
    assert any("at least one quantity" in p for p in refused["problems"])
    done = tool["handler"](None, "ws", scaffold.EXAMPLE)
    assert done["self_check"]["ok"] and done["already_exists"] == [] and "not compiled" in done["not_checked"]
    assert Path(next(iter(done["files"]))).parts[0] == "acme-ps"


def test_a_real_device_long_strings_and_queries_that_report_a_setting():
    """The Keysight E36100B description in docs/examples: strings are lsi/lso (an *IDN? answer is longer than 40
    characters), and VOLT? is simulated as what VOLT set, not as a quantity of its own."""
    spec = yaml.safe_load((Path(__file__).resolve().parents[2] / "docs/examples/keysight-e36100.yaml").read_text())
    out = scaffold.scaffold(spec)
    assert out["self_check"]["ok"], out["self_check"]
    files = out["files"]
    template = files["keysight-e36100/e36100App/Db/e36100.template"]
    assert 'record(lsi, "$(P):$(R):Ident_RB")' in template and 'field(SIZV, "256")' in template
    assert "char v[256];" in files["keysight-e36100/e36100App/src/e36100Driver.cpp"]
    sim = files["keysight-e36100/sim/e36100_sim.py"]
    assert "'VOLT?': ('Voltage', '%f')" in sim and "'MEAS:VOLT?': ('Voltage', '%f')" in sim
    assert out["module"]["state_programs"] == ["e36100RampOn", "e36100SafeOff"]
    with pytest.raises(scaffold.Invalid, match="sim_from"):
        scaffold.scaffold({**spec, "parameters": spec["parameters"] + [
            {"name": "Bad", "type": "string", "read": "B?", "sim_from": "Voltage"}]})
