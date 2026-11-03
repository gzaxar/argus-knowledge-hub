"""Corrections proposed back to Git, as patches against the source each value comes from
(docs/catalogue-collections.md §3, §A).

A field marked *propose to Git* (`catalogue_entries.corrections`) is the record's value, kept, with the
collection's value beside it. This turns every open correction into a change of the file the entry is written
in, at the commit ARGUS pinned:

    an Argus-native entry           its key, in collections/<collection>/<file> of argus-catalogue
    a NetBox model's model code     `model:` in its device type, in the NetBox fork
    a NetBox model's device class,  its `classifications` entry in argus-catalogue (added when there is none)
    end of life or spares

A field a source's format has no place for (a NetBox model's name, datasheet or description) is listed with
the reason, never forced in. The result is one unified diff per repository — `git apply` it on a branch at the
pinned commit, and open a pull request — and the list of what each correction became. Only lines that change
are touched: the rest of each file stays as its reviewers wrote it.
"""
from __future__ import annotations

import difflib
import re
from datetime import date
from typing import Any, Optional

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalogue.loader import Collection, load_tree
from app.models.catalogue_entry import CatalogueEntry

NETBOX_CLASSIFIED = ("device_class", "eol_date", "typical_spares")


def _scalar(value: Any) -> str:
    """A value as one line of YAML."""
    text = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True, width=10_000).strip()
    return text[:-4].strip() if text.endswith("\n...") else text.removesuffix("...").strip()


def _yaml_value(field: str, value: Any, vendor_ids: dict[str, str]) -> Any:
    if field == "vendor":
        return vendor_ids.get(str(value), value)
    if field == "eol_date" and value:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return value
    if field == "typical_spares" and isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    return value


def set_in_block(text: str, entry_id: str, key: str, value: Any) -> Optional[str]:
    """The file with `key` of the block-style list item `- id: entry_id` set to `value`, or None if no such
    item. The key is replaced where it is, or added before the item's `sources`, else at its end."""
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines) if re.match(rf"^(\s*)- id: ['\"]?{re.escape(entry_id)}['\"]?\s*$", l)),
                 None)
    if start is None:
        return None
    def depth(line: str) -> int:
        return len(line) - len(line.lstrip())
    indent = depth(lines[start]) + 2
    end = start + 1                      # the item: every line indented at least as far as its keys
    while end < len(lines) and lines[end].strip() and depth(lines[end]) >= indent:
        end += 1
    pad = " " * indent
    new = f"{pad}{key}: {_scalar(value)}"
    for i in range(start + 1, end):
        if re.match(rf"^{pad}{re.escape(key)}:", lines[i]):
            # Replace the key, and any lines that continue its value.
            j = i + 1                    # a value's own lines: deeper, or a list at the key's depth
            while j < end and (depth(lines[j]) > indent or
                               (depth(lines[j]) == indent and lines[j].lstrip().startswith("- "))):
                j += 1
            return "\n".join(lines[:i] + [new] + lines[j:])
    at = next((i for i in range(start + 1, end) if lines[i].startswith(f"{pad}sources:")), end)
    return "\n".join(lines[:at] + [new] + lines[at:])


def set_in_flow(text: str, entry_id: str, key: str, value: Any, list_key: str) -> str:
    """The file with `key` of the flow-style item `{id: entry_id, …}` set, or the item added to `list_key`."""
    lines = text.split("\n")
    for i, l in enumerate(lines):
        m = re.match(r"^(\s*- )(\{.*\})\s*$", l)
        if m:
            item = yaml.safe_load(m.group(2))
            if isinstance(item, dict) and str(item.get("id")) == entry_id:
                item[key] = value
                lines[i] = m.group(1) + _scalar(item)
                return "\n".join(lines)
    at = next((i for i, l in enumerate(lines) if l.startswith(f"{list_key}:")), None)
    if at is None:
        return text.rstrip("\n") + f"\n{list_key}:\n  - {_scalar({'id': entry_id, key: value})}\n"
    # The list ends at the next top-level key; a new item takes the indentation of the items there.
    end = at + 1
    while end < len(lines) and (not lines[end].strip() or lines[end][0] in " -#"):
        end += 1
    while end > at + 1 and not lines[end - 1].strip():
        end -= 1
    dash = next((l[:len(l) - len(l.lstrip())] for l in lines[at + 1:end] if l.lstrip().startswith("- ")), "  ")
    return "\n".join(lines[:end] + [f"{dash}- {_scalar({'id': entry_id, key: value})}"] + lines[end:])


def _find(tree: dict[str, Collection], catalogue_id: str, collection_id: str):
    c = tree.get(collection_id)
    if c is None:
        return None, None
    return c, next((e for e in c.entries() if e.id == catalogue_id), None)


def _classification_home(tree: dict[str, Collection], catalogue_id: str):
    """Where a NetBox model's classification is, or the collection to add it to."""
    for c in tree.values():
        for e in c.classifications:
            if e.id == catalogue_id:
                return c, e.file
    for c in tree.values():
        if c.classifications:
            return c, c.classifications[0].file
    return None, None


def patches(db: Session, workspace_id: str, tree: Optional[dict[str, Collection]] = None,
            netbox_file=None) -> dict:
    """Every open correction as unified diffs, one per repository, and what each became.

    `netbox_file(path) -> str` reads a file of the NetBox source at its pinned commit (default: from the
    source cache)."""
    rows = list(db.scalars(select(CatalogueEntry).where(CatalogueEntry.workspace_id == workspace_id)))
    if tree is None:
        have: dict[str, set[str]] = {}
        for r in rows:
            have.setdefault(r.collection_id, set()).add(r.catalogue_id)
        tree = load_tree(netbox_models=have)
    vendor_ids = {r.record_uid: r.catalogue_id for r in rows if r.kind == "vendor"}
    if netbox_file is None:
        netbox_file = _netbox_reader()
    # repo -> path -> [original, current]
    files: dict[str, dict[str, list[str]]] = {"argus-catalogue": {}, "devicetype-library": {}}
    items = []

    def edit(repo: str, path: str, original: str, change) -> bool:
        current = files[repo].setdefault(path, [original, original])
        changed = change(current[1])
        if changed is None:
            return False
        current[1] = changed
        return True

    for r in sorted(rows, key=lambda r: r.catalogue_id):
        for field, corr in sorted((r.corrections or {}).items()):
            value = _yaml_value(field, corr.get("value"), vendor_ids)
            item = {"catalogue_id": r.catalogue_id, "field": field, "from": (r.stated or {}).get(field),
                    "to": corr.get("value"), "by": corr.get("by"), "reason": corr.get("reason")}
            c, entry = _find(tree, r.catalogue_id, r.collection_id)
            if entry is None:
                items.append({**item, "status": "skipped", "why": f"{r.collection_id} at the pinned revision does "
                                                                  f"not hold {r.catalogue_id}"})
                continue
            if c.origin != "netbox":
                path = f"collections/{c.path.name}/{entry.file}"
                original = (c.path / entry.file).read_text(encoding="utf-8")
                ok = edit("argus-catalogue", path, original, lambda t: set_in_block(t, r.catalogue_id, field, value))
                items.append({**item, "repo": "argus-catalogue", "file": path,
                              "status": "patched" if ok else "skipped",
                              **({} if ok else {"why": "the entry was not found in its file"})})
            elif field == "model_code":
                src = next((s.get("ref") for s in entry.data.get("sources") or []
                            if s.get("kind") == "netbox-devicetype-library"), None)
                if not src:
                    items.append({**item, "status": "skipped", "why": "its NetBox file is not known"})
                    continue
                original = netbox_file(src)
                ok = edit("devicetype-library", src, original,
                          lambda t: re.sub(r"(?m)^model: .*$", f"model: {_scalar(value)}", t, count=1))
                items.append({**item, "repo": "devicetype-library", "file": src, "status": "patched" if ok else "skipped"})
            elif field in NETBOX_CLASSIFIED:
                home, file = _classification_home(tree, r.catalogue_id)
                if home is None:
                    items.append({**item, "status": "skipped", "why": "no classifications collection to hold it"})
                    continue
                path = f"collections/{home.path.name}/{file}"
                original = (home.path / file).read_text(encoding="utf-8")
                edit("argus-catalogue", path, original,   # a block-style item, or a one-line {id: …} one
                     lambda t: set_in_block(t, r.catalogue_id, field, value)
                     or set_in_flow(t, r.catalogue_id, field, value, "classifications"))
                items.append({**item, "repo": "argus-catalogue", "file": path, "status": "patched"})
            else:
                items.append({**item, "status": "skipped",
                              "why": f"a NetBox model's {field} has no place in the NetBox device type format: "
                                     f"propose it to the fork by hand, or keep it local"})
    out = []
    for repo, by_path in files.items():
        diff = "".join("".join(difflib.unified_diff(orig.splitlines(keepends=True), new.splitlines(keepends=True),
                                                    fromfile=f"a/{path}", tofile=f"b/{path}"))
                       for path, (orig, new) in sorted(by_path.items()) if orig != new)
        if diff:
            out.append({"repo": repo, "diff": diff})
    return {"patches": out, "items": items}


def _netbox_reader():
    from app.catalogue.sources import _show, cache_dir, fetch, lock_path, read_lock

    def read(path: str) -> str:
        source = next(s for s in read_lock(lock_path()) if s["kind"] == "netbox-devicetype-library")
        return _show(fetch(source, cache_dir()), source["commit"], path).decode()
    return read
