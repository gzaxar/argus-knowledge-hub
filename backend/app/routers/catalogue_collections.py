"""Catalogue collections (app/catalogue, docs/catalogue-collections.md): the versioned Vendor and Product Model
records this installation ships, what the catalogue workspace has installed, and installing them — previewed
first, applied all or nothing.

Reading needs read on objects in the catalogue workspace. Previewing and installing are for its owners and
administrators, as installing a package is.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import Identity, OidcIdentity, PatIdentity, get_identity, require_permission
from app.catalogue import install as installer
from app.catalogue.loader import load_tree
from app.catalogue.validate import tree_problems
from app.db import get_db

router = APIRouter(prefix="/v1/catalogue/collections", tags=["catalogue"])


class FieldDecisionIn(BaseModel):
    field: str
    decision: str                     # managed | local | propose
    reason: Optional[str] = None


class CollectionsIn(BaseModel):
    collections: list[str]
    # Per catalogue id: {"action": "link" | "create", "record_uid": optional, "fields": {field: managed | local |
    # propose}}. A link names the record an entry is, when the match is not found by vendor and model code.
    decisions: dict[str, dict] = {}
    # A migration manifest (`python -m app.catalogue export`), as its YAML text: which record each catalogue id
    # is, the duplicates to merge, the field decisions and the references to check. Decisions given here win.
    manifest: Optional[str] = None


def _workspace(db: Session) -> str:
    ws = installer.catalogue_workspace(db)
    if ws is None:
        raise HTTPException(status_code=404, detail={"error": "this installation has no catalogue workspace"})
    return ws


def _may_read(db: Session, identity: Identity, ws: str) -> None:
    """Everyone reads the installation's catalogue: its models are shared with every workspace."""
    return None


def _may_install(db: Session, identity: Identity, ws: str) -> None:
    """Installing, deciding and correcting: the catalogue's maintainers (app/catalogue/system.py)."""
    from app.catalogue.system import may_maintain
    if isinstance(identity, PatIdentity):
        if identity.workspace_id != ws or not identity.may("admin"):
            raise HTTPException(status_code=403, detail="Only the catalogue's maintainers may do this")
        return
    if identity.token is not None and (not identity.token.may("admin") or
                                       identity.token.workspace_id not in (None, ws)):
        raise HTTPException(status_code=403, detail="This token may not maintain the catalogue")
    if not may_maintain(db, identity.user):
        raise HTTPException(status_code=403, detail="Only the catalogue's maintainers may do this")


def _actor(identity: Identity) -> str:
    return identity.user.id if isinstance(identity, OidcIdentity) else "api-token"


def _problem(db: Session, e: installer.CatalogueProblem):
    db.rollback()
    raise HTTPException(status_code=422, detail={"error": str(e), "details": e.details})


def _manifest(body: CollectionsIn, ws: str) -> tuple[dict, dict, dict]:
    """The request's decisions, with a manifest's under them; and the manifest's merges and references."""
    if not body.manifest:
        return body.decisions, {}, {}
    import yaml
    from app.catalogue.export import manifest_decisions
    try:
        data = yaml.safe_load(body.manifest)
        decisions, merges, expected = manifest_decisions(data)
    except (yaml.YAMLError, ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=422, detail={"error": f"the migration manifest cannot be read: {e}"})
    if data.get("workspace") != ws:
        raise HTTPException(status_code=422, detail={"error": f"the manifest is for {data.get('workspace')!r}, "
                                                              f"and the catalogue workspace is {ws!r}"})
    for cid, d in body.decisions.items():
        decisions[cid] = {**decisions.get(cid, {}), **d,
                          "fields": {**(decisions.get(cid, {}).get("fields") or {}), **(d.get("fields") or {})}}
    return decisions, merges, expected


def _entry_view(r) -> dict:
    return {"catalogue_id": r.catalogue_id, "record_uid": r.record_uid, "kind": r.kind,
            "collection_id": r.collection_id, "collection_version": r.collection_version, "status": r.status,
            "retired": r.retired, "managed_fields": r.managed_fields, "conflicts": r.conflicts,
            "corrections": r.corrections, "adopted_at": r.adopted_at, "adopted_by": r.adopted_by}


def _counts(c, lib) -> dict:
    """A collection's size; a NetBox library's from the index (its models are read only when chosen)."""
    if not c.partial:
        return {"summary": c.summary(), "vendors": len(c.vendors), "models": len(c.models)}
    n = sum(1 for i in lib.items if i.collection == c.id)
    return {"summary": f"{n} models, each installed when it is chosen", "vendors": len(c.vendors), "models": n}


@router.get("")
def list_collections(identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """The collections this installation ships, whether each is valid, and the release the catalogue workspace
    has installed (with the history)."""
    from app.catalogue.sources import SourceProblem, describe
    ws = _workspace(db)
    _may_read(db, identity, ws)
    try:
        pins = describe()
        tree = load_tree(netbox_models={})                 # a NetBox library: its manifest, counted by the index
        from app.catalogue.library import index
        lib = index() if any(c.partial for c in tree.values()) else None
    except SourceProblem as e:
        raise HTTPException(status_code=502, detail={"error": f"the catalogue's sources cannot be read as pinned: {e}"})
    problems = tree_problems(tree)
    have = installer.installed(db, ws)
    rows = []
    for c in tree.values():
        got = have.get(c.id)
        rows.append({"id": c.id, "name": c.name, "description": c.description, "version": c.version,
                     "domain": c.domain, "domains": c.domains, "owner": c.owner, "license": c.license, "checksum": c.checksum,
                     **_counts(c, lib),
                     "requires": {"packages": c.requires_packages, "collections": c.requires_collections},
                     "problems": [str(p) for p in problems.get(c.id, [])],
                     "installed_version": got.version if got else None,
                     "installed_at": got.installed_at if got else None,
                     "upgrade_available": bool(got and got.version != c.version)})
    history = [{"collection_id": h.collection_id, "from_version": h.from_version, "version": h.version,
                "checksum": h.checksum, "result": h.result, "installed_by": h.installed_by,
                "installed_at": h.installed_at} for h in installer.history(db, ws)]
    return {"workspace_id": ws, "sources": pins, "collections": rows, "history": history}


@router.get("/entries")
def list_entries(collection: Optional[str] = None, status: Optional[str] = None, needs_review: bool = False,
                 identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """Which record each catalogue id is, with its managed fields, and the conflicts and corrections waiting for
    review (`needs_review=true`)."""
    ws = _workspace(db)
    _may_read(db, identity, ws)
    out = []
    for r in sorted(installer.entries(db, ws).values(), key=lambda r: r.catalogue_id):
        if collection and r.collection_id != collection:
            continue
        if status and r.status != status:
            continue
        if needs_review and not (r.conflicts or r.corrections):
            continue
        out.append(_entry_view(r))
    return out


@router.post("/preview")
def preview(body: CollectionsIn, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """What installing these collections (and those they require) would do, entry by entry: add, change, link,
    conflict, transfer, retire, unchanged. Nothing is kept."""
    ws = _workspace(db)
    _may_install(db, identity, ws)
    decisions, merges, expected = _manifest(body, ws)
    try:
        out = installer.preview(db, ws, body.collections, actor=_actor(identity), decisions=decisions, merges=merges,
                                expected=expected)
    except installer.CatalogueProblem as e:
        _problem(db, e)
    db.rollback()
    return out


@router.post("/install")
def install(body: CollectionsIn, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """Install or upgrade these collections, all or nothing. Every link needs its decision first; installing the
    version already installed changes nothing."""
    ws = _workspace(db)
    _may_install(db, identity, ws)
    decisions, merges, expected = _manifest(body, ws)
    try:
        out = installer.install(db, ws, body.collections, actor=_actor(identity), decisions=decisions, merges=merges,
                                expected=expected)
    except installer.CatalogueProblem as e:
        _problem(db, e)
    db.commit()
    return out


def _readable(db: Session, identity: Identity) -> set[str]:
    from app.catalogue.views import readable_workspaces
    if isinstance(identity, PatIdentity):
        return {identity.workspace_id}
    return readable_workspaces(db, identity.user)


@router.get("/models")
def browse_models(q: Optional[str] = None, device_class: Optional[str] = None, vendor: Optional[str] = None,
                  status: Optional[str] = None, collection: Optional[str] = None, domain: Optional[str] = None,
                  identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """The catalogue's Product Models — from a collection, local, or retired — with search, facets (domain among
    them) and the navigator: domain › device class › vendor, counted."""
    from app.catalogue.views import browse
    ws = _workspace(db)
    _may_read(db, identity, ws)
    return browse(db, ws, q=q, device_class=device_class, vendor=vendor, status=status, collection=collection,
                  domain=domain)


@router.get("/models/search")
def search_models(q: str = "", every: bool = False, limit: int = 30, sources_only: bool = False,
                  workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """Models for a picker: those installed in the catalogue first, then the pinned sources' not yet installed
    (the NetBox library among them), best first — the model code exactly, at its start, inside it, then the name.
    The models of this workspace's domains, unless `every`."""
    from app.catalogue.library import search
    from app.catalogue.sources import SourceProblem
    try:
        return search(db, q, workspace_id=workspace_id, every=every, limit=max(1, min(limit, 100)),
                      sources_only=sources_only)
    except SourceProblem as e:
        raise HTTPException(status_code=503, detail={"error": f"the catalogue's sources cannot be read: {e}",
                                                     "code": "catalogue_sources"})


class InstallOneIn(BaseModel):
    catalogue_id: str


@router.post("/models/install-one")
def install_one_model(body: InstallOneIn, identity: Identity = Depends(get_identity),
                      workspace_id: str = Depends(require_permission("create")), db: Session = Depends(get_db)):
    """Install one model of the pinned sources (and its vendor, when the catalogue has none) — what a person
    picks for a unit they are creating. An existing record that looks like it is never overwritten: the answer is
    409 with that record, to choose instead. Recorded in the catalogue's history as a partial installation."""
    from app.catalogue.library import LibraryProblem, install_one
    try:
        out = install_one(db, body.catalogue_id, actor=_actor(identity))
    except LibraryProblem as e:
        db.rollback()
        raise HTTPException(status_code=409 if e.candidate else 422,
                            detail={"error": str(e), "code": "catalogue_install_one", "candidate": e.candidate,
                                    "candidates": [e.candidate] if e.candidate else []})
    except installer.CatalogueProblem as e:
        db.rollback()
        raise HTTPException(status_code=422, detail={"error": str(e), "code": "catalogue_install_one"})
    db.commit()
    return out


class LinkModelIn(BaseModel):
    catalogue_id: str
    record_uid: str


@router.post("/models/link")
def link_model(body: LinkModelIn, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """A catalogue model made by hand, linked to the same model in the pinned sources (a NetBox device type):
    its empty fields filled — part number, height, weight, every component — the ones it has kept, and kept up to
    date with the source from then on. The catalogue's maintainers."""
    from app.catalogue.library import LibraryProblem, install_one
    ws = _workspace(db)
    _may_install(db, identity, ws)
    try:
        out = install_one(db, body.catalogue_id, actor=_actor(identity), record_uid=body.record_uid)
    except LibraryProblem as e:
        db.rollback()
        raise HTTPException(status_code=409 if e.candidate else 422,
                            detail={"error": str(e), "code": "catalogue_link", "candidate": e.candidate})
    except installer.CatalogueProblem as e:
        db.rollback()
        raise HTTPException(status_code=422, detail={"error": str(e), "code": "catalogue_link"})
    db.commit()
    return out


@router.get("/records/{uid}")
def record_provenance(uid: str, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """A catalogue record's values, each with its source (the collection, edited here, local, a correction
    proposed back), what the collection states beyond the type's fields, its units per workspace, and the
    releases."""
    from app.catalogue.views import provenance
    ws = _workspace(db)
    _may_read(db, identity, ws)
    try:
        return provenance(db, uid, _readable(db, identity))
    except LookupError:
        raise HTTPException(status_code=404, detail="No such record")


@router.get("/review")
def review(identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """Entries waiting for a person: release conflicts, managed values edited here, corrections proposed back."""
    from app.catalogue.views import review_queue
    ws = _workspace(db)
    _may_read(db, identity, ws)
    return review_queue(db, ws)


@router.get("/corrections")
def corrections(identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """Every correction proposed back to Git, as one unified diff per source repository (argus-catalogue, the
    NetBox fork) against the pinned commit — for `git apply` and a pull request — and what each became."""
    from app.catalogue.corrections import patches
    from app.catalogue.sources import SourceProblem
    ws = _workspace(db)
    _may_read(db, identity, ws)
    try:
        return patches(db, ws)
    except SourceProblem as e:
        raise HTTPException(status_code=502, detail={"error": f"the catalogue's sources cannot be read as pinned: {e}"})


@router.post("/entries/{catalogue_id:path}/fields")
def decide_field(catalogue_id: str, body: FieldDecisionIn, identity: Identity = Depends(get_identity),
                 db: Session = Depends(get_db)):
    """One field of an installed entry: managed (the collection's value, now and in later releases), local
    (this workspace's, which releases leave), or propose (kept, and proposed back to Git)."""
    from app.catalogue import views
    ws = _workspace(db)
    _may_install(db, identity, ws)
    try:
        e = views.decide_field(db, ws, _actor(identity), catalogue_id, body.field, body.decision, body.reason)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except installer.CatalogueProblem as exc:
        _problem(db, exc)
    db.commit()
    return _entry_view(e)


glpi_router = APIRouter(prefix="/v1/catalogue/glpi-matches", tags=["catalogue"])


@glpi_router.get("")
def glpi_unmatched(workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """This workspace's GLPI models that no catalogue model matches, with how many units are of each:
    candidates for new catalogue entries. Read only."""
    from app.catalogue import glpi
    return {"workspace_id": workspace_id, "unmatched": glpi.unmatched(db, workspace_id, _workspace(db))}


@glpi_router.post("")
def glpi_match(workspace_id: str = Depends(require_permission("update")), db: Session = Depends(get_db)):
    """Propose a catalogue model for each of this workspace's GLPI units that has none. The proposals wait in the
    review queue (Facts to confirm) until a person accepts or rejects each; the ambiguous and the unmatched are
    reported."""
    from app.catalogue import glpi
    try:
        out = glpi.match(db, workspace_id, _workspace(db))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"error": str(exc)})
    db.commit()
    return out


@router.get("/offered")
def offered_models(workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    """The catalogue's models this workspace is not offered by default (`hidden`): those of collections for
    domains it has no package of. A model picker hides them behind "show every model"."""
    from app.catalogue.system import offered
    return offered(db, workspace_id)


# --------------------------------------------------------------------------- the system catalogue (administrators)

system_router = APIRouter(prefix="/v1/admin/catalogue", tags=["catalogue"])


def _admin(identity: Identity) -> None:
    if isinstance(identity, PatIdentity) or not identity.user.is_admin:
        raise HTTPException(status_code=403, detail="Admins only")


class DesignateIn(BaseModel):
    workspace_id: str


@system_router.get("")
def catalogue_status(identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """Which workspace is the installation's catalogue, what it holds, which workspaces hang from it, the units
    pointing at its models, and its collections (docs/system-catalogue.md). Administrators and the catalogue's
    maintainers."""
    from app.catalogue.system import may_maintain
    if isinstance(identity, PatIdentity) or not may_maintain(db, identity.user):
        raise HTTPException(status_code=403, detail="Administrators and the catalogue's maintainers only")
    from app.catalogue.system import status
    return status(db)


@system_router.post("/designate")
def designate_catalogue(body: DesignateIn, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)):
    """Make a workspace the installation's catalogue, when there is none. Refused while another is, or while
    it holds records other than Vendors and Product Models."""
    _admin(identity)
    from app.catalogue.system import CatalogueProtected, designate, status
    try:
        designate(db, body.workspace_id)
    except CatalogueProtected as e:
        db.rollback()
        raise HTTPException(status_code=422, detail={"error": str(e), "code": "catalogue_workspace"})
    db.commit()
    return status(db)
