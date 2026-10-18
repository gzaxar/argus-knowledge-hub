"""The catalogue: a checkout of infn-epics-ioc read into one JSON document.

Built offline (`python -m app.ioc_engineer build`) because the repositories are where the truth is
and they change on their own schedule; the hub ships the last snapshot it was given and can be
pointed at a newer one with ARGUS_IOC_CATALOG, without a release.

What is read, and from where:

    modules         <collection>/<folder>/*.install.yml     git source, version, libs, dbds
    entity_models   <collection>/<folder>/*.ibek.support.yaml, and ibek's own epics.* entities
    built           Dockerfile, Dockerfile.base             which modules `ansible.sh` compiles in
    templates       ibek-templates/templates/**/<name>.yaml.j2
    examples        ibek-templates/tests/*.yaml, and the *-config.yaml at the repository's root
    schemas         ibek-templates/schemas/*.json
    guide           docs/architecture.md
    sources         (with --sources) each driver's own repository: db templates, protocols, README
    beamlines       (with --beamline) a beamline repository's value files: iocDefaults and the IOC entries

A module's git source is `organization` + `module`, exactly as the ansible role clones it.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

BUNDLED = Path(__file__).parent / "data" / "catalog.json.gz"
FORMAT = 1

# Where each family of support definitions sits in infn-epics-ioc, and who maintains it.
# In the order a type defined twice is taken from: the base image builds upstream modules from ibek-support-dls.
COLLECTIONS = [
    ("ibek-support-infn", "infn", "https://github.com/infn-epics/ibek-support-infn"),
    ("ibek-support-dls", "dls", "https://github.com/infn-epics/ibek-support-dls"),
    ("ibek-support", "epics-containers", "https://github.com/epics-containers/ibek-support"),
]
DOCKERFILES = ["Dockerfile.base", "Dockerfile"]

WORKDIR = re.compile(r"^\s*WORKDIR\s+\S*?(ibek-support[\w-]*)/?\s*$")
COPY = re.compile(r"^\s*COPY\s+(ibek-support[\w-]*)/([\w.+-]+)/?\s")
ANSIBLE = re.compile(r"ansible\.sh\s+(?:-v\s+(\S+)\s+)?([\w.+-]+)")
# The IOC-level devtype only: `dev.devtype == "rtd"` is a device's, not a branch of the template.
DEVTYPE = re.compile(r"(?<![\w.])devtype\s*(?:==|!=)\s*['\"]([^'\"]+)['\"]")
DEVTYPE_IN = re.compile(r"(?<![\w.])devtype\s+in\s*[\[(]([^\])]*)[\])]")
# Module prefixes may hold dots themselves (pfeiffer.tpg366.controller); `agilent.{{devtype}}.pump` is left out.
ENTITY_TYPE = re.compile(r"\btype:\s*['\"]?([A-Za-z][\w-]*(?:\.[A-Za-z_][\w-]*)+)(?![\w.{-])")
VARIABLE = re.compile(r"\{\{-?\s*([a-zA-Z_]\w*)")
MACRO = re.compile(r"\$[({]([A-Za-z_]\w*)")
RECORD = re.compile(r"record\s*\(\s*(\w+)\s*,\s*\"([^\"]+)\"")
PROTO_COMMAND = re.compile(r"^\s*([A-Za-z_]\w*)\s*\{", re.M)

SOURCE_KINDS = {".template": "db", ".db": "db", ".vdb": "db", ".substitutions": "substitutions",
                ".proto": "protocol", ".cmd": "startup", ".bob": "opi", ".dbd": "dbd"}
MAX_SOURCE_FILES = 200
MAX_TEXT = 6000


# --- reading a checkout ------------------------------------------------------

def _yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:  # a broken file is a finding, not a reason to stop
        return {"__error__": f"{type(e).__name__}: {e}"}


def _git_head(path: Path) -> Optional[str]:
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True,
                             timeout=30)
        return out.stdout.strip() or None
    except Exception:
        return None


def _built(repo: Path) -> dict:
    """(collection directory, folder) → how the image gets it: compiled by Dockerfile.base or Dockerfile, or only
    commented out. A module is built from whatever its Dockerfile copied into the working directory:
    Dockerfile.base copies ibek-support-dls/<folder> into ibek-support/, Dockerfile works in ibek-support-infn."""
    built: dict = {}
    for name in DOCKERFILES:
        path = repo / name
        if not path.exists():
            continue
        workdir, copied = None, {}
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            commented = line.lstrip().startswith("#")
            if not commented:
                w = WORKDIR.search(line)
                if w:
                    workdir = w.group(1)
                c = COPY.search(line)
                if c:
                    copied[c.group(2)] = c.group(1)
            for version, folder in ANSIBLE.findall(line):
                source = copied.get(folder) or workdir or "ibek-support"
                entry = built.setdefault((source, folder), {"in_image": None, "dockerfile": None,
                                                            "version_override": None, "commented_out_in": []})
                if commented:
                    entry["commented_out_in"].append(name)
                elif entry["in_image"] is None:
                    entry.update(in_image=True, dockerfile=name, version_override=version or None)
    return built


def _git_url(organization: Optional[str], module: Optional[str]) -> Optional[str]:
    if not organization or not module:
        return None
    return f"{organization.rstrip('/')}/{module}.git"


def _parameters(raw) -> dict:
    params = {}
    for name, p in (raw or {}).items():
        p = p if isinstance(p, dict) else {"type": str(p)}
        entry = {"type": p.get("type", "str"), "description": (p.get("description") or "").strip()}
        if "default" in p:
            entry["default"] = p["default"]
        else:
            entry["required"] = True
        if p.get("type") == "enum":
            values = p.get("values") or {}
            entry["values"] = list(values) if isinstance(values, dict) else list(values or [])
        params[name] = entry
    return params


def _lines(raw) -> list:
    """pre_init / post_init entries as the text they put in st.cmd."""
    out = []
    for item in raw or []:
        if isinstance(item, dict):
            out.append(str(item.get("value", "")).rstrip())
        else:
            out.append(str(item).rstrip())
    return [x for x in out if x]


def _databases(raw) -> list:
    out = []
    for db in raw or []:
        if isinstance(db, dict):
            args = db.get("args") or {}
            out.append({"file": db.get("file"), "args": list(args) if isinstance(args, dict) else args})
    return out


def _entity_models(path: Path, folder: str, collection: str) -> tuple[Optional[str], list, Optional[str]]:
    data = _yaml(path)
    if not isinstance(data, dict):
        return None, [], f"{path.name}: not a mapping"
    if "__error__" in data:
        return None, [], f"{path.name}: {data['__error__']}"
    prefix = data.get("module")
    models = []
    for m in data.get("entity_models") or data.get("defs") or []:
        if not isinstance(m, dict) or not m.get("name"):
            continue
        models.append({
            "type": f"{prefix}.{m['name']}",
            "module": prefix,
            "folder": folder,
            "collection": collection,
            "file": path.name,
            "description": (m.get("description") or "").strip(),
            "parameters": _parameters(m.get("parameters")),
            "pre_init": _lines(m.get("pre_init")),
            "post_init": _lines(m.get("post_init")),
            "env_vars": [{"name": e.get("name"), "value": e.get("value")} for e in m.get("env_vars") or []
                         if isinstance(e, dict)],
            "databases": _databases(m.get("databases")),
            "sub_entities": [s.get("type") for s in m.get("sub_entities") or [] if isinstance(s, dict)],
            "has_pvi": bool(m.get("pvi")),
        })
    return prefix, models, None


def _modules(repo: Path, built: dict) -> tuple[list, list, list]:
    modules, models, problems = [], [], []
    for directory, collection, url in COLLECTIONS:
        base = repo / directory
        if not base.is_dir():
            problems.append(f"{directory}: not checked out (git submodule update --init {directory})")
            continue
        for folder in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
            installs = sorted(folder.glob("*.install.yml")) + sorted(folder.glob("*.install.yaml"))
            supports = sorted(folder.glob("*.ibek.support.yaml"))
            if not installs and not supports:
                continue
            install = _yaml(installs[0]) if installs else {}
            install = install if isinstance(install, dict) else {}
            if "__error__" in install:
                problems.append(f"{directory}/{folder.name}/{installs[0].name}: {install['__error__']}")
                install = {}
            prefixes = []
            for s in supports:
                prefix, found, problem = _entity_models(s, folder.name, collection)
                if problem:
                    problems.append(f"{directory}/{folder.name}/{problem}")
                if prefix:
                    prefixes.append(prefix)
                models.extend(found)
            readme = next((p for p in folder.iterdir() if p.name.lower().startswith("readme")), None)
            b = built.get((directory, folder.name), {})
            modules.append({
                "folder": folder.name,
                "collection": collection,
                "path": f"{directory}/{folder.name}",
                "browse": f"{url}/tree/main/{folder.name}",
                "module": install.get("module"),
                "version": str(install["version"]) if install.get("version") is not None else None,
                "organization": install.get("organization"),
                "git_url": _git_url(install.get("organization"), install.get("module")),
                "libs": install.get("libs") or [],
                "dbds": install.get("dbds") or [],
                "protocol_files": install.get("protocol_files") or [],
                "apt_developer": install.get("apt_developer") or [],
                "apt_runtime": install.get("apt_runtime") or [],
                "install_file": installs[0].name if installs else None,
                "install_yml": installs[0].read_text(encoding="utf-8", errors="replace")[:MAX_TEXT] if installs else None,
                "has_install_sh": (folder / "install.sh").exists(),
                "support_files": [s.name for s in supports],
                "ibek_modules": prefixes,
                "built": {"in_image": bool(b.get("in_image")), "dockerfile": b.get("dockerfile"),
                          "version_override": b.get("version_override"),
                          "commented_out_in": b.get("commented_out_in") or []},
                "readme": readme.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT] if readme else None,
            })
    # ibek's own entities (epics.EpicsEnvSet, epics.DbAlias, …): in every image, from the _ansible the base copies.
    ansible = next((d for d in ("ibek-support-dls", "ibek-support") if (repo / d / "_ansible").is_dir()), "ibek-support")
    for builtin in sorted((repo / ansible / "_ansible").glob("*.ibek.support.yaml")):
        prefix, found, problem = _entity_models(builtin, "_ansible", dict((c[0], c[1]) for c in COLLECTIONS)[ansible])
        if problem:
            problems.append(f"{ansible}/_ansible/{problem}")
        for m in found:
            m["builtin"] = True
        models.extend(found)
    return modules, models, problems


def _template_info(path: Path, root: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    rel = path.relative_to(root)
    devtypes = set(DEVTYPE.findall(text))
    for group in DEVTYPE_IN.findall(text):
        devtypes.update(v.strip().strip("'\"") for v in group.split(",") if v.strip())
    folder = path.parent
    siblings = sorted(p.name for p in folder.iterdir() if p.is_file() and p != path)
    schema = next((p for p in folder.glob("*.schema.json")), None)
    readme = folder / "README.md"
    return {
        "name": path.name[: -len(".yaml.j2")],
        "group": rel.parts[0],
        "path": f"ibek-templates/templates/{rel.as_posix()}",
        "directory": folder.name,
        "devtypes": sorted(devtypes),
        "entity_types": sorted(set(ENTITY_TYPE.findall(text))),
        "variables": sorted(set(VARIABLE.findall(text)) - {"loop", "range", "true", "false", "none"}),
        "siblings": siblings,
        "source": text,
        "schema": json.loads(schema.read_text(encoding="utf-8")) if schema else None,
        "readme": readme.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT] if readme.exists() else None,
    }


def _templates(repo: Path) -> tuple[list, list, list]:
    root = repo / "ibek-templates" / "templates"
    if not root.is_dir():
        return [], [], ["ibek-templates: not checked out"]
    templates, globals_ = [], []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.parts[0] == "global":
            globals_.append({"file": rel.as_posix(), "source": path.read_text(encoding="utf-8", errors="replace")})
        elif path.name.endswith(".yaml.j2"):
            templates.append(_template_info(path, root))
    # The directories jnjrender can also resolve `template:` to (it renders every .j2 in them). The image
    # searches epics-support-template-infn too: directory templates (st.cmd.j2, start.sh.j2), not ibek YAML.
    dirs = sorted({f"ibek-templates/{p.relative_to(root).as_posix()}" for p in root.rglob("*") if p.is_dir()})
    other = repo / "epics-support-template-infn"
    if other.is_dir():
        dirs += sorted({f"infn-support-templates/{p.relative_to(other).as_posix()}" for p in other.rglob("*")
                        if p.is_dir() and ".git" not in p.parts and not p.name.startswith((".", "__"))})
    return templates, globals_, dirs


def _examples(repo: Path) -> list:
    out = []
    candidates = [("ibek-templates fixture", p) for p in sorted((repo / "ibek-templates" / "tests").glob("*.yaml"))]
    candidates += [("infn-epics-ioc config", p) for p in sorted(repo.glob("*-config.yaml"))]
    for origin, path in candidates:
        text = path.read_text(encoding="utf-8", errors="replace")
        data = _yaml(path)
        data = data if isinstance(data, dict) else {}
        out.append({
            "name": path.stem,
            "origin": origin,
            "path": path.relative_to(repo).as_posix(),
            "template": data.get("template"),
            "devtype": data.get("devtype"),
            "devgroup": data.get("devgroup"),
            "iocprefix": data.get("iocprefix"),
            "devices": len(data.get("devices") or []),
            "source": text[:20000],
        })
    return out


# --- driver sources --------------------------------------------------------------

def _index_source(checkout: Path) -> dict:
    files = []
    for path in sorted(checkout.rglob("*")):
        if not path.is_file() or ".git" in path.parts or len(files) >= MAX_SOURCE_FILES:
            continue
        kind = SOURCE_KINDS.get(path.suffix)
        if kind is None:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        entry = {"path": path.relative_to(checkout).as_posix(), "kind": kind, "bytes": len(text)}
        if kind in ("db", "substitutions", "startup"):
            entry["macros"] = sorted(set(MACRO.findall(text)))
        if kind == "db":
            records = RECORD.findall(text)
            entry["records"] = len(records)
            entry["record_sample"] = [f"{t} {n}" for t, n in records[:25]]
        if kind == "protocol":
            entry["commands"] = sorted(set(PROTO_COMMAND.findall(text)) - {"ExtraInput", "InTerminator"})[:60]
        if kind in ("startup", "substitutions") and len(text) < MAX_TEXT:
            entry["text"] = text
        files.append(entry)
    readme = next((p for p in sorted(checkout.iterdir()) if p.name.lower().startswith("readme")), None)
    return {"files": files, "readme": readme.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT] if readme else None}


def _fetch_source(module: dict, into: Path) -> dict:
    url, version = module["git_url"], module["built"]["version_override"] or module["version"]
    target = into / module["folder"]
    if not target.exists():
        cmd = ["git", "clone", "-q", "--depth", "1"] + (["--branch", version] if version else []) + [url, str(target)]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if done.returncode != 0 and version:  # a version that is a commit, not a branch or a tag
            done = subprocess.run(["git", "clone", "-q", url, str(target)], capture_output=True, text=True, timeout=600)
            if done.returncode == 0:
                subprocess.run(["git", "-C", str(target), "checkout", "-q", version], capture_output=True, timeout=60)
        if done.returncode != 0:
            return {"url": url, "ref": version, "error": (done.stderr or "clone failed").strip()[-300:]}
    return {"url": url, "ref": version, "commit": _git_head(target), **_index_source(target)}


# --- beamlines ---------------------------------------------------------------------

VALUE_FILE = re.compile(r"\$\w+/((?:deploy/)?[\w./-]+\.ya?ml)")


def _deep_merge(base: dict, over: dict) -> dict:
    """Helm's merge of value files: maps merge key by key, anything else is replaced by the later file."""
    out = dict(base)
    for key, value in (over or {}).items():
        out[key] = _deep_merge(out[key], value) if isinstance(out.get(key), dict) and isinstance(value, dict) else value
    return out


def _value_files(checkout: Path) -> list:
    """The value files ArgoCD renders epik8s-chart with, in order: the multi-source `valueFiles` of
    deploy/templates/*.yaml (SPARC, BTF), else deploy/values.yaml alone (single-source beamlines such as ELI)."""
    files = []
    for template in sorted((checkout / "deploy" / "templates").glob("*.y*ml")):
        for rel in VALUE_FILE.findall(template.read_text(encoding="utf-8", errors="replace")):
            if rel not in files and (checkout / rel).exists():
                files.append(rel)
    return files or (["deploy/values.yaml"] if (checkout / "deploy" / "values.yaml").exists() else [])


def _beamline(spec: str, into: Path) -> dict:
    """One beamline repository (a path, or a git URL with an optional @ref) as epik8s-chart sees it."""
    url, ref = spec, None
    if "://" in spec and "@" in spec.rsplit("/", 1)[-1]:
        url, ref = spec.rsplit("@", 1)
    if Path(url).is_dir():
        checkout = Path(url)
    else:
        checkout = into / re.sub(r"\.git$", "", url.rstrip("/").rsplit("/", 1)[-1])
        if not checkout.exists():
            cmd = ["git", "clone", "-q", "--depth", "1"] + (["--branch", ref] if ref else []) + [url, str(checkout)]
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if done.returncode != 0:
                return {"name": checkout.name, "url": url, "ref": ref,
                        "error": (done.stderr or "clone failed").strip()[-300:]}
    values: dict = {}
    files = _value_files(checkout)
    for rel in files:
        data = _yaml(checkout / rel)
        if isinstance(data, dict) and "__error__" not in data:
            values = _deep_merge(values, data)
    raw = (values.get("epicsConfiguration") or {}).get("iocs") or []
    # A list or a map keyed by name: the chart ranges over either (a map in key order).
    entries = [dict(v, name=v.get("name") or k) for k, v in sorted(raw.items())] if isinstance(raw, dict) \
        else [dict(v) for v in raw if isinstance(v, dict)]
    globals_ = {k: values.get(k) for k in ("beamline", "namespace", "ioc_version", "nfsMounts", "targetRevision",
                                           "giturl", "gitrev", "baseIp", "startIp") if k in values}
    return {
        "name": str(values.get("beamline") or checkout.name),
        "url": url if not Path(url).is_dir() else None,
        "ref": ref,
        "commit": _git_head(checkout),
        "value_files": files,
        "globals": globals_,
        "ioc_defaults": values.get("iocDefaults") or {},
        "iocs": entries,
    }


# --- the catalogue -----------------------------------------------------------------

def build(repo: Path, sources: Optional[Path] = None, only_collections: tuple = ("infn",),
          beamlines: tuple = (), workdir: Optional[Path] = None) -> dict:
    repo = Path(repo).resolve()
    built = _built(repo)
    modules, models, problems = _modules(repo, built)
    templates, globals_, dirs = _templates(repo)
    problems += [] if templates else ["no templates found"]
    if sources is not None:
        sources.mkdir(parents=True, exist_ok=True)
        for m in modules:
            if m["git_url"] and m["collection"] in only_collections:
                m["source"] = _fetch_source(m, sources)
    schemas = {}
    for path in sorted((repo / "ibek-templates" / "schemas").glob("*.json")):
        schemas[path.stem.replace(".schema", "")] = json.loads(path.read_text(encoding="utf-8"))
    lines = []
    if beamlines:
        into = workdir or sources or Path(os.environ.get("TMPDIR", "/tmp")) / "argus-ioc-beamlines"
        into.mkdir(parents=True, exist_ok=True)
        for spec in beamlines:
            line = _beamline(spec, into)
            if line.get("error"):
                problems.append(f"beamline {spec}: {line['error']}")
            lines.append(line)
    guide = repo / "docs" / "architecture.md"
    return {
        "format": FORMAT,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repository": {
            "url": "https://github.com/infn-epics/infn-epics-ioc",
            "commit": _git_head(repo),
            "submodules": {d: _git_head(repo / d) for d in [c[0] for c in COLLECTIONS]
                           + ["ibek-templates", "epics-support-template-infn"]},
        },
        "image": {"runtime": "ghcr.io/infn-epics/infn-epics-ioc-runtime", "base": "ghcr.io/infn-epics/infn-epics-ioc-base"},
        "modules": modules,
        "entity_models": models,
        "templates": templates,
        "template_dirs": dirs,
        "global_templates": globals_,
        "examples": _examples(repo),
        "schemas": schemas,
        "beamlines": lines,
        "guide": guide.read_text(encoding="utf-8") if guide.exists() else "",
        "problems": problems,
    }


def write(catalog: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(catalog, ensure_ascii=False, sort_keys=False, default=str).encode("utf-8")
    if out.suffix == ".gz":
        out.write_bytes(gzip.compress(data, mtime=0))
    else:
        out.write_bytes(data)


def _read(path: Path) -> dict:
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw)


def _empty_catalog(problem: str) -> dict:
    return {"format": FORMAT, "modules": [], "entity_models": [], "templates": [], "examples": [], "beamlines": [],
            "template_dirs": [], "global_templates": [], "schemas": {}, "guide": "", "problems": [problem]}


def _fetch(url: str) -> dict:
    """A published catalogue (e.g. the asset infn-epics-ioc attaches to each release), kept in a local copy so a
    restart or an unreachable GitHub still answers from the last one fetched."""
    import requests  # only needed for a remote catalogue
    cache = Path(os.environ.get("ARGUS_IOC_CATALOG_CACHE") or Path(os.environ.get("TMPDIR", "/tmp")) /
                 "argus-ioc-catalog.json.gz")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        catalog = json.loads(gzip.decompress(response.content) if response.content[:2] == b"\x1f\x8b"
                             else response.content)
        if catalog.get("format") != FORMAT:
            raise ValueError(f"catalogue format {catalog.get('format')}, this hub reads {FORMAT}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(response.content)
        catalog["loaded_from"] = url
        return catalog
    except Exception as e:
        fallback = cache if cache.exists() else BUNDLED
        catalog = _read(fallback) if fallback.exists() else _empty_catalog("no IOC catalogue")
        catalog.setdefault("problems", []).insert(0, f"could not fetch {url} ({type(e).__name__}: {e}); "
                                                     f"answering from {fallback.name}")
        catalog["loaded_from"] = str(fallback)
        return catalog


_loaded: dict = {}


def load() -> dict:
    """The catalogue this hub answers from: ARGUS_IOC_CATALOG (a file, or an http(s) URL re-read every
    ARGUS_IOC_CATALOG_TTL seconds, default six hours) if set, else the bundled snapshot."""
    source = os.environ.get("ARGUS_IOC_CATALOG") or str(BUNDLED)
    ttl = float(os.environ.get("ARGUS_IOC_CATALOG_TTL") or 6 * 3600)
    now = time.monotonic()
    if _loaded.get("source") == source and (not source.startswith(("http://", "https://"))
                                            or now - _loaded["at"] < ttl):
        return _loaded["catalog"]
    if source.startswith(("http://", "https://")):
        catalog = _fetch(source)
    else:
        path = Path(source)
        catalog = _read(path) if path.exists() else _empty_catalog(f"no IOC catalogue at {path}")
        catalog["loaded_from"] = str(path)
    _loaded.update(source=source, at=now, catalog=catalog)
    return catalog


load.cache_clear = _loaded.clear  # the tests' handle, as with lru_cache
