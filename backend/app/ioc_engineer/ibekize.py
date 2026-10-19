"""An existing EPICS IOC repository, read into the files that make it an ibek support module and a template.

A driver usually arrives as a makeBaseApp tree that works on its author's bench: configure/RELEASE, an App with
src/Makefile and Db/ (templates, protocols), and an iocBoot/*/st.cmd that starts it. What ibek needs is the same
knowledge, said differently:

    install.yml            where the source is, and the libs and dbds an IOC links   ← *App/src/Makefile, RELEASE
    ibek.support.yaml      a controller entity (the port set-up of st.cmd) and one    ← st.cmd, the db templates
                           entity per db template it loads, a typed parameter per macro
    <template>.yaml.j2     the beamline vocabulary mapped onto those entities          ← the entity models
    tests/<…>-test.yaml    a fixture, from the values st.cmd was started with          ← st.cmd

Nothing is guessed silently. A macro with no default and no example becomes a required parameter, st.cmd lines
that are not port set-up, record loading or boilerplate are kept verbatim and listed, and the report says where
each value came from. The result is checked as every draft here is: the fixture is rendered with the template
and validated against the entity models just written.

Repositories are cloned shallow, without submodules or hooks, from the hosts in ARGUS_IOC_SOURCE_HOSTS, and
read; nothing in them is run.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_HOSTS = "github.com,gitlab.com,baltig.infn.it"
MAX_REPO_BYTES = 200_000_000

# st.cmd lines that start any IOC and say nothing about the device.
BOILERPLATE = re.compile(r"^(<|cd\b|dbLoadDatabase\b|\w+_registerRecordDeviceDriver\b|iocInit\b|dbl\b|echo\b|"
                         r"epicsThreadSleep\b|errlogInit2?\b|set_requestfile_path\b|set_savefile_path\b|"
                         r"save_restoreSet_\w+|create_monitor_set\b|iocLogInit\b|exit\b)")
PORT_MAKERS = {"drvAsynIPPortConfigure": "ip", "drvAsynSerialPortConfigure": "serial"}
AFTER_INIT = re.compile(r"^(dbpf|seq|motorUtilInit|create_monitor_set)\b")
MACRO = re.compile(r"\$[({]([A-Za-z_]\w*)(?:=([^)}]*))?[)}]")
SKIP_LIBS = {"$(EPICS_BASE_IOC_LIBS)", "$(EPICS_BASE_HOST_LIBS)", "Com", "dbCore", "dbRecStd", "ca"}
SKIP_DBDS = {"base.dbd"}
# configure/RELEASE names → what an IOC links for them, when the Makefile does not say.
RELEASE_DEPS = {"ASYN": (["asyn"], ["asyn.dbd", "drvAsynIPPort.dbd", "drvAsynSerialPort.dbd"]),
                "STREAM": (["stream"], ["stream.dbd"]), "STREAMDEVICE": (["stream"], ["stream.dbd"]),
                "MODBUS": (["modbus"], ["modbusSupport.dbd"]), "CALC": (["calc"], ["calcSupport.dbd"]),
                "MOTOR": (["motor"], ["motorSupport.dbd"]), "BUSY": (["busy"], ["busySupport.dbd"]),
                "SNCSEQ": (["seq", "pv"], []), "AUTOSAVE": (["autosave"], ["asSupport.dbd"])}


class Refused(ValueError):
    """The repository cannot be read as asked; the reason goes back to the model."""


# --- fetching --------------------------------------------------------------------------------------------------

def _hosts() -> list[str]:
    return [h.strip().lower() for h in os.environ.get("ARGUS_IOC_SOURCE_HOSTS", DEFAULT_HOSTS).split(",") if h.strip()]


def check_url(url: str) -> str:
    u = str(url or "").strip()
    m = re.fullmatch(r"https://([A-Za-z0-9.-]+)/([\w.\-/]+?)(?:\.git)?/?", u)
    if not m:
        raise Refused(f"{url!r} is not an https git URL (https://host/owner/repository)")
    if m.group(1).lower() not in _hosts():
        raise Refused(f"repositories are read only from {', '.join(_hosts())}; not from {m.group(1)}")
    if ".." in m.group(2):
        raise Refused(f"{url!r} is not a repository path")
    return f"https://{m.group(1)}/{m.group(2)}.git"


def _git(*args, cwd=None, timeout=180) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
    return subprocess.run(["git", "-c", "protocol.file.allow=never", "-c", "core.hooksPath=/dev/null", *args],
                          cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def fetch(url: str, ref: Optional[str], into: Path) -> tuple[Path, str, Optional[str]]:
    """A shallow clone: (checkout, the branch or tag read, the commit)."""
    url = check_url(url)
    if ref and not re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", ref):
        raise Refused(f"{ref!r} is not a branch or tag name")
    target = into / "repo"
    done = _git("clone", "-q", "--depth", "1", "--no-recurse-submodules", *(["--branch", ref] if ref else []),
                url, str(target))
    if done.returncode != 0:
        raise Refused(f"could not clone {url}{'@' + ref if ref else ''}: {(done.stderr or '').strip()[-300:]}")
    size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
    if size > MAX_REPO_BYTES:
        raise Refused(f"{url} is {size // 1_000_000} MB; at most {MAX_REPO_BYTES // 1_000_000} MB is read")
    branch = ref or _git("rev-parse", "--abbrev-ref", "HEAD", cwd=target).stdout.strip() or "main"
    commit = _git("rev-parse", "HEAD", cwd=target).stdout.strip() or None
    return target, branch, commit


# --- reading the tree --------------------------------------------------------------------------------------------

def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _files(root: Path, *patterns) -> list[Path]:
    out = []
    for pattern in patterns:
        out += [p for p in root.rglob(pattern) if p.is_file() and ".git" not in p.parts
                and not any(part.startswith("O.") for part in p.parts)]
    return sorted(set(out))


def _makefile_lists(root: Path) -> dict:
    """What the App/src Makefiles build and link: PROD_IOC / LIBRARY_IOC names, DBD +=, <name>_DBD +=, _LIBS."""
    found = {"prod": [], "library": [], "dbd": [], "named_dbd": {}, "libs": []}
    for mk in _files(root, "Makefile"):
        if "src" not in mk.parent.name.lower() and not mk.parent.name.endswith("App"):
            continue
        variables: dict = {}
        for raw in _text(mk).splitlines():
            line = raw.split("#", 1)[0].strip()
            m = re.match(r"^([A-Za-z_]\w*)\s*:?=\s*(\S.*)$", line)
            if m and m.group(1) not in ("TOP", "PROD_IOC", "LIBRARY_IOC", "LIBRARY", "DBD") \
                    and not m.group(1).endswith(("_DBD", "_LIBS", "_SRCS")):
                variables[m.group(1)] = m.group(2).strip()
            line = re.sub(r"\$\(([A-Za-z_]\w*)\)", lambda v: variables.get(v.group(1), v.group(0)), line)
            m = re.match(r"^(PROD_IOC|LIBRARY_IOC|LIBRARY)\s*\+?=\s*(.+)$", line)
            if m:
                found["prod" if m.group(1) == "PROD_IOC" else "library"] += m.group(2).split()
                continue
            m = re.match(r"^DBD\s*\+?=\s*(.+)$", line)
            if m:
                found["dbd"] += m.group(1).split()
                continue
            m = re.match(r"^(\w+)_DBD\s*\+?=\s*(.+)$", line)
            if m:
                found["named_dbd"].setdefault(m.group(1), []).extend(m.group(2).split())
                continue
            m = re.match(r"^(\w+)_LIBS\s*\+?=\s*(.+)$", line)
            if m:
                found["libs"] += m.group(2).split()
    return found


def _release(root: Path) -> list[str]:
    names = []
    for rel in _files(root, "RELEASE"):
        if rel.parent.name != "configure":
            continue
        for line in _text(rel).splitlines():
            m = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*=", line)
            if m and m.group(1) not in ("TEMPLATE_TOP", "EPICS_BASE", "SUPPORT", "TOP"):
                names.append(m.group(1))
    return names


def libs_and_dbds(root: Path) -> tuple[list, list, list]:
    """(libs, dbds, notes) an IOC using this module links, as install.yml lists them."""
    mk = _makefile_lists(root)
    notes = []
    libs = [x for x in OrderedDict.fromkeys(mk["libs"]) if x not in SKIP_LIBS and not x.startswith("$(")]
    own_libs = [x for x in mk["library"] if x not in libs]
    if mk["library"]:
        # A support library: what it builds, plus what it needs; its DBD += is its own support dbd.
        # (its <lib>_DBD += lines are the sources of that dbd, which already includes them)
        dbds = [d for d in mk["dbd"] if d not in SKIP_DBDS]
        libs = own_libs + [x for x in libs if x not in mk["library"]]
        dep_dbds = []
    else:
        dbds = []
        dep_dbds = [d for p in mk["prod"] for d in mk["named_dbd"].get(p, []) if d not in SKIP_DBDS]
        libs = [x for x in libs if x not in mk["prod"]]
    dbds = list(OrderedDict.fromkeys(dbds + dep_dbds))
    if not libs or not dbds:
        for name in _release(root):
            extra_libs, extra_dbds = RELEASE_DEPS.get(name, ([], []))
            if not libs and extra_libs:
                libs += [x for x in extra_libs if x not in libs]
            if not dbds and extra_dbds:
                dbds += [x for x in extra_dbds if x not in dbds]
        if libs or dbds:
            notes.append("libs/dbds partly from configure/RELEASE: the Makefiles did not list them")
    return libs, dbds, notes


def protocol_files(root: Path) -> list[str]:
    """Protocol files as install.yml names them: db/<file> when a Db Makefile installs it, else its path."""
    installed = set()
    for mk in _files(root, "Makefile"):
        if mk.parent.name.lower() == "db":
            for line in _text(mk).splitlines():
                m = re.match(r"^\s*DB\s*\+?=\s*(.+)$", line.split("#", 1)[0])
                if m:
                    installed.update(m.group(1).split())
    out = []
    for p in _files(root, "*.proto"):
        out.append(f"db/{p.name}" if p.name in installed else p.relative_to(root).as_posix())
    return list(OrderedDict.fromkeys(out))


# --- st.cmd ------------------------------------------------------------------------------------------------------

def _split_args(text: str) -> list[str]:
    """iocsh arguments: `cmd("a", "b", 0)`, `cmd "a" "b" 0` or `cmd a,b`; quotes keep commas and spaces."""
    args, cur, quote = [], "", None
    for ch in text:
        if quote:
            if ch == quote:
                quote = None
            else:
                cur += ch
        elif ch in "\"'":
            quote = ch
        elif ch in ", \t":
            if cur:
                args.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        args.append(cur)
    return args


def parse_line(line: str) -> Optional[tuple[str, list[str], str]]:
    """(command, arguments, the line as written) for one st.cmd line, or None for a comment or blank."""
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    m = re.match(r"^([A-Za-z_]\w*)\s*\((.*)\)\s*(?:#.*)?$", s)
    if m:
        return m.group(1), _split_args(m.group(2)), s
    m = re.match(r"^([A-Za-z_]\w*)\b\s*(.*)$", s)
    if m:
        rest = re.sub(r"\s+#.*$", "", m.group(2))
        return m.group(1), _split_args(rest), s
    return s.split()[0], [], s


def _expand(text: str, env: dict) -> str:
    return MACRO.sub(lambda m: env.get(m.group(1), m.group(0)), text)


def parse_macros(text: str) -> dict:
    """`P=SPARC:,R=TTI:,PORT=TTI1` as a mapping; values may be quoted."""
    out = OrderedDict()
    for chunk in re.findall(r"([A-Za-z_]\w*)\s*=\s*(\"[^\"]*\"|'[^']*'|[^,]*)", text):
        out[chunk[0]] = chunk[1].strip().strip("\"'")
    return out


def parse_substitutions(text: str) -> list[tuple[str, dict]]:
    """A substitutions file's (template, macros) pairs: `file x.template { pattern {A, B} {1, 2} }` and
    `file x.template { {A=1, B=2} }`; a global { } block applies to what follows."""
    loads = []
    text = re.sub(r"#.*", "", text)
    for m in re.finditer(r"file\s+\"?([^\s\"{]+)\"?\s*\{(.*?)\n\s*\}", text, re.S):
        name, body = m.group(1), m.group(2)
        pattern = re.search(r"pattern\s*\{([^}]*)\}", body)
        rows = re.findall(r"\{([^{}]*)\}", body[pattern.end():] if pattern else body)
        if pattern:
            keys = _split_args(pattern.group(1))
            for row in rows:
                values = _split_args(row)
                loads.append((name, dict(zip(keys, values))))
        else:
            for row in rows:
                loads.append((name, parse_macros(row)))
    return loads


def startup(root: Path) -> dict:
    """The example st.cmd, read: port set-up lines, records loaded with their macros, and what else it does."""
    candidates = [p for p in _files(root, "st*.cmd", "*.cmd") if "iocBoot" in p.parts] or _files(root, "st*.cmd")
    if not candidates:
        return {"path": None, "setup": [], "loads": [], "after_init": [], "kept": [], "ports": {}}
    path = max(candidates, key=lambda p: (p.name.startswith("st"), _text(p).count("dbLoadRecords")))
    env: dict = {}
    setup, loads, after, kept, ports = [], [], [], [], {}
    for raw in _text(path).splitlines():
        parsed = parse_line(raw)
        if parsed is None:
            continue
        cmd, args, line = parsed
        args = [_expand(a, env) for a in args]
        if cmd == "epicsEnvSet" and len(args) >= 2:
            if args[0] == "STREAM_PROTOCOL_PATH":
                continue
            env[args[0]] = args[1]
            continue
        if BOILERPLATE.match(line) or line.startswith("#!"):
            continue
        if cmd == "dbLoadRecords" and args:
            loads.append({"file": Path(args[0]).name, "macros": parse_macros(args[1]) if len(args) > 1 else {}})
            continue
        if cmd == "dbLoadTemplate" and args:
            subs = next((p for p in _files(root, Path(args[0]).name)), None)
            if subs is not None:
                for name, macros in parse_substitutions(_text(subs)):
                    loads.append({"file": Path(_expand(name, env)).name,
                                  "macros": {k: _expand(v, env) for k, v in macros.items()}})
            else:
                kept.append(line)
            continue
        if AFTER_INIT.match(line):
            after.append(_expand(line, env))
            continue
        if cmd in PORT_MAKERS and len(args) >= 2:
            ports[args[0]] = {"kind": PORT_MAKERS[cmd], "address": args[1], "root": True}
        elif cmd == "drvModbusAsynConfigure" and len(args) >= 2:
            ports[args[0]] = {"kind": "modbus", "on": args[1], "root": False}
        elif re.search(r"(Config|Configure|Create)", cmd) and args and re.fullmatch(r"[A-Za-z_][\w-]*", args[0]):
            ports.setdefault(args[0], {"kind": "driver", "command": cmd, "root": False})
        setup.append(_expand(line, env))
    return {"path": path.relative_to(root).as_posix(), "setup": setup, "loads": loads, "after_init": after,
            "kept": kept, "ports": ports}


# --- generating ----------------------------------------------------------------------------------------------

def _ident(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")
    return (s if s and not s[0].isdigit() else f"x_{s}")[:40] or "entity"


def _kind(values: list) -> str:
    vals = [str(v) for v in values if v not in (None, "")]
    if vals and all(re.fullmatch(r"-?\d+", v) for v in vals):
        return "int"
    if vals and all(re.fullmatch(r"-?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", v) for v in vals):
        return "float"
    return "str"


def _template_macros(root: Path, name: str) -> "OrderedDict[str, Optional[str]]":
    path = next(iter(_files(root, name)), None)
    out: "OrderedDict[str, Optional[str]]" = OrderedDict()
    if path is None:
        return out
    for macro, default in MACRO.findall(_text(path)):
        if macro not in out or (out[macro] is None and default):
            out[macro] = default or out.get(macro)
    return out


def _records(root: Path, name: str) -> int:
    path = next(iter(_files(root, name)), None)
    return len(re.findall(r"\brecord\s*\(", _text(path))) if path else 0


def _port_ref(value: str, ports: dict, root_port: Optional[str]) -> Optional[str]:
    """How a macro's value names a port of the controller, as Jinja: the controller itself or one of its ports."""
    if value == root_port:
        return "{{controller}}"
    if value in ports:
        return "{{controller}}_" + value
    return None


def build(root: Path, url: str, ref: str, folder: Optional[str] = None, group: str = "io",
          devtype: Optional[str] = None) -> dict:
    """The four files, the Dockerfile line and the report for a checked-out repository."""
    repo = re.sub(r"\.git$", "", url.rstrip("/").rsplit("/", 1)[-1])
    organization = url.rstrip("/").rsplit("/", 1)[0] + "/"
    folder = _ident(folder or repo).replace("_", "-") if not folder else re.sub(r"[^A-Za-z0-9_-]", "-", folder)
    prefix = re.sub(r"[^A-Za-z0-9_]", "_", folder)
    devtype = devtype or prefix.lower()
    libs, dbds, notes = libs_and_dbds(root)
    protos = protocol_files(root)
    st = startup(root)
    report = {"read": {"st.cmd": st["path"], "libs": libs, "dbds": dbds, "protocol_files": protos},
              "inferred": [], "required_without_example": [], "kept_verbatim": [], "notes": list(notes)}

    # --- the controller: st.cmd's port set-up, its root port, host and TCP port as parameters
    ports = st["ports"]
    root_port = next((p for p, d in ports.items() if d.get("root")), None)
    controller_params: "OrderedDict[str, dict]" = OrderedDict()
    controller_params["name"] = {"type": "id", "description": "Asyn port name of the controller (unique in the IOC)"}
    pre_init = []
    if protos:
        pre_init.append('epicsEnvSet "STREAM_PROTOCOL_PATH", "/epics/support/configure/protocol/"')
    host = tcp = tty = None
    if root_port:
        address = ports[root_port]["address"]
        if ports[root_port]["kind"] == "ip" and ":" in address:
            host, tcp = address.rsplit(":", 1)
            tcp = re.sub(r"\s.*$", "", tcp)  # "4001 COM" → 4001
            controller_params["IP"] = {"type": "str", "description": "Device or terminal-server address",
                                       "default": host}
            controller_params["TCPPORT"] = {"type": "int" if tcp.isdigit() else "str", "description": "TCP port",
                                            "default": int(tcp) if tcp.isdigit() else tcp}
            report["inferred"].append(f"controller IP/TCPPORT defaults from {st['path']}: {address}")
        elif ports[root_port]["kind"] == "serial":
            tty = address
            controller_params["TTY"] = {"type": "str", "description": "Serial device", "default": address}
    for line in st["setup"]:
        out = line
        for port in sorted(ports, key=len, reverse=True):
            target = "{{name}}" if port == root_port else "{{name}}_" + port
            out = re.sub(rf"(?<![\w{{]){re.escape(port)}(?![\w}}])", target, out)
        if host and tcp:
            out = out.replace(f"{host}:{tcp}", "{{IP}}:{{TCPPORT}}")
        if tty:
            out = out.replace(tty, "{{TTY}}")
        pre_init.append(out)
    if not root_port and st["setup"]:
        report["notes"].append("no drvAsynIPPortConfigure/drvAsynSerialPortConfigure in st.cmd: the controller "
                               "keeps its set-up lines as written; check which values should be parameters")
    if not st["path"]:
        report["notes"].append("no st.cmd found: entities come from the db templates alone, with no example values")
    report["kept_verbatim"] = st["kept"] + [l for l in st["setup"] if not re.match(r"^(drvAsyn|drvModbus|"
                                                                                   r"modbusInterpose|asynSet)", l)]

    # --- one entity per db template st.cmd loads (or every template, when there is no st.cmd)
    loads = st["loads"] or [{"file": p.name, "macros": {}} for p in _files(root, "*.template", "*.db")]
    by_file: "OrderedDict[str, list]" = OrderedDict()
    for load in loads:
        by_file.setdefault(load["file"], []).append(load["macros"])
    entities = []
    names_used = set()
    for file, instances in by_file.items():
        name = _ident(Path(file).stem)
        while name in names_used or name == "controller":
            name += "_db"
        names_used.add(name)
        declared = _template_macros(root, file)
        macros = list(OrderedDict.fromkeys(list(declared) + [m for inst in instances for m in inst]))
        params: "OrderedDict[str, dict]" = OrderedDict()
        args: "OrderedDict[str, str]" = OrderedDict()
        uses_controller = False
        for macro in macros:
            values = [inst[macro] for inst in instances if macro in inst]
            refs = {_port_ref(v, ports, root_port) for v in values} - {None}
            if refs and len(refs) == 1:
                uses_controller = True
                args[macro] = refs.pop()
                continue
            if refs:  # different ports of the controller per load: the port's suffix is a parameter
                uses_controller = True
                common = Counter(values).most_common(1)[0][0]
                params[f"{macro}_PORT"] = {"type": "str", "description": f"Which of the controller's ports {macro} "
                                                                         "names (the suffix after its name)",
                                           "default": common}
                args[macro] = "{{controller}}_{{" + f"{macro}_PORT" + "}}"
                report["notes"].append(f"{file}: {macro} names {len(set(values))} different ports across "
                                       f"{len(values)} loads; {macro}_PORT selects one per instance")
                continue
            default = declared.get(macro)
            kind = _kind(values + ([default] if default else []))
            spec = {"type": kind, "description": f"{macro} macro of {file}"}
            if macro in ("P", "R", "PREFIX", "DEVICE", "NAME"):
                pass  # identity: always given
            elif default not in (None, ""):
                spec["default"] = int(default) if kind == "int" else float(default) if kind == "float" else default
                report["inferred"].append(f"{name}.{macro}: default {default!r} from {file}")
            elif values and len(set(values)) == 1:
                v = values[0]
                spec["default"] = int(v) if kind == "int" else float(v) if kind == "float" else v
                report["inferred"].append(f"{name}.{macro}: default {v!r}, the value {st['path']} starts it with")
            else:
                report["required_without_example"].append(f"{name}.{macro}")
            params[macro] = spec
            args[macro] = "{{" + macro + "}}"
        if uses_controller:
            params = OrderedDict([("controller", {"type": "object", "description": "The controller"}), *params.items()])
        entities.append({"name": name, "file": file, "params": params, "args": args, "instances": len(instances),
                         "records": _records(root, file), "examples": instances})

    support = _support_yaml(prefix, repo, controller_params, pre_init, st["after_init"], entities)
    install = _install_yml(repo, organization, ref, libs, dbds, protos)
    template, fixture = _template_and_fixture(prefix, folder, group, devtype, controller_params, entities,
                                              host, tcp, tty, ports, root_port)
    files = {
        f"ibek-support-infn/{folder}/{folder}.install.yml": install,
        f"ibek-support-infn/{folder}/{folder}.ibek.support.yaml": support,
        f"ibek-templates/templates/{group}/{folder}/{folder}.yaml.j2": template,
        f"ibek-templates/tests/{group}-{folder.lower()}-test.yaml": fixture,
    }
    report["entities"] = [{"type": f"{prefix}.{e['name']}", "db": e["file"], "records": e["records"],
                           "loaded": e["instances"], "parameters": list(e["params"])} for e in entities]
    return {"files": files, "report": report, "prefix": prefix, "folder": folder,
            "dockerfile": f"Add `ansible.sh {folder}` to the RUN chain in infn-epics-ioc/Dockerfile."}


def _dump(data) -> str:
    class Dumper(yaml.SafeDumper):
        pass

    def literal(dumper, value):
        style = "|" if "\n" in value else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)
    Dumper.add_representer(str, literal)
    Dumper.add_representer(OrderedDict, lambda d, v: d.represent_dict(v.items()))
    return yaml.dump(data, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=120)


def _support_yaml(prefix, repo, controller_params, pre_init, after_init, entities) -> str:
    models = [{"name": "controller", "description": f"{repo}: the port set-up of its st.cmd.",
               "parameters": controller_params, "pre_init": [{"value": "\n".join(pre_init) + "\n"}]}]
    if after_init:
        models[0]["post_init"] = [{"value": "\n".join(after_init) + "\n"}]
    for e in entities:
        models.append({"name": e["name"], "description": f"{e['file']} ({e['records']} records).",
                       "parameters": e["params"], "databases": [{"file": e["file"], "args": e["args"]}]})
    header = ("# yaml-language-server: $schema=https://github.com/epics-containers/ibek/releases/download/3.1.2/"
              "ibek.support.schema.json\n# Drafted by the ARGUS IOC engineer from the repository's st.cmd and "
              "db templates: review the parameters.\n\n")
    return header + _dump({"module": prefix, "entity_models": models})


def _install_yml(repo, organization, ref, libs, dbds, protos) -> str:
    data = OrderedDict([("module", repo), ("organization", organization), ("version", ref)])
    if dbds:
        data["dbds"] = dbds
    if libs:
        data["libs"] = libs
    if protos:
        data["protocol_files"] = protos
    return ("# yaml-language-server: $schema=../../ibek-support/_scripts/support_install_variables.json\n"
            "# a release tag makes the image reproducible; a branch follows whatever was pushed last\n" + _dump(data))


# Names Jinja already defines: an IOC-level key by one of them would render the function, not a value.
JINJA_GLOBALS = {"range", "dict", "lipsum", "cycler", "joiner", "namespace", "loop", "self", "super", "varargs",
                 "kwargs", "caller", "true", "false", "none"}


def _beamline_value(macro: str, spec: dict) -> str:
    """The template expression for one macro: the device's key, else the IOC's, else the model's default."""
    key = macro.lower()
    if macro in ("P", "PREFIX"):
        return '"{{ iocprefix }}"'
    if macro in ("R", "DEVICE", "NAME"):
        return '"{{ device.name }}"'
    default = spec.get("default")
    tail = f" | default({default!r})" if default is not None else ""
    quote = spec["type"] == "str"
    ioc_level = "" if key in JINJA_GLOBALS else f" | default({key})"
    expr = "{{ device." + key + ioc_level + tail + " }}"
    return f'"{expr}"' if quote else expr


def _template_and_fixture(prefix, folder, group, devtype, controller_params, entities, host, tcp, tty,
                          ports, root_port) -> tuple[str, str]:
    lines = ["ioc_name: {{ iocname }}", f"description: {folder} (drafted by the ARGUS IOC engineer)", "",
             "entities:", f"- type: {prefix}.controller", '  name: "{{ iocname }}_ctrl"']
    if "IP" in controller_params:
        lines += ['  IP: "{{ server }}"', f"  TCPPORT: {{{{ port | default({tcp if str(tcp).isdigit() else repr(tcp)}) }}}}"]
    if "TTY" in controller_params:
        lines += ['  TTY: "{{ tty | default(' + repr(tty) + ') }}"']
    lines += ["{%- for device in devices %}"]
    for e in entities:
        lines += [f"- type: {prefix}.{e['name']}"]
        for macro, spec in e["params"].items():
            if macro == "controller":
                lines += ['  controller: "{{ iocname }}_ctrl"']
            else:
                lines += [f"  {macro}: {_beamline_value(macro, spec)}"]
    lines += ["{%- endfor %}", "", "- type: epics.PostStartupCommand", "  command: |", "    epicsThreadSleep 1.0",
              "{%- if iocexit %}", "    dbl", "    exit", "{%- else %}", '    dbl("*") > {{ config_dir }}/pvlist.txt',
              "    dbl", "{%- endif %}", ""]
    # The fixture: the IOC as its st.cmd starts it, two devices from its example loads where they differ.
    first = entities[0]["examples"][0] if entities and entities[0]["examples"] else {}
    fixture = {"iocname": f"{group}-{folder.lower()}-test", "template": folder, "devtype": devtype,
               "devgroup": group, "iocprefix": str(first.get("P", f"TEST:{group.upper()}:{folder.upper()}")).rstrip(":")}
    if host:
        fixture["server"] = host
        fixture["port"] = int(tcp) if str(tcp).isdigit() else tcp
    if tty:
        fixture["tty"] = tty
    names = []
    for e in entities[:1]:
        for inst in e["examples"][:2]:
            names.append(str(inst.get("R") or inst.get("DEVICE") or inst.get("NAME") or "").strip(":") or None)
    devices = [{"name": n or f"{folder.upper()}{i + 1:02d}"} for i, n in enumerate(names or [None, None])]
    # One device key serves every entity with that macro: a number when any of them wants one (a string
    # parameter takes "1" as well), else a placeholder the reviewer must replace.
    kinds_of: dict = {}
    required = set()
    for e in entities:
        for macro, spec in e["params"].items():
            if macro in ("controller", "P", "R", "PREFIX", "DEVICE", "NAME"):
                continue
            kinds_of.setdefault(macro.lower(), set()).add(spec["type"])   # every entity reading the key counts
            if "default" not in spec:
                required.add(macro.lower())
    wanted = {key: kinds_of[key] for key in required}
    for key, kinds in wanted.items():
        example = 1 if "int" in kinds else 1.0 if "float" in kinds else "CHANGE_ME"
        for d in devices:
            d.setdefault(key, example)
    fixture["devices"] = devices
    header = ("# yaml-language-server: $schema=https://raw.githubusercontent.com/infn-epics/ibek-templates/refs/heads/"
              "main/schemas/ioc.schema.json\n")
    return "\n".join(lines), header + _dump(fixture)


# --- the tool --------------------------------------------------------------------------------------------------

def ibekize(url: str, ref: Optional[str] = None, folder: Optional[str] = None, group: str = "io",
            devtype: Optional[str] = None, checkout: Optional[Path] = None) -> dict:
    """Clone (or read `checkout`), build the files, and render the fixture against them."""
    from app.ioc_engineer import tools
    work = None
    try:
        if checkout is None:
            work = Path(tempfile.mkdtemp(prefix="argus-ibekize-"))
            checkout, branch, commit = fetch(url, ref, work)
        else:
            branch, commit = ref or "main", None
        out = build(checkout, check_url(url) if checkout is None or url.startswith("https://") else url,
                    branch, folder, group, devtype)
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
    support = next(v for k, v in out["files"].items() if k.endswith(".ibek.support.yaml"))
    template = next(v for k, v in out["files"].items() if k.endswith(".yaml.j2"))
    fixture = next(v for k, v in out["files"].items() if k.startswith("ibek-templates/tests/"))
    from app.ioc_engineer.pull_requests import _models_in
    models = _models_in({"x.ibek.support.yaml": support})
    rendered, empty, error = tools._render(template, yaml.safe_load(fixture))
    check = {"error": error} if error else tools.validate_instance(rendered, models)
    out["self_check"] = {"rendered_fixture": rendered, "rendered_empty": empty, **check}
    out["source"] = {"url": url, "ref": branch, "commit": commit}
    out["next"] = ("Review the report: required_without_example are parameters nobody set; kept_verbatim are st.cmd "
                   "lines copied into the controller as written. Then propose two pull requests (ibek-support-infn "
                   "with install.yml and ibek.support.yaml, ibek-templates with the template and the fixture).")
    return out


def ioc_ibekize_repo(db, workspace_id: str, url: str, ref: Optional[str] = None, folder: Optional[str] = None,
                     group: str = "io", devtype: Optional[str] = None) -> dict:
    """The MCP tool: an existing IOC repository read into its ibek support files, template and fixture."""
    from app.ioc_engineer.tools import GROUPS, _find_module
    target = str(url or "").strip()
    if target and "://" not in target:
        # A module the catalogue knows: its git source and the version its install.yml names.
        known = _find_module(target)
        if known and known[0].get("git_url"):
            ref = ref or known[0]["built"].get("version_override") or known[0].get("version")
            folder = folder or known[0]["folder"]
            target = known[0]["git_url"]
    try:
        return ibekize(target, ref, folder, group if group in GROUPS else "io", devtype)
    except Refused as e:
        return {"error": str(e)}
