"""Moving a catalogue source to a newer release, from Administration › Catalogue (docs/catalogue-collections.md §A).

The lock file shipped with ARGUS (`backend/catalogue/sources.lock.yaml`) pins each source at a release tag and its
commit. A catalogue maintainer may pin a newer release of the same repository here, without an ARGUS release:

    1. the release is one of the repository's tags, newer than the lock's (older ones are what unpinning is for);
    2. its commit is the one the tag points at now, and is kept: a tag moved later is refused when read;
    3. the catalogue it makes is checked before it is pinned — the validator over every source together, and
       against the catalogue read now: nothing disappeared without being retired or moved, and a collection whose
       content changed has a new version. A release that fails is not pinned.

Pinning installs nothing. The collections page then shows which collections have an upgrade, previewed and
installed as before. An ARGUS release whose lock is newer than the stored pin wins: the stored one is ignored.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.catalogue.sources import (SourceProblem, effective, lock_path, materialize, read_lock, releases,
                                   tag_version)


class PinProblem(ValueError):
    def __init__(self, message: str, details: Optional[list] = None):
        super().__init__(message)
        self.details = details or []


def _shipped(source_id: str) -> dict:
    path = lock_path()
    if not path.is_file():
        raise PinProblem("this installation has no lock file: its collections are the folders it ships")
    found = next((s for s in read_lock(path) if s["id"] == source_id), None)
    if found is None:
        raise PinProblem(f"no catalogue source is called {source_id!r}")
    if tag_version(found.get("ref")) is None:
        raise PinProblem(f"{source_id} is pinned to a branch ({found.get('ref')}), not a release: it moves only with "
                         f"an ARGUS release")
    return found


def available(source_id: str) -> dict:
    """A source's releases: the one read now, the lock's, and the newer ones that may be pinned."""
    shipped = _shipped(source_id)
    current = next(s for s in effective() if s["id"] == source_id)
    floor = tag_version(shipped["ref"])
    now = tag_version(current.get("ref")) or floor
    out = []
    for r in releases(shipped):
        v = tag_version(r["tag"])
        if v > floor:
            out.append({**r, "current": v == now, "newer": v > now})
    return {"source": source_id, "repo": shipped["repo"], "ref": current.get("ref"), "commit": current["commit"],
            "shipped_ref": shipped["ref"], "shipped_commit": shipped["commit"], "releases": out}


def check(source_id: str, ref: str) -> tuple[str, list[dict]]:
    """The commit of the release, and the catalogue it would make, checked: refuses a release that fails."""
    from app.catalogue.loader import load_tree
    from app.catalogue.validate import tree_problems
    shipped = _shipped(source_id)
    wanted = tag_version(ref)
    if wanted is None:
        raise PinProblem(f"{ref!r} is not a release tag (vX.Y.Z)")
    if wanted <= tag_version(shipped["ref"]):
        raise PinProblem(f"{ref} is not newer than {shipped['ref']}, the release this ARGUS ships: to go back to it, "
                         f"remove the pin")
    commit = next((r["commit"] for r in releases(shipped) if r["tag"] == ref), None)
    if commit is None:
        raise PinProblem(f"{shipped['repo']} has no release {ref}")
    sources = [{**s, "ref": ref, "commit": commit} if s["id"] == source_id else s for s in effective()]
    try:
        root = materialize(sources=sources)
    except SourceProblem as e:
        raise PinProblem(f"{ref} cannot be read: {e}")
    candidate = load_tree(root, netbox_models={})
    problems = tree_problems(candidate, previous=load_tree(netbox_models={}))
    flat = [str(p) for ps in problems.values() for p in ps]
    if flat:
        raise PinProblem(f"{ref} is not a valid catalogue for this ARGUS: {len(flat)} problem(s)", flat[:50])
    return commit, [{"id": c.id, "version": c.version} for c in candidate.values()]


def pin(db: Session, source_id: str, ref: str, actor: str) -> dict:
    """Pin a newer release, checked first. Installs nothing."""
    from app.models.catalogue_entry import CataloguePin
    commit, collections = check(source_id, ref)
    current = next(s for s in effective() if s["id"] == source_id)
    row = db.get(CataloguePin, source_id) or CataloguePin(source_id=source_id)
    row.previous_ref, row.previous_commit = current.get("ref"), current["commit"]
    row.ref, row.commit, row.pinned_by = ref, commit, actor
    from app.ledger.engine import now
    row.pinned_at = now()
    db.add(row)
    db.flush()
    return {"source": source_id, "ref": ref, "commit": commit, "previous_ref": row.previous_ref,
            "collections": collections}


def unpin(db: Session, source_id: str) -> dict:
    """Back to the release the lock file ships."""
    from app.models.catalogue_entry import CataloguePin
    shipped = _shipped(source_id)
    row = db.get(CataloguePin, source_id)
    if row is not None:
        db.delete(row)
        db.flush()
    return {"source": source_id, "ref": shipped["ref"], "commit": shipped["commit"]}
