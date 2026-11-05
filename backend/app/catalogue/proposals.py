"""A model made in ARGUS, proposed for the Git catalogue as a pull request (docs/catalogue-collections.md §4).

A catalogue maintainer makes a Product Model by hand in the catalogue workspace when a unit needs one today. The
action *Propose for the catalogue* turns it into an entry of the catalogue repository:

    1. draft: the entry ARGUS reads from the record — its vendor (the catalogue's, found by the record's link or
       by name, or a new one proposed with it), model code, name, part number, device class, datasheet — and the
       collections it may go in;
    2. the person completes it — the collection (or a new one), the source the values were checked against;
    3. ARGUS writes the files against the repository's default branch (the entry in its place, the collection's
       version raised once per release), checks them with the validator over the catalogue it reads, and opens
       a pull request with them, naming who proposed it. ARGUS never merges;
    4. after review the repository releases it; a maintainer pins the release (app/catalogue/pins.py) and
       installs it. The install links the record to its entry — same record, now with a catalogue id — with
       the reviewed values, and the proposal is done.

The pull request is opened with ARGUS's GitHub credential (ARGUS_GITHUB_TOKEN, contents and pull requests on the
catalogue repository), as the IOC engineer's are (app/ioc_engineer/pull_requests.py).
"""
from __future__ import annotations

import base64
import datetime as dt
import os
import re
import secrets
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset

SOURCE_KINDS = ("datasheet", "manufacturer-page", "other")
ENTRY_FIELDS = ("model_code", "name", "part_number", "description", "device_class", "instance_type",
                "datasheet_url", "eol_date")
OPEN = ("open", "merged")


class ProposalProblem(ValueError):
    def __init__(self, message: str, details: Optional[list] = None):
        super().__init__(message)
        self.details = details or []


# --------------------------------------------------------------------------- the repository

def repository() -> Optional[str]:
    """owner/name of the catalogue repository: ARGUS_CATALOGUE_REPO, else the GitHub repository the lock pins."""
    configured = os.environ.get("ARGUS_CATALOGUE_REPO")
    if configured:
        return configured.strip().lower()
    try:
        from app.catalogue.sources import effective
        argus = next((s for s in effective() if s["kind"] == "argus-collections"), None)
    except Exception:
        return None
    m = re.match(r"^(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?/?$", str((argus or {}).get("repo")))
    return m.group(1).lower() if m else None


def enabled() -> bool:
    return bool(os.environ.get("ARGUS_GITHUB_TOKEN")) and bool(repository())


class GitHub:
    """What a proposal needs of GitHub (replaced in tests)."""

    def __init__(self, repo: str):
        self.repo = repo

    def _call(self, method: str, path: str, **kw) -> Any:
        from app.ioc_engineer.pull_requests import Refused, _gh
        try:
            return _gh(method, path, **kw)
        except Refused as e:
            raise ProposalProblem(str(e))

    def default_branch(self) -> str:
        return self._call("GET", f"/repos/{self.repo}").get("default_branch") or "main"

    def read(self, path: str, ref: str) -> Optional[str]:
        try:
            got = self._call("GET", f"/repos/{self.repo}/contents/{path}", params={"ref": ref})
        except ProposalProblem as e:
            if " 404 " in str(e):
                return None
            raise
        return base64.b64decode(got.get("content") or "").decode("utf-8")

    def latest_release(self) -> Optional[str]:
        from app.catalogue.sources import tag_version
        tags = [t.get("name") for t in self._call("GET", f"/repos/{self.repo}/tags", params={"per_page": 100}) or []]
        tags = [t for t in tags if tag_version(t) is not None]
        return max(tags, key=tag_version) if tags else None

    def open_pull_request(self, base: str, branch: str, title: str, body: str, files: dict[str, str],
                          message: str) -> dict:
        head = self._call("GET", f"/repos/{self.repo}/git/ref/heads/{base}")["object"]["sha"]
        tree = self._call("GET", f"/repos/{self.repo}/git/commits/{head}")["tree"]["sha"]
        new_tree = self._call("POST", f"/repos/{self.repo}/git/trees", json={
            "base_tree": tree,
            "tree": [{"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in files.items()]})
        commit = self._call("POST", f"/repos/{self.repo}/git/commits",
                            json={"message": message, "tree": new_tree["sha"], "parents": [head]})
        self._call("POST", f"/repos/{self.repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
        pr = self._call("POST", f"/repos/{self.repo}/pulls",
                        json={"title": title, "head": branch, "base": base, "body": body})
        return {"number": pr.get("number"), "url": pr.get("html_url")}

    def pull_state(self, number: int) -> Optional[str]:
        pr = self._call("GET", f"/repos/{self.repo}/pulls/{number}")
        if pr.get("merged_at"):
            return "merged"
        return "closed" if pr.get("state") == "closed" else "open"


def github() -> GitHub:
    repo = repository()
    if not repo:
        raise ProposalProblem("no catalogue repository on GitHub: set ARGUS_CATALOGUE_REPO")
    if not os.environ.get("ARGUS_GITHUB_TOKEN"):
        raise ProposalProblem("no ARGUS_GITHUB_TOKEN is installed: an administrator must add one, with contents and "
                              f"pull requests on {repo}, before ARGUS opens pull requests")
    return GitHub(repo)


# --------------------------------------------------------------------------- reading the record

def slug(text: Any, model: bool = False) -> str:
    allowed = r"[^a-z0-9.+]+" if model else r"[^a-z0-9]+"
    return re.sub(r"-+", "-", re.sub(allowed, "-", str(text or "").lower())).strip("-.+")


def _tree() -> dict:
    from app.catalogue.loader import load_tree
    from app.catalogue.sources import SourceProblem
    try:
        return load_tree(netbox_models={})
    except SourceProblem as e:
        raise ProposalProblem(f"the catalogue's sources cannot be read as pinned: {e}")


def _record(db: Session, ws: str, uid: str) -> Asset:
    from app.catalogue import install as installer
    rec = db.get(Asset, uid)
    model_schema, _ = installer._types(db, ws)
    if rec is None or rec.deleted_at is not None or rec.workspace_id != ws or rec.schema_uid != model_schema.uid:
        raise ProposalProblem(f"{uid} is not a Product Model of the catalogue: a model is proposed from the "
                              f"catalogue, where its record is linked when the release is installed")
    return rec


def _vendor(db: Session, ws: str, rec: Asset, tree: dict) -> dict:
    """The catalogue vendor of a record: linked already, found by name or alias, or new (proposed with it)."""
    from app.models.catalogue_entry import CatalogueEntry
    from app.services.catalogue_mapping import norm
    a = rec.attributes or {}
    vrec = db.get(Asset, a["vendor_ref"]) if a.get("vendor_ref") else None
    name = (vrec.name if vrec is not None else None) or a.get("vendor")
    if not name:
        raise ProposalProblem(f"{rec.name} has no vendor: set its vendor first")
    if vrec is not None:
        row = db.execute(select(CatalogueEntry).where(CatalogueEntry.record_uid == vrec.uid)).scalar_one_or_none()
        if row is not None:
            return {"id": row.catalogue_id, "name": vrec.name, "new": False, "record_uid": vrec.uid}
    key = norm(name)
    for c in tree.values():
        for v in c.vendors:
            if key in {norm(str(n)) for n in [v.data.get("name"), *(v.data.get("aliases") or [])] if n}:
                return {"id": v.id, "name": v.data.get("name"), "new": False,
                        "record_uid": vrec.uid if vrec is not None else None}
    entry: dict = {"id": slug(name), "name": str(name)}
    website = (vrec.attributes or {}).get("website") if vrec is not None else None
    if website:
        entry["website"] = website
    return {"id": entry["id"], "name": entry["name"], "new": True, "entry": entry,
            "record_uid": vrec.uid if vrec is not None else None}


def _collections(tree: dict) -> list[dict]:
    """Where a new model may go: the Argus-native collections that hold models."""
    return [{"id": c.id, "name": c.name, "version": c.version, "domains": list(c.domains)}
            for c in sorted(tree.values(), key=lambda c: c.id)
            if not c.partial and c.origin != "netbox" and c.id != "vendors" and c.models]


def _existing(db: Session, ws: str, rec: Asset) -> None:
    from app.models.catalogue_entry import CatalogueEntry, CatalogueProposal
    row = db.execute(select(CatalogueEntry).where(CatalogueEntry.record_uid == rec.uid)).scalar_one_or_none()
    if row is not None:
        raise ProposalProblem(f"{rec.name} is in the catalogue already, as {row.catalogue_id}")
    pending = db.execute(select(CatalogueProposal).where(CatalogueProposal.record_uid == rec.uid,
                                                         CatalogueProposal.state.in_(OPEN))).scalars().first()
    if pending is not None:
        raise ProposalProblem(f"{rec.name} is proposed already: {pending.url}")


def draft(db: Session, ws: str, record_uid: str) -> dict:
    """What ARGUS would propose for this record, and the choices left to the person."""
    from app.catalogue.validate import DEVICE_CLASSES
    rec = _record(db, ws, record_uid)
    _existing(db, ws, rec)
    tree = _tree()
    vendor = _vendor(db, ws, rec, tree)
    a = rec.attributes or {}
    code = a.get("model_code") or rec.name
    entry: dict = {"id": f"{vendor['id']}/{slug(code, model=True)}", "vendor": vendor["id"], "model_code": str(code),
                   "name": rec.name}
    for k in ("part_number", "device_class", "datasheet_url", "eol_date"):
        if a.get(k):
            entry[k] = str(a[k])
    return {"record_uid": rec.uid, "entry": entry, "vendor": vendor, "collections": _collections(tree),
            "device_classes": sorted(DEVICE_CLASSES), "source_kinds": list(SOURCE_KINDS),
            "repository": repository(), "enabled": enabled()}


# --------------------------------------------------------------------------- writing the files

class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def _dump_item(item: dict) -> str:
    return yaml.dump([item], Dumper=_Dumper, sort_keys=False, allow_unicode=True, default_flow_style=False, width=120)


def insert_sorted(text: str, key: str, item: dict) -> str:
    """`item` as a new `- id:` item of the file's list (`models:` or `vendors:`), at its place by id; the rest of
    the file kept as written."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    if not any(l.startswith(f"{key}:") for l in lines):
        return "".join(lines) + f"{key}:\n" + _dump_item(item)
    block = _dump_item(item)
    for i, line in enumerate(lines):
        m = re.match(r"^- id: ['\"]?([^'\"\n]+)", line)
        if m and m.group(1).strip() > item["id"]:
            return "".join(lines[:i]) + block + "".join(lines[i:])
    return "".join(lines) + block


def _version_of(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    try:
        return str((yaml.safe_load(text) or {}).get("version") or "") or None
    except yaml.YAMLError:
        return None


def bump(manifest: str, released: Optional[str]) -> str:
    """The collection's version raised once since its last release (patch); already raised: as it is."""
    from packaging.version import Version
    current = _version_of(manifest)
    if not current or (released and Version(current) > Version(released)) or not released:
        return manifest
    v = Version(current)
    return re.sub(r"(?m)^version:.*$", f"version: {v.major}.{v.minor}.{v.micro + 1}", manifest, count=1)


def _new_collection(c: dict, vendors_version: Optional[str]) -> str:
    from packaging.version import Version
    v = Version(vendors_version or "0.2.0")
    upper = f"{v.major + 1}" if v.major else "1"
    manifest = {"id": c["id"], "version": "0.1.0", "name": c.get("name") or c["id"],
                "description": c.get("description") or "Models proposed from ARGUS; specifications are added as "
                                                          "each is verified.",
                "domain": c.get("domain") or "catalogue", "owner": "INFN ARGUS", "license": "CC0-1.0",
                "requires": {"packages": {"core-objects": ">=2.1,<3"},
                             "collections": {"vendors": f">={v.major}.{v.minor},<{upper}"}},
                "contents": ["models.yaml"]}
    return yaml.dump(manifest, Dumper=_Dumper, sort_keys=False, allow_unicode=True)


def _models_file(manifest: str) -> str:
    contents = [str(x) for x in (yaml.safe_load(manifest) or {}).get("contents") or []]
    named = [x for x in contents if x.endswith("models.yaml")]
    return (named or contents or ["models.yaml"])[0]


def _check(files: dict[str, str], touched: set[str]) -> list[str]:
    """The validator over the catalogue read now, with these files in it (the pull request's CI runs it again,
    against the repository's last release)."""
    from app.catalogue.loader import load_tree
    from app.catalogue.loader import catalogue_dir
    from app.catalogue.sources import lock_path, materialize
    from app.catalogue.validate import validate_tree
    base = materialize() if lock_path().is_file() else catalogue_dir()
    work = Path(tempfile.mkdtemp(prefix="argus-proposal-"))
    try:
        for child in base.iterdir():
            if not child.is_dir():
                continue
            if child.name in touched:
                shutil.copytree(child, work / child.name)
            else:
                (work / child.name).symlink_to(child, target_is_directory=True)
        for path, content in files.items():
            if path.startswith("collections/"):
                target = work / path[len("collections/"):]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        tree = load_tree(work, netbox_models={})
        return [str(p) for cid, ps in validate_tree(tree).items() if cid in touched for p in ps]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def build(db: Session, ws: str, body: dict, gh: Optional[GitHub] = None) -> dict:
    """The pull request's files for this proposal, checked: refuses one the validator would."""
    from app.catalogue.validate import MODEL_ID, SLUG, code_key
    d = draft(db, ws, body["record_uid"])
    entry = dict(d["entry"])
    for k in ENTRY_FIELDS:
        if k in (body.get("entry") or {}):
            v = (body["entry"] or {}).get(k)
            if v in (None, ""):
                entry.pop(k, None)
            else:
                entry[k] = str(v).strip()
    vendor = dict(d["vendor"])
    if vendor["new"]:
        given = body.get("vendor") or {}
        ventry = dict(vendor["entry"])
        for k in ("id", "name", "website"):
            if given.get(k):
                ventry[k] = str(given[k]).strip()
        aliases = [str(x).strip() for x in given.get("aliases") or [] if str(x).strip()]
        if aliases:
            ventry["aliases"] = aliases
        if not SLUG.match(ventry["id"]):
            raise ProposalProblem(f"{ventry['id']!r} is not a vendor id: lower-case letters, digits and dashes")
        ventry["sources"] = [{"kind": "manufacturer-page" if ventry.get("website") else "other",
                              "ref": ventry.get("website") or f"ARGUS record {vendor.get('record_uid') or ''}".strip(),
                              "checked": dt.date.today()}]
        vendor.update(id=ventry["id"], name=ventry["name"], entry=ventry)
    entry["vendor"] = vendor["id"]
    entry["id"] = str((body.get("entry") or {}).get("id") or f"{vendor['id']}/{slug(entry['model_code'], model=True)}")
    if not MODEL_ID.match(entry["id"]) or not entry["id"].startswith(vendor["id"] + "/"):
        raise ProposalProblem(f"{entry['id']!r} is not a model id: {vendor['id']}/<model>, lower-case")
    source = body.get("source") or {}
    if source.get("kind") not in SOURCE_KINDS or not str(source.get("ref") or "").strip():
        raise ProposalProblem("say where the values can be checked: the datasheet or manufacturer page (a link or "
                              "a document reference)")
    s: dict = {"kind": source["kind"], "ref": str(source["ref"]).strip(), "checked": dt.date.today()}
    if str(source.get("note") or "").strip():
        s["note"] = str(source["note"]).strip()
    entry["sources"] = [s]
    order = ["id", "vendor", "model_code", "part_number", "name", "description", "device_class", "instance_type",
             "datasheet_url", "eol_date", "sources"]
    entry = {k: entry[k] for k in order if k in entry}

    tree = _tree()
    for c in tree.values():
        for m in c.models:
            if m.id == entry["id"]:
                raise ProposalProblem(f"{entry['id']} is in the catalogue already ({c.id}): link the record to it")
            if m.data.get("vendor") == entry["vendor"] and code_key(m.data.get("model_code")) == code_key(entry["model_code"]):
                raise ProposalProblem(f"{m.id} in {c.id} is the same model ({m.data.get('model_code')}): link the "
                                      f"record to it")

    col = body.get("collection") or {}
    cid = str(col.get("id") or "").strip()
    if not SLUG.match(cid):
        raise ProposalProblem("choose a collection, or name a new one (lower-case letters, digits and dashes)")
    known = {c["id"] for c in d["collections"]}
    if cid in tree and cid not in known:
        raise ProposalProblem(f"{cid} does not take models proposed from ARGUS")

    gh = gh or github()
    base = gh.default_branch()
    released = gh.latest_release()
    files: dict[str, str] = {}

    def released_version(collection: str) -> Optional[str]:
        return _version_of(gh.read(f"collections/{collection}/collection.yaml", released)) if released else None

    vendors_manifest = gh.read("collections/vendors/collection.yaml", base)
    if vendor["new"]:
        text = gh.read("collections/vendors/vendors.yaml", base) or "vendors:\n"
        files["collections/vendors/vendors.yaml"] = insert_sorted(text, "vendors", vendor["entry"])
        bumped = bump(vendors_manifest, released_version("vendors")) if vendors_manifest else None
        if bumped and bumped != vendors_manifest:
            files["collections/vendors/collection.yaml"] = bumped
    manifest = gh.read(f"collections/{cid}/collection.yaml", base)
    if manifest is None:
        files[f"collections/{cid}/collection.yaml"] = _new_collection(
            {"id": cid, "name": col.get("name"), "description": col.get("description"), "domain": col.get("domain")},
            _version_of(files.get("collections/vendors/collection.yaml") or vendors_manifest))
        files[f"collections/{cid}/models.yaml"] = insert_sorted("models:\n", "models", entry)
    else:
        mfile = f"collections/{cid}/{_models_file(manifest)}"
        files[mfile] = insert_sorted(gh.read(mfile, base) or "models:\n", "models", entry)
        bumped = bump(manifest, released_version(cid))
        if bumped != manifest:
            files[f"collections/{cid}/collection.yaml"] = bumped
    problems = _check(files, {cid, "vendors"})
    if problems:
        raise ProposalProblem("the validator refuses the entry as written", problems)
    title = f"Add {vendor['name']} {entry['model_code']} ({entry['id']})"
    return {"title": title, "base": base, "files": files, "entry": entry, "vendor": vendor, "collection": cid,
            "repository": gh.repo}


def _body(built: dict, actor: str) -> str:
    e, v = built["entry"], built["vendor"]
    lines = [f"Proposed from ARGUS by **{actor}**: the Product Model {e['name']} as `{e['id']}` in "
             f"`{built['collection']}`" + (f", with the new vendor `{v['id']}` ({v['name']})." if v["new"] else "."),
             "", "## Entry", "", "```yaml", _dump_item(e).rstrip(), "```"]
    if v["new"]:
        lines += ["", "## New vendor", "", "```yaml", _dump_item(v["entry"]).rstrip(), "```"]
    lines += ["", "## Checks run by ARGUS",
              "- the ARGUS validator over the catalogue ARGUS reads, with these files",
              "- no model in the catalogue has this id, or this vendor and model code",
              "", "## For the reviewer",
              "- check the values against the source cited; remove any that cannot be checked",
              "- a new vendor: is it a company the catalogue has under another name? then use that id instead",
              "", "When a release carrying it is installed, ARGUS links the record it came from. ARGUS does not merge."]
    return "\n".join(lines)


def propose(db: Session, ws: str, body: dict, actor: str, gh: Optional[GitHub] = None) -> dict:
    """Open the pull request and keep the proposal."""
    from app.models.catalogue_entry import CatalogueProposal
    gh = gh or github()
    built = build(db, ws, body, gh)
    branch = f"argus/model-{slug(built['entry']['id'])[:40]}-{secrets.token_hex(3)}"
    message = f"{built['title']}\n\nProposed from ARGUS by {actor}."
    pr = gh.open_pull_request(built["base"], branch, built["title"], _body(built, actor), built["files"], message)
    row = CatalogueProposal(workspace_id=ws, record_uid=body["record_uid"], catalogue_id=built["entry"]["id"],
                            vendor_id=built["vendor"]["id"] if built["vendor"]["new"] else None,
                            vendor_record_uid=built["vendor"].get("record_uid") if built["vendor"]["new"] else None,
                            collection_id=built["collection"], repository=gh.repo, number=pr.get("number"),
                            url=pr.get("url"), branch=branch, state="open", files=built["files"], proposed_by=actor)
    db.add(row)
    db.flush()
    return view(db, row)


# --------------------------------------------------------------------------- following them

def view(db: Session, p) -> dict:
    rec = db.get(Asset, p.record_uid)
    return {"id": p.id, "record_uid": p.record_uid, "record_name": rec.name if rec else None,
            "catalogue_id": p.catalogue_id, "vendor_id": p.vendor_id, "collection_id": p.collection_id,
            "repository": p.repository, "number": p.number, "url": p.url, "state": p.state,
            "proposed_by": p.proposed_by, "proposed_at": p.proposed_at, "updated_at": p.updated_at,
            "files": sorted((p.files or {}).keys())}


def _linked(db: Session, uid: str) -> bool:
    from app.models.catalogue_entry import CatalogueEntry
    return db.execute(select(CatalogueEntry.id).where(CatalogueEntry.record_uid == uid)).first() is not None


def refresh(db: Session, ws: str, gh: Optional[GitHub] = None) -> None:
    """Each pending proposal's state: installed once its record has a catalogue id, else the pull request's."""
    from app.models.catalogue_entry import CatalogueProposal
    pending = db.execute(select(CatalogueProposal).where(CatalogueProposal.workspace_id == ws,
                                                         CatalogueProposal.state.in_(OPEN))).scalars().all()
    for p in pending:
        if _linked(db, p.record_uid):
            p.state = "installed"
            continue
        if p.state == "open" and p.number:
            try:
                p.state = (gh or GitHub(p.repository)).pull_state(p.number) or p.state
            except ProposalProblem:
                pass                                       # GitHub unreachable or no token: as it was
    db.flush()


def listing(db: Session, ws: str) -> list[dict]:
    from app.models.catalogue_entry import CatalogueProposal
    rows = db.execute(select(CatalogueProposal).where(CatalogueProposal.workspace_id == ws)
                      .order_by(CatalogueProposal.proposed_at.desc())).scalars().all()
    return [view(db, p) for p in rows]


def with_proposals(db: Session, ws: str, decisions: dict) -> dict:
    """Installing: an entry someone proposed from a record links that record, taking the reviewed values —
    unless the installer decided otherwise."""
    from app.models.catalogue_entry import CatalogueProposal
    out = dict(decisions or {})
    for p in db.execute(select(CatalogueProposal).where(CatalogueProposal.workspace_id == ws,
                                                        CatalogueProposal.state.in_(OPEN))
                        .order_by(CatalogueProposal.id)).scalars():
        if _linked(db, p.record_uid):
            continue
        out.setdefault(p.catalogue_id, {"action": "link", "record_uid": p.record_uid, "fields_default": "managed"})
        if p.vendor_id and p.vendor_record_uid and not _linked(db, p.vendor_record_uid):
            out.setdefault(p.vendor_id, {"action": "link", "record_uid": p.vendor_record_uid,
                                         "fields_default": "managed"})
    return out


def mark_installed(db: Session, ws: str) -> None:
    from app.models.catalogue_entry import CatalogueProposal
    for p in db.execute(select(CatalogueProposal).where(CatalogueProposal.workspace_id == ws,
                                                        CatalogueProposal.state.in_(OPEN))).scalars():
        if _linked(db, p.record_uid):
            p.state = "installed"
    db.flush()
