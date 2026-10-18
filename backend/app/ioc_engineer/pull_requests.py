"""A pull request the IOC engineer proposes, opened only once a person confirms it.

Ask ARGUS can draft the files an IOC needs (a beamline entry, a template and its fixture, a driver's
install.yml and ibek.support.yaml). Turning a draft into a pull request is the one step that leaves ARGUS, so it
goes through the same gate as every other change the assistant proposes (services/ask_actions.py): the model can
only propose; the proposal is checked as it is made and shown under the answer; nothing happens until the person
applies it. Two approvals stand between a description and a running IOC:

    1. the person in Ask ARGUS, signed in (not an API token) and allowed to approve in the workspace, confirms;
       the checks run again at that moment, against the catalogue the hub has then;
    2. the repository's reviewers review the pull request; ARGUS opens it (a draft by default) and never merges.

What is checked before a proposal stands: the repository is one ARGUS may open pull requests on
(ARGUS_IOC_PR_REPOS); paths stay inside the repository and out of .github/ (CI is not the assistant's to
change); YAML parses; support definitions declare their entity models; and every template, fixture and IOC entry
in the change renders and passes the same check as ioc_render, with the entity models proposed in the same
change, or earlier in the conversation, counted as known.

The pull request is made with one service credential (ARGUS_GITHUB_TOKEN), scoped by whoever installs it to
the repositories in the allowlist: contents and pull requests, read and write. Its body names the person who
confirmed it.
"""
from __future__ import annotations

import os
import re
import secrets
from pathlib import PurePosixPath
from typing import Any, Optional

import yaml

from app.ioc_engineer import tools

DEFAULT_REPOS = "infn-epics/ibek-support-infn,infn-epics/ibek-templates,infn-epics/infn-epics-ioc"
MAX_FILES = 20
MAX_BYTES = 200_000
API = "https://api.github.com"


class Refused(ValueError):
    """A change that cannot be proposed (or opened) as it stands; the reason goes back to the model."""


# --- configuration ---------------------------------------------------------------------------------------------

def repositories() -> list[str]:
    raw = os.environ.get("ARGUS_IOC_PR_REPOS", DEFAULT_REPOS)
    return [r.strip().lower() for r in raw.split(",") if r.strip()]


def enabled() -> bool:
    """Offered to the assistant only where an administrator has installed a credential."""
    return bool(os.environ.get("ARGUS_GITHUB_TOKEN")) and bool(repositories())


def _draft() -> bool:
    return os.environ.get("ARGUS_IOC_PR_DRAFT", "true").strip().lower() not in ("0", "false", "no")


# --- the checks ------------------------------------------------------------------------------------------------

def _safe_path(path: str) -> str:
    p = str(path or "").strip().replace("\\", "/")
    parts = PurePosixPath(p).parts
    if not p or p.startswith("/") or any(x in ("..", ".", "") for x in p.split("/")) or not parts:
        raise Refused(f"{path!r} is not a path inside the repository")
    if parts[0] == ".github" or parts[0] == ".git":
        raise Refused(f"{p}: the repository's CI and git configuration are not changed from ARGUS")
    return p


def safe_branch(name: Optional[str]) -> Optional[str]:
    """A branch name as git allows it, and nothing that could steer the API path it is put in."""
    b = str(name or "").strip()
    if not b:
        return None
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", b) or ".." in b or b.startswith(("/", "-")) or b.endswith("/"):
        raise Refused(f"{name!r} is not a branch name")
    return b


def _models_in(files: dict) -> dict:
    """Entity models defined by *.ibek.support.yaml files in a change, as validate_instance wants them."""
    models = {}
    for path, text in files.items():
        if not path.endswith(".ibek.support.yaml"):
            continue
        data = yaml.safe_load(text) or {}
        prefix = data.get("module")
        for m in data.get("entity_models") or []:
            params = {}
            for k, v in (m.get("parameters") or {}).items():
                v = v if isinstance(v, dict) else {}
                spec = {"type": v.get("type", "str")}
                if "default" in v:
                    spec["default"] = v["default"]
                else:
                    spec["required"] = True
                if v.get("type") == "enum":
                    values = v.get("values") or {}
                    spec["values"] = list(values) if isinstance(values, dict) else list(values)
                params[k] = spec
            models[f"{prefix}.{m.get('name')}"] = {"type": f"{prefix}.{m.get('name')}", "parameters": params}
    return models


def _render_problems(values: str, template_source: Optional[str], models: dict) -> list[str]:
    """ioc_render's verdict on one entry, with the change's own entity models counted as known."""
    if template_source is None:
        r = tools.ioc_render(None, "", values)
    else:
        r = tools.ioc_render(None, "", values, template_source=template_source)
    problems = list(r.get("errors") or [])
    for o in r.get("outputs") or []:
        if o.get("error"):
            problems.append(o["error"])
        elif o.get("yaml") is not None and models:
            report = tools.validate_instance(o["yaml"], models)
            problems += report["errors"]
        else:
            problems += o.get("errors") or []
    return problems


def check(repository: str, files: list, prior_models: Optional[dict] = None) -> dict:
    """What a proposed change would put in the repository, checked. Refused on the first thing that would fail."""
    repo = str(repository or "").strip().lower()
    if repo not in repositories():
        raise Refused(f"ARGUS opens pull requests only on {', '.join(repositories())}; not on {repository!r}")
    if not isinstance(files, list) or not files:
        raise Refused("files must be a list of {path, content}")
    if len(files) > MAX_FILES:
        raise Refused(f"at most {MAX_FILES} files in one pull request")
    change: dict = {}
    for f in files:
        if not isinstance(f, dict) or not isinstance(f.get("content"), str):
            raise Refused("each file is {path, content} with the whole new content as text")
        path = _safe_path(f.get("path"))
        if path in change:
            raise Refused(f"{path} appears twice")
        if len(f["content"].encode("utf-8")) > MAX_BYTES:
            raise Refused(f"{path} is larger than {MAX_BYTES // 1000} kB")
        # Never a credential in a pull request: the same scan exports go through (names where, never the value).
        from app.portability.secret_scan import scan_text
        found = scan_text(f["content"], path)
        if found:
            raise Refused(f"{path} looks like it holds a credential ({found[0].get('kind', 'secret')}); "
                          "configuration secrets belong in the deployment's Secret, not in a repository")
        change[path] = f["content"]

    notes = []
    for path, text in change.items():
        if path.endswith((".yaml", ".yml")):
            try:
                data = yaml.safe_load(text)
            except yaml.YAMLError as e:
                raise Refused(f"{path} is not valid YAML: {e}")
            if path.endswith(".ibek.support.yaml"):
                if not isinstance(data, dict) or not data.get("module") or not data.get("entity_models"):
                    raise Refused(f"{path} needs a module and its entity_models")
            if path.endswith((".install.yml", ".install.yaml")):
                if not isinstance(data, dict) or not data.get("module"):
                    raise Refused(f"{path} needs at least module: (and organization:, version:)")

    models = {**(prior_models or {}), **_models_in(change)}
    templates = {PurePosixPath(p).name[: -len(".yaml.j2")]: t for p, t in change.items() if p.endswith(".yaml.j2")}

    # ibek-templates fixtures render against the template in the change, or the image's.
    rendered = set()
    for path, text in change.items():
        data = yaml.safe_load(text) if path.endswith((".yaml", ".yml")) else None
        if not isinstance(data, dict) or not data.get("template"):
            continue
        is_fixture = repo.endswith("/ibek-templates") and path.startswith("tests/")
        is_config = repo.endswith("/infn-epics-ioc") and path.endswith("-config.yaml")
        if not (is_fixture or is_config):
            continue
        problems = _render_problems(text, templates.get(data["template"]), models)
        if problems:
            raise Refused(f"{path} would not start: " + "; ".join(problems[:6]))
        rendered.add(data["template"])
        notes.append(f"{path}: renders and passes the ibek check (template {data['template']})")
    for name in sorted(set(templates) - rendered):
        notes.append(f"template {name}: no fixture in this change renders it; add tests/<group>-{name}-test.yaml")
    return {"repository": repo, "files": change, "checks": notes, "models": sorted(_models_in(change))}


# --- opening it ------------------------------------------------------------------------------------------------

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "change"


def _gh(method: str, path: str, **kwargs) -> Any:
    import requests
    token = os.environ.get("ARGUS_GITHUB_TOKEN")
    if not token:
        raise Refused("no ARGUS_GITHUB_TOKEN is installed: an administrator must add one before ARGUS opens pull requests")
    response = requests.request(method, f"{os.environ.get('ARGUS_GITHUB_API', API)}{path}", timeout=30,
                                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                         "X-GitHub-Api-Version": "2022-11-28"}, **kwargs)
    if response.status_code >= 400:
        try:
            message = response.json().get("message")
        except ValueError:
            message = response.text[:200]
        raise Refused(f"GitHub refused {method} {path}: {response.status_code} {message}")
    return response.json() if response.content else {}


def open_pull_request(payload: dict, actor: str, prior_models: Optional[dict] = None) -> dict:
    """Check the change again, then make one commit on a new branch and open the pull request."""
    files = [{"path": p, "content": c} for p, c in payload["files"].items()]
    checked = check(payload["repository"], files, prior_models)
    repo = checked["repository"]
    meta = _gh("GET", f"/repos/{repo}")
    base = safe_branch(payload.get("base")) or safe_branch(meta.get("default_branch")) or "main"
    head = _gh("GET", f"/repos/{repo}/git/ref/heads/{base}")["object"]["sha"]
    tree = _gh("GET", f"/repos/{repo}/git/commits/{head}")["tree"]["sha"]
    new_tree = _gh("POST", f"/repos/{repo}/git/trees", json={
        "base_tree": tree,
        "tree": [{"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in checked["files"].items()]})
    message = f"{payload['title']}\n\n{payload.get('description') or ''}".strip() + \
        f"\n\nProposed in ARGUS (IOC engineer), confirmed by {actor}."
    commit = _gh("POST", f"/repos/{repo}/git/commits",
                 json={"message": message, "tree": new_tree["sha"], "parents": [head]})
    branch = f"argus/{_slug(payload['title'])}-{secrets.token_hex(3)}"
    _gh("POST", f"/repos/{repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
    checks = [f"- {n}" for n in checked["checks"]] or ["- YAML parses; no IOC entry, template or fixture to render"]
    body = "\n".join([
        payload.get("description") or "",
        "",
        "## Checks run by ARGUS",
        *checks,
        "",
        "## Files",
        *[f"- `{p}`" for p in checked["files"]],
        "",
        f"Proposed by the ARGUS IOC engineer and confirmed by **{actor}** in Ask ARGUS. "
        "The checks are ibek's and the IOC pod's render; they cannot confirm addresses, ports, channels or "
        "axis ids, which only the hardware can. Review before merging: ARGUS does not merge.",
    ]).strip()
    pr = _gh("POST", f"/repos/{repo}/pulls", json={"title": payload["title"], "head": branch, "base": base,
                                                   "body": body, "draft": _draft()})
    return {"url": pr.get("html_url"), "number": pr.get("number"), "branch": branch, "repository": repo,
            "key": f"{repo}#{pr.get('number')}"}
