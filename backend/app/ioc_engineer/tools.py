"""What the IOC engineer can do with the catalogue.

Read-only, like the rest of the MCP tools: they find, explain, render and check, and the scaffold
returns files as text. Committing them, bumping the submodules and tagging an image stay with the
person who answers for the IOC.

Rendering is jnjrender's: plain Jinja2 over the merged IOC entry, with `template:` resolved the
way `jnjrender --auto` resolves it (a file <template>.yaml.j2 anywhere under the templates, else a
directory of that name). It runs sandboxed, because the values come from whoever is asking.
Validation is what `ibek runtime generate` will refuse at pod start, found before the pod starts:
an entity type nobody defines or the image does not compile, a parameter that is missing,
unknown or of the wrong type, an object reference to nothing.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import yaml
from jinja2 import Undefined
from jinja2.sandbox import SandboxedEnvironment

from app.ioc_engineer.catalog import load

WORD = re.compile(r"[\w-]+", re.UNICODE)
JINJA = re.compile(r"\{\{|\{%")
# Keys an ibek entity may carry besides its model's parameters.
ENTITY_KEYS = {"type", "entity_enabled"}
GROUPS = ["ps", "motor", "vac", "daq", "io", "cooling", "modulator", "synch", "mps"]


# --- lookups -----------------------------------------------------------------------

def _models() -> dict:
    """type → model. A type defined in two collections (ibek-support and its DLS mirror) is the copy the image
    builds, else the first in collection order."""
    out: dict = {}
    for m in load()["entity_models"]:
        if m["type"] not in out or (not _availability(out[m["type"]])["in_image"] and _availability(m)["in_image"]):
            out[m["type"]] = m
    return out


def _modules() -> list:
    return load()["modules"]


def _module_of(model: dict) -> Optional[dict]:
    return next((m for m in _modules() if m["folder"] == model["folder"] and m["collection"] == model["collection"]),
                None)


def _availability(model: dict) -> dict:
    """Whether an image built from this catalogue's Dockerfiles can instantiate the model."""
    if model.get("builtin"):
        return {"in_image": True, "how": "built into ibek"}
    module = _module_of(model)
    if module is None:
        return {"in_image": False, "how": "no support folder found"}
    b = module["built"]
    if b["in_image"]:
        return {"in_image": True, "how": f"ansible.sh {module['folder']} in {b['dockerfile']}"}
    hint = f" (commented out in {', '.join(b['commented_out_in'])})" if b["commented_out_in"] else ""
    return {"in_image": False, "how": f"{module['path']} exists but no Dockerfile runs ansible.sh {module['folder']}{hint}"}


def _find_module(name: str) -> list:
    n = (name or "").strip().lower()
    exact = [m for m in _modules() if n in {m["folder"].lower(), (m["module"] or "").lower(),
                                            *(p.lower() for p in m["ibek_modules"])}]
    return exact or [m for m in _modules() if n and (n in m["folder"].lower() or n in (m["module"] or "").lower())]


def _templates() -> list:
    return load()["templates"]


def _resolve(name: str) -> dict:
    """`template:` → what jnjrender --auto renders: one file, a directory of files, or nothing."""
    files = [t for t in _templates() if t["name"] == name]
    if files:
        return {"kind": "file", "templates": files[:1]}
    dirs = [d for d in load().get("template_dirs", []) if d.rsplit("/", 1)[-1] == name]
    if dirs:
        if dirs[0].startswith("ibek-templates/"):
            under = "ibek-templates/templates/" + dirs[0].split("/", 1)[1] + "/"
            inside = [t for t in _templates() if t["path"].startswith(under)]
            return {"kind": "directory", "directory": dirs[0], "templates": inside}
        return {"kind": "directory", "directory": dirs[0], "templates": [],
                "note": "a directory template from epics-support-template-infn (st.cmd.j2 / start.sh.j2), rendered "
                        "as is by the pod; it is not an ibek IOC YAML, so it is not checked here"}
    return {"kind": "none", "templates": []}


# --- search --------------------------------------------------------------------------

def _score(words: list, fields: list) -> int:
    score = 0
    for weight, text in fields:
        text = (text or "").lower()
        for w in words:
            if w == text:
                score += 6 * weight
            elif w in text:
                score += weight
    return score


def ioc_search(db, workspace_id: str, query: str, kind: Optional[str] = None, limit: int = 15) -> dict:
    """Modules, entity models, templates and examples that match the words."""
    words = [w.lower() for w in WORD.findall(query or "")]
    if not words:
        return {"error": "Say what to look for: a vendor, a device, a driver, a devtype…"}
    hits = []
    if kind in (None, "module"):
        for m in _modules():
            s = _score(words, [(4, m["folder"]), (3, m["module"]), (3, " ".join(m["ibek_modules"])),
                               (1, m["organization"]), (1, (m["readme"] or "")[:1500])])
            if s:
                hits.append((s, {"kind": "module", "name": m["folder"], "module": m["module"],
                                 "collection": m["collection"], "in_image": m["built"]["in_image"],
                                 "git_url": m["git_url"]}))
    if kind in (None, "entity_model"):
        for e in load()["entity_models"]:
            s = _score(words, [(4, e["type"]), (2, e["folder"]), (1, e["description"][:400])])
            if s:
                hits.append((s, {"kind": "entity_model", "name": e["type"],
                                 "description": e["description"].split("\n")[0][:160]}))
    if kind in (None, "template"):
        for t in _templates():
            s = _score(words, [(5, t["name"]), (2, t["group"]), (3, " ".join(t["devtypes"])),
                               (2, " ".join(t["entity_types"])), (1, (t["readme"] or "")[:1500])])
            if s:
                hits.append((s, {"kind": "template", "name": t["name"], "group": t["group"],
                                 "devtypes": t["devtypes"], "path": t["path"]}))
    if kind in (None, "example"):
        for x in load()["examples"]:
            s = _score(words, [(4, x["name"]), (3, x["template"]), (3, x["devtype"]), (1, x["iocprefix"])])
            if s:
                hits.append((s, {"kind": "example", "name": x["name"], "template": x["template"],
                                 "devtype": x["devtype"], "origin": x["origin"]}))
    hits.sort(key=lambda h: -h[0])
    limit = max(1, min(int(limit or 15), 50))
    return {"total": len(hits), "results": [h for _s, h in hits[:limit]]}


# --- reading ------------------------------------------------------------------------

def ioc_get_module(db, workspace_id: str, name: str) -> dict:
    """A support module: where its source is, how it is built, whether the image has it, its entities."""
    found = _find_module(name)
    if not found:
        return {"found": False, "suggestions": [h["name"] for h in ioc_search(db, workspace_id, name, "module")["results"]]}
    m = found[0]
    models = [e for e in load()["entity_models"] if e["folder"] == m["folder"] and e["collection"] == m["collection"]]
    out = {k: v for k, v in m.items() if k != "source"}
    out["entity_models"] = [{"type": e["type"], "description": e["description"].split("\n")[0][:200],
                             "required": [p for p, d in e["parameters"].items() if d.get("required")]} for e in models]
    out["templates_using_it"] = [t["name"] for t in _templates() if set(t["entity_types"]) & {e["type"] for e in models}]
    if m.get("source"):
        src = m["source"]
        out["source"] = {k: src.get(k) for k in ("url", "ref", "commit", "error", "readme")}
        out["source"]["files"] = [{k: f[k] for k in f if k != "text"} for f in src.get("files", [])]
    if len(found) > 1:
        out["also_matching"] = [f"{x['collection']}/{x['folder']}" for x in found[1:]]
    return {"found": True, **out}


def ioc_get_entity_model(db, workspace_id: str, type: str) -> dict:
    """One entity model whole: parameters with types and defaults, the st.cmd lines, the databases."""
    models = _models()
    model = models.get(type) or next((m for t, m in models.items() if t.lower() == (type or "").lower()), None)
    if model is None:
        prefix = (type or "").split(".")[0].lower()
        return {"found": False, "same_module": sorted(t for t in models if t.split(".")[0].lower() == prefix)[:40],
                "suggestions": [h["name"] for h in ioc_search(db, workspace_id, type, "entity_model")["results"][:10]]}
    return {"found": True, **model, "availability": _availability(model)}


def ioc_get_template(db, workspace_id: str, name: str, include_source: bool = True) -> dict:
    """A template: what it reads from the beamline entry, which devtypes it branches on, what it emits."""
    resolved = _resolve(name)
    if resolved["kind"] == "none":
        return {"found": False, "suggestions": [h["name"] for h in ioc_search(db, workspace_id, name, "template")["results"]]}
    if not resolved["templates"]:
        return {"found": True, **resolved}
    t = resolved["templates"][0]
    models = _models()
    out = {k: v for k, v in t.items() if include_source or k != "source"}
    out["resolution"] = {"kind": resolved["kind"], "renders": [x["path"] for x in resolved["templates"]]}
    out["emits"] = [{"type": e, "known": e in models, **(_availability(models[e]) if e in models else {})}
                    for e in t["entity_types"]]
    out["examples"] = [x["name"] for x in load()["examples"] if x["template"] == t["name"]]
    return {"found": True, **out}


def ioc_get_example(db, workspace_id: str, name: str) -> dict:
    """A worked beamline entry: an ibek-templates test fixture or a config from infn-epics-ioc."""
    examples = load()["examples"]
    x = next((e for e in examples if e["name"] == name), None) or \
        next((e for e in examples if e["template"] == name), None)
    if x is None:
        return {"found": False, "examples": [{"name": e["name"], "template": e["template"], "devtype": e["devtype"]}
                                             for e in examples]}
    return {"found": True, **x, "others_for_template": [e["name"] for e in examples
                                                        if e["template"] == x["template"] and e is not x]}


def ioc_guide(db, workspace_id: str, section: Optional[str] = None) -> dict:
    """How infn-epics-ioc, ibek-support-infn, ibek-templates and the beamlines fit together."""
    cat = load()
    text = cat.get("guide") or ""
    parts = re.split(r"(?m)^## ", text)
    sections = {p.split("\n", 1)[0].strip(): p.split("\n", 1)[1] if "\n" in p else "" for p in parts[1:]}
    about = {"repository": cat.get("repository"), "generated_at": cat.get("generated_at"),
             "loaded_from": cat.get("loaded_from"),
             "beamlines": {b["name"]: {"iocs": len(b.get("iocs") or []), "commit": b.get("commit")}
                           for b in cat.get("beamlines") or []},
             "modules": len(cat["modules"]), "entity_models": len(cat["entity_models"]),
             "templates": len(cat["templates"]), "examples": len(cat["examples"]),
             "problems": cat.get("problems", [])[:30]}
    if section:
        s = section.lower()
        hit = next((k for k in sections if s in k.lower()), None)
        if hit:
            return {"section": hit, "text": sections[hit], "catalogue": about}
    return {"sections": list(sections), "text": text if not section else None, "catalogue": about,
            "workflow": WORKFLOW}


WORKFLOW = [
    "1. Existing hardware type: ioc_search the vendor/device, ioc_get_template, start from ioc_get_example, "
    "then ioc_render your entry: it must come back with no errors.",
    "2. Existing driver but no template: ioc_get_module (entity models, required parameters), write the template, "
    "check it with ioc_render(values, template_source=…).",
    "3. New driver: ioc_scaffold_driver, adapt the entity models to the driver's db templates and st.cmd "
    "(ioc_get_module shows the source's macros when the catalogue was built with --sources), then add "
    "ansible.sh <folder> to the Dockerfile, bump the submodules and tag a release.",
    "4. Deploy: add the entry under epicsConfiguration.iocs in the beamline values.yaml (iocDefaults may hold the "
    "family defaults: ioc_render(values, beamline=…) applies them), commit, sync the ArgoCD application.",
    "5. A beamline in the catalogue: ioc_list_beamline, ioc_get_beamline_ioc for one IOC as deployed, "
    "ioc_check_beamline before bumping the image or a template.",
]


# --- render and validate --------------------------------------------------------------

def _values(values: Any) -> tuple[Optional[dict], Optional[str]]:
    if isinstance(values, dict):
        return values, None
    try:
        data = yaml.safe_load(values or "")
    except yaml.YAMLError as e:
        return None, f"The values are not YAML: {e}"
    if not isinstance(data, dict):
        return None, "The values must be one IOC entry: a mapping with template, iocprefix, devices, …"
    # A pasted beamline block: epicsConfiguration.iocs.<name>: {...}, or iocs: {<name>: {...}}
    iocs = (data.get("epicsConfiguration") or {}).get("iocs") if isinstance(data.get("epicsConfiguration"), dict) else None
    iocs = iocs if iocs is not None else (data.get("iocs") if "template" not in data else None)
    # …or the IOC's own block as it sits under iocs: `ocem-modbus4chan0: {template: ocem, …}`
    if iocs is None and "template" not in data and len(data) == 1:
        only = next(iter(data.values()))
        if isinstance(only, dict) and "template" in only:
            iocs = data
    if isinstance(iocs, dict) and len(iocs) == 1:
        name, entry = next(iter(iocs.items()))
        data = {"name": name, **(entry or {})}
    elif isinstance(iocs, list) and len(iocs) == 1:
        data = iocs[0]
    elif iocs:
        return None, "That holds several IOCs; pass one entry at a time."
    return data, None


def _render(source: str, values: dict) -> tuple[Optional[str], list, Optional[str]]:
    empty: set = set()

    class Tracking(Undefined):
        """Renders as nothing, as jnjrender's does, but remembers which variables did."""

        def __str__(self):
            empty.add(self._undefined_name or "?")
            return ""

    env = SandboxedEnvironment(undefined=Tracking)
    try:
        return env.from_string(source).render(values), sorted(empty), None
    except Exception as e:
        return None, sorted(empty), f"{type(e).__name__}: {e}"


def _check_value(kind: str, value: Any, spec: dict) -> Optional[str]:
    if value is None:
        return f"is empty (null); ibek expects a {kind}: usually a key the template read was missing from the entry"
    if isinstance(value, str) and JINJA.search(value):
        return None  # ibek renders it later
    if kind == "int" and (isinstance(value, bool) or not isinstance(value, int)):
        if not (isinstance(value, str) and re.fullmatch(r"-?(0x[0-9a-fA-F]+|\d+)", value.strip())):
            return f"expects an int, got {value!r}"
    if kind == "float" and (isinstance(value, bool) or not isinstance(value, (int, float))):
        try:
            float(value)
        except (TypeError, ValueError):
            return f"expects a float, got {value!r}"
    if kind == "bool" and not isinstance(value, bool) and str(value).lower() not in ("true", "false"):
        return f"expects true/false, got {value!r}"
    if kind == "enum" and spec.get("values") and str(value) not in [str(v) for v in spec["values"]]:
        return f"must be one of {spec['values']}, got {value!r}"
    return None


def validate_instance(document: Any, extra_models: Optional[dict] = None) -> dict:
    """What `ibek runtime generate` would object to in an IOC instance YAML."""
    errors, warnings = [], []
    if isinstance(document, str):
        try:
            document = yaml.safe_load(document)
        except yaml.YAMLError as e:
            return {"ok": False, "errors": [f"The rendered IOC is not valid YAML: {e}"], "warnings": [], "entities": []}
    if not isinstance(document, dict):
        return {"ok": False, "errors": ["An IOC instance is a mapping with ioc_name and entities."], "warnings": [],
                "entities": []}
    models = {**_models(), **(extra_models or {})}
    if not document.get("ioc_name"):
        errors.append("ioc_name is empty: the chart injects iocname; set it when rendering by hand.")
    entities = document.get("entities") or []
    if not isinstance(entities, list) or not entities:
        errors.append("No entities: the IOC would start with nothing in it.")
        entities = entities if isinstance(entities, list) else []
    ids: dict = {}
    refs: list = []
    summary = []
    for i, entity in enumerate(entities):
        where = f"entities[{i}]"
        if not isinstance(entity, dict) or not entity.get("type"):
            errors.append(f"{where}: an entity needs a type.")
            continue
        etype = entity["type"]
        model = models.get(etype)
        summary.append(etype)
        if model is None:
            prefix = etype.split(".")[0]
            near = sorted(t for t in models if t.split(".")[0] == prefix)
            errors.append(f"{where}: unknown entity type {etype}" +
                          (f"; module {prefix} defines {', '.join(near[:12])}" if near else
                           "; no support module defines it"))
            continue
        if entity.get("entity_enabled") is False:
            continue
        if extra_models is None or etype not in extra_models:
            avail = _availability(model)
            if not avail["in_image"]:
                errors.append(f"{where}: {etype} is defined but not compiled into the image: {avail['how']}.")
        params = model["parameters"]
        for key, spec in params.items():
            value = entity.get(key, spec.get("default"))
            if key not in entity and spec.get("required"):
                errors.append(f"{where} ({etype}): missing required parameter {key}.")
                continue
            if key not in entity:
                continue
            problem = _check_value(spec["type"], value, spec)
            if problem:
                errors.append(f"{where} ({etype}).{key} {problem}.")
            if spec["type"] == "id":
                if str(value) in ids:
                    errors.append(f"{where} ({etype}).{key}: id {value!r} is already used by {ids[str(value)]}.")
                ids[str(value)] = f"{where} ({etype})"
            if spec["type"] == "object":
                refs.append((where, etype, key, value))
        unknown = sorted(set(entity) - set(params) - ENTITY_KEYS)
        if unknown:
            warnings.append(f"{where} ({etype}): parameters the model does not declare: {', '.join(unknown)} "
                            f"(ibek refuses them).")
    for where, etype, key, value in refs:
        if isinstance(value, str) and JINJA.search(value):
            continue
        if str(value) not in ids:
            errors.append(f"{where} ({etype}).{key} refers to {value!r}, which no entity declares as its id.")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "entities": summary}


def ioc_render(db, workspace_id: str, values: Any, template: Optional[str] = None,
               template_source: Optional[str] = None, beamline: Optional[str] = None) -> dict:
    """Render a beamline IOC entry as the pod will, then check what ibek will make of it."""
    data, problem = _values(values)
    if problem:
        return {"ok": False, "errors": [problem]}
    notes = []
    if beamline:
        line = _beamline(beamline)
        if line is None:
            return {"ok": False, "errors": [f"No beamline {beamline!r} in the catalogue."],
                    "beamlines": [b["name"] for b in _beamlines()]}
        d = deployed_values(line, data)
        data = d["values"]
        if d["defaults_key"]:
            notes.append(f"iocDefaults.{d['defaults_key']} of {line['name']} merged under the entry.")
        notes += d["ignored_by_merge"]
    if not data.get("iocname"):
        data["iocname"] = str(data.get("name") or "ioc-under-test").lower()
        notes.append(f"iocname is injected by epik8s-chart at deploy time; rendered with iocname={data['iocname']!r}.")
    name = template or data.get("template")
    if template_source:
        sources = [("(template_source)", template_source)]
        resolved = {"kind": "inline"}
    else:
        if not name:
            return {"ok": False, "errors": ["No template: set `template:` in the values or pass template."]}
        resolved = _resolve(name)
        if resolved["kind"] == "none":
            return {"ok": False, "errors": [f"Template {name!r} is not under the image's templates; the pod would exit "
                                            "with code 7 (template directory not found)."],
                    "suggestions": [h["name"] for h in ioc_search(db, workspace_id, name, "template")["results"]]}
        if not resolved["templates"]:
            return {"ok": True, "resolution": resolved, "notes": notes}
        sources = [(t["path"], t["source"]) for t in resolved["templates"]]
    image = str(data.get("image") or "")
    if image and "infn-epics-ioc-runtime" not in image:
        notes.append(f"This entry runs {image}; the checks below are against the infn-epics-ioc-runtime image the "
                     "catalogue was built from, so types that only that image has show as unknown.")
    if len(sources) > 1:
        notes.append(f"template {name!r} resolves to a directory with {len(sources)} YAML templates; ioc/start.sh "
                     "refuses a config holding more than one *.yaml.")
    outputs = []
    ok = True
    for path, source in sources:
        rendered, empty, error = _render(source, data)
        if error:
            outputs.append({"template": path, "error": error, "rendered_empty": empty})
            ok = False
            continue
        report = validate_instance(rendered)
        ok = ok and report["ok"]
        if data.get("devtype") and path != "(template_source)":
            t = next((x for x in _templates() if x["path"] == path), None)
            if t and len(t["devtypes"]) > 1 and data["devtype"] not in t["devtypes"]:
                report["warnings"].append(f"devtype {data['devtype']!r} matches none of the branches this template "
                                          f"tests ({', '.join(t['devtypes'])}); check which one it fell into.")
        outputs.append({"template": path, "yaml": rendered, "rendered_empty": empty, **report})
    return {"ok": ok, "resolution": {k: v for k, v in resolved.items() if k != "templates"}, "notes": notes,
            "outputs": outputs,
            "next": "Errors are what `ibek runtime generate` would stop on at pod start. rendered_empty lists the "
                    "variables the template printed as nothing: usually a key missing from the entry."}


def ioc_validate(db, workspace_id: str, ioc_yaml: str) -> dict:
    """Check an ibek IOC instance YAML (ioc_name, entities) against the entity models and the image."""
    return validate_instance(ioc_yaml)


# --- a new driver ---------------------------------------------------------------------

def _id(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", text.strip()).strip("-")


def ioc_scaffold_driver(db, workspace_id: str, folder: str, repository: str,
                        organization: str = "https://github.com/infn-epics/", version: str = "main",
                        protocol: str = "stream", group: str = "io", devtype: Optional[str] = None,
                        db_template: Optional[str] = None, proto_file: Optional[str] = None,
                        description: Optional[str] = None, default_port: int = 4001) -> dict:
    """The files a new INFN driver needs, in the house style, checked against each other."""
    folder, repository = _id(folder), _id(repository)
    if not folder or not repository:
        return {"error": "folder (the ibek-support-infn directory) and repository (the driver's git repo) are needed."}
    protocol = protocol if protocol in ("stream", "modbus", "asyn") else "stream"
    group = group if group in GROUPS else "io"
    devtype = devtype or folder.lower()
    prefix = folder
    db_template = db_template or f"{repository}.template"
    proto_file = proto_file or f"db/{repository}.proto"
    what = description or f"{folder} device"
    exists = _find_module(folder)

    libs = {"stream": ["asyn", "stream"], "modbus": ["asyn", "modbus"], "asyn": ["asyn"]}[protocol]
    dbds = {"stream": ["asyn.dbd", "stream.dbd"], "modbus": ["asyn.dbd", "modbusSupport.dbd"],
            "asyn": ["asyn.dbd"]}[protocol]
    install = (
        "# yaml-language-server: $schema=../../ibek-support/_scripts/support_install_variables.json\n"
        f"module: {repository}\n"
        f"organization: {organization.rstrip('/')}/\n"
        f"# a release tag makes the image reproducible; a branch follows whatever was pushed last\n"
        f"version: {version}\n\n"
        "dbds:\n" + "".join(f"  - {d}\n" for d in dbds) +
        "\nlibs:\n" + "".join(f"  - {lib}\n" for lib in libs) +
        (f"\nprotocol_files:\n  - {proto_file}\n" if protocol == "stream" else "")
    )
    port_setup = {
        "stream": f'epicsEnvSet "STREAM_PROTOCOL_PATH", "/epics/support/configure/protocol/"\n'
                  '          drvAsynIPPortConfigure("{{NAME}}", "{{IP}}:{{PORT}}", 0, 0, 0)',
        "modbus": 'drvAsynIPPortConfigure("{{NAME}}_TCP", "{{IP}}:{{PORT}}", 0, 0, 1)\n'
                  '          modbusInterposeConfig("{{NAME}}_TCP", 0, {{TIMEOUT}}, 0)',
        "asyn": 'drvAsynIPPortConfigure("{{NAME}}", "{{IP}}:{{PORT}}", 0, 0, 0)',
    }[protocol]
    support = f"""# yaml-language-server: $schema=https://github.com/epics-containers/ibek/releases/download/3.1.2/ibek.support.schema.json

module: {prefix}

entity_models:
  - name: device
    description: |-
      {what}, reached over TCP/IP ({protocol}).
    parameters:
      NAME:
        type: id
        description: |-
          Asyn port name (unique in the IOC)
      P:
        type: str
        description: |-
          PV prefix (the IOC's iocprefix)
      R:
        type: str
        description: |-
          PV suffix (the device name)
      IP:
        type: str
        description: |-
          Device or terminal-server address
        default: 127.0.0.1
      PORT:
        type: int
        description: |-
          TCP port
        default: {int(default_port)}
      TIMEOUT:
        type: int
        description: |-
          Communication timeout in ms
        default: 1000

    pre_init:
      - value: |
          {port_setup}

    databases:
      - file: {db_template}
        args:
          P: "{{{{P}}}}"
          R: "{{{{R}}}}"
          PORT: "{{{{NAME}}}}"
"""
    template = f"""ioc_name: {{{{ iocname }}}}
description: {what} (template {folder})

entities:
{{%- for device in devices %}}
- type: {prefix}.device
  NAME: "{{{{ device.name }}}}"
  P: "{{{{ iocprefix }}}}"
  R: "{{{{ device.name }}}}"
  IP: "{{{{ device.ip | default(server) }}}}"
  PORT: {{{{ device.port | default(port) | default({int(default_port)}) }}}}
  TIMEOUT: {{{{ device.timeout | default(timeout) | default(1000) }}}}
{{%- endfor %}}

- type: epics.PostStartupCommand
  command: |
    epicsThreadSleep 1.0
{{%- if iocexit %}}
    dbl
    exit
{{%- else %}}
    dbl("*") > {{{{ config_dir }}}}/pvlist.txt
    dbl
{{%- endif %}}
"""
    fixture = f"""# yaml-language-server: $schema=https://raw.githubusercontent.com/infn-epics/ibek-templates/refs/heads/main/schemas/ioc.schema.json
iocname: "{group}-{folder.lower()}-test"
template: "{folder}"
devtype: {devtype}
devgroup: {group}
iocprefix: "TEST:{group.upper()}:{folder.upper()}"
server: "192.168.1.10"
port: {int(default_port)}
devices:
  - name: "{folder.upper()}01"
  - name: "{folder.upper()}02"
    port: {int(default_port) + 1}
"""
    files = {
        f"ibek-support-infn/{folder}/{folder}.install.yml": install,
        f"ibek-support-infn/{folder}/{folder}.ibek.support.yaml": support,
        f"ibek-templates/templates/{group}/{folder}/{folder}.yaml.j2": template,
        f"ibek-templates/tests/{group}-{folder.lower()}-test.yaml": fixture,
    }
    # The drafts must agree with each other before anybody builds an image to find out they do not.
    drafted = []
    data = yaml.safe_load(support)
    for m in data["entity_models"]:
        drafted.append({"type": f"{prefix}.{m['name']}", "parameters": {
            k: ({"type": v["type"], "default": v["default"]} if "default" in v else {"type": v["type"], "required": True})
            for k, v in m["parameters"].items()}})
    rendered, empty, error = _render(template, {**yaml.safe_load(fixture)})
    check = {"error": error} if error else validate_instance(rendered, {d["type"]: d for d in drafted})
    similar = [m["folder"] for m in _modules() if m["collection"] == "infn"
               and set(m["libs"]) >= set(libs) and m["built"]["in_image"]][:6]
    return {
        "files": files,
        "dockerfile": f"Add `ansible.sh {folder}` to the RUN chain in infn-epics-ioc/Dockerfile (one layer, "
                      "keep it under the 127-layer limit).",
        "self_check": {"rendered_fixture": rendered, "rendered_empty": empty, **check},
        "already_exists": [f"{m['collection']}/{m['folder']}" for m in exists],
        "compare_with": similar,
        "steps": [
            f"Check db_template ({db_template}) and its macros against the driver repository "
            f"({organization.rstrip('/')}/{repository}); add a parameter for every macro without a default.",
            "Add entity models for what the driver has besides one device per port (controllers, axes, channels).",
            "Run ibek-support-infn/tests/test_ioc_generate.sh, then render the fixture: "
            f"jnjrender templates/ tests/{group}-{folder.lower()}-test.yaml --auto --output /tmp/out",
            "Add the template's IOC-level keys to ibek-templates/schemas/ioc.schema.json.",
            f"Add `ansible.sh {folder}` to the Dockerfile, bump both submodules in infn-epics-ioc, tag a release.",
        ],
    }


# --- beamlines ------------------------------------------------------------------------

def _empty(value: Any) -> bool:
    """What Go's mergo counts as empty, and so never lets overwrite a default."""
    return value is None or value is False or value == 0 and not isinstance(value, bool) or value in ("", [], {})


def _merge_overwrite(defaults: dict, entry: dict, path: str = "", ignored: Optional[list] = None) -> dict:
    """Sprig's mustMergeOverwrite(deepCopy(defaults), entry), which epik8s-chart uses for iocDefaults: the entry
    wins key by key, maps merge, and an empty value in the entry (false, 0, "", null, []) does not replace a
    non-empty default. That last rule surprises people (`autosync: false` under a default of true is ignored),
    so every such key is reported."""
    out = dict(defaults)
    for key, value in entry.items():
        here = f"{path}{key}"
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_overwrite(out[key], value, f"{here}.", ignored)
        elif _empty(value) and key in out and not _empty(out[key]):
            if ignored is not None:
                ignored.append(f"{here}: {value!r} in the entry is ignored, iocDefaults keeps {out[key]!r}")
        else:
            out[key] = value
    return out


def _beamlines() -> list:
    return load().get("beamlines") or []


def _beamline(name: Optional[str]) -> Optional[dict]:
    lines = _beamlines()
    if not name and len(lines) == 1:
        return lines[0]
    n = (name or "").lower()
    return next((b for b in lines if b["name"].lower() == n or (b.get("url") or "").lower().rstrip("/").endswith(n)),
                None)


def _mode(values: dict) -> str:
    """Which branch of ioc-chart's start-up the pod takes: host first, then template, else a git config dir."""
    if values.get("host"):
        return "host"
    if values.get("template"):
        return "template"
    return "git"


def deployed_values(beamline: dict, entry: dict) -> dict:
    """The entry as /tmp/iocconfig.yaml holds it in the pod: iocDefaults merged under it, what epik8s-chart
    injects (beamline, iocname, ioc_version, nfsMounts) and the directories ioc-chart's ConfigMap adds."""
    ignored: list = []
    key = entry.get("template") or entry.get("devtype") or ""
    defaults = (beamline.get("ioc_defaults") or {}).get(key) if key else None
    merged = _merge_overwrite(defaults, entry, ignored=ignored) if isinstance(defaults, dict) else dict(entry)
    g = beamline.get("globals") or {}
    name = str(merged.get("name") or "").lower()
    injected: dict = {}
    mounts = merged.get("nfsMounts") or g.get("nfsMounts")
    if mounts:
        injected.update({f"{str(m.get('name')).lower()}_dir": f"{m.get('mountPath')}/{name}" for m in mounts
                         if isinstance(m, dict)})
    else:
        injected.update(config_dir="/epics/ioc/config", autosave_dir="/autosave")
    injected["ioctop"] = merged.get("workdir") or "/epics/ioc/config"
    # ioc-chart writes each iocparam as a top-level `name: value` line, before the values themselves.
    for p in merged.get("iocparam") or []:
        if isinstance(p, dict) and p.get("name"):
            try:
                injected[str(p["name"])] = yaml.safe_load(f"{p.get('value')}") if p.get("value") is not None else None
            except yaml.YAMLError:
                injected[str(p["name"])] = p.get("value")
    values = {**injected, **merged}
    if mounts:
        values["nfsMounts"] = mounts
    if g.get("ioc_version") and not merged.get("image"):
        values["ioc_version"] = g["ioc_version"]
    values["beamline"] = g.get("beamline") or beamline["name"]
    values["iocname"] = name
    return {"values": values, "defaults_key": key if defaults is not None else None, "ignored_by_merge": ignored}


def _ioc_row(beamline: dict, entry: dict) -> dict:
    d = deployed_values(beamline, entry)["values"]
    return {"name": d["iocname"], "template": d.get("template"), "devtype": d.get("devtype"),
            "devgroup": d.get("devgroup"), "iocprefix": d.get("iocprefix"), "mode": _mode(d),
            "disabled": bool(d.get("disable")), "devices": len(d.get("devices") or [])}


def ioc_list_beamline(db, workspace_id: str, beamline: Optional[str] = None, template: Optional[str] = None,
                      query: Optional[str] = None) -> dict:
    """The beamlines in the catalogue, or one beamline's IOCs as deployed."""
    line = _beamline(beamline) if beamline else None
    if line is None:
        return {"beamlines": [{"name": b["name"], "url": b.get("url"), "commit": b.get("commit"),
                               "iocs": len(b.get("iocs") or []), "error": b.get("error")} for b in _beamlines()],
                **({"not_found": beamline} if beamline else {})}
    rows = [_ioc_row(line, e) for e in line.get("iocs") or []]
    if template:
        rows = [r for r in rows if r["template"] == template]
    if query:
        q = query.lower()
        rows = [r for r in rows if any(q in str(v).lower() for v in r.values() if v)]
    by_template: dict = {}
    for r in rows:
        by_template[r["template"] or f"({r['mode']})"] = by_template.get(r["template"] or f"({r['mode']})", 0) + 1
    return {"beamline": line["name"], "url": line.get("url"), "commit": line.get("commit"),
            "value_files": line.get("value_files"), "ioc_defaults": sorted(line.get("ioc_defaults") or {}),
            "total": len(rows), "by_template": by_template, "iocs": rows}


def _entry(line: dict, name: str) -> Optional[dict]:
    n = (name or "").lower()
    return next((e for e in line.get("iocs") or [] if str(e.get("name", "")).lower() == n), None)


def ioc_get_beamline_ioc(db, workspace_id: str, beamline: str, name: str, render: bool = True) -> dict:
    """One IOC of a beamline: its entry, the iocDefaults it inherits, what the pod receives, and the render."""
    line = _beamline(beamline)
    if line is None:
        return {"found": False, **ioc_list_beamline(db, workspace_id)}
    entry = _entry(line, name)
    if entry is None:
        close = [r["name"] for r in ioc_list_beamline(db, workspace_id, line["name"], query=name)["iocs"]][:20]
        return {"found": False, "beamline": line["name"], "similar": close}
    d = deployed_values(line, entry)
    out = {"found": True, "beamline": line["name"], "entry": entry, "defaults_key": d["defaults_key"],
           "defaults": (line.get("ioc_defaults") or {}).get(d["defaults_key"]) if d["defaults_key"] else None,
           "ignored_by_merge": d["ignored_by_merge"], "deployed": d["values"], "mode": _mode(d["values"])}
    if render and out["mode"] == "template" and not d["values"].get("disable"):
        out["render"] = ioc_render(db, workspace_id, d["values"])
    elif out["mode"] != "template":
        out["note"] = {"host": "runs natively on a remote host through epik8s-run; not an ibek render",
                       "git": "no template: the pod takes config/iocs/<iocdir|name> from the beamline repository "
                              "(st.cmd.j2, start.sh); not an ibek render"}[out["mode"]]
    return out


def ioc_check_beamline(db, workspace_id: str, beamline: str, template: Optional[str] = None) -> dict:
    """Render and check every templated, enabled IOC of a beamline: what would fail at its next sync."""
    line = _beamline(beamline)
    if line is None:
        return {"found": False, **ioc_list_beamline(db, workspace_id)}
    passed, failed, skipped, ignored = [], [], [], []
    for entry in line.get("iocs") or []:
        d = deployed_values(line, entry)
        v = d["values"]
        if template and v.get("template") != template:
            continue
        if d["ignored_by_merge"]:
            ignored.append({"ioc": v["iocname"], "keys": d["ignored_by_merge"]})
        if v.get("disable") or _mode(v) != "template":
            skipped.append({"ioc": v["iocname"], "why": "disabled" if v.get("disable") else _mode(v)})
            continue
        r = ioc_render(db, workspace_id, v)
        if r["ok"]:
            passed.append(v["iocname"])
            continue
        errors = list(r.get("errors") or [])
        for o in r.get("outputs") or []:
            errors += ([o["error"]] if o.get("error") else []) + (o.get("errors") or [])
        failed.append({"ioc": v["iocname"], "template": v.get("template"), "devtype": v.get("devtype"),
                       "errors": errors[:5], "more": max(0, len(errors) - 5)})
    return {"beamline": line["name"], "commit": line.get("commit"), "passed": len(passed), "failed": failed,
            "skipped": skipped, "ignored_by_merge": ignored,
            "next": "ioc_get_beamline_ioc shows one IOC's deployed values and full render."}
