"""The object types an accelerator facility keeps.

Tickets and documents ship with seeded types; objects did not, so every object
type was made by an importer with no attributes and nothing could be validated,
autocompleted or shown as a column. This is the catalogue that fills the gap.
docs/asset-schema-design.md is the reasoning; the accelerator package
(backend/packages/accelerator) is the transcription, and this module seeds it.

The shape is one abstract root and six branches, because one object cannot be
the quadrupole, the magnet, the product and the EPICS channel at once, once the
magnet is swapped and the quadrupole stays:

  Functional      what the machine is           survives every hardware swap
  Physical        which serialised box is in it carries serial, warranty
  Catalogue       what it is an instance of     the vendor's product
  Control         how it is driven              the EPIK8s configuration
  Engineering     what the design says it needs utilities, cost, work package
  Location        where it is

Two sets, seeded separately. What exists physically is one inventory shared by
every beamline: assets, products, vendors and locations. How each machine is
arranged, controlled and paid for is its own: the functional branch (facility,
sections, modules, lattice elements), the control branch (configuration, IOCs,
devices, access points) and the engineering records (utilities, procurement). A type in the global set is
created in one catalogue workspace and flagged global, so every workspace can
use and inherit it; the objects of a global type are visible everywhere, and
editable only where they were made. A type in the beamline set is created in
each beamline's own workspace, under global parents, so a beamline's structure
and control stay its own. No global type refers to a beamline type.

Attribute keys are spelled exactly as tickets and documents spell them
(`argus_system`, `argus_subsystem`, ...) or "everything about the vacuum
system" cannot be answered across sections. The control plane keeps the bare
keys the EPIK8s importer already writes; renaming them would orphan every row
already imported.

Seeding is additive. A type that exists keeps every attribute it has and
gains the ones it lacks, so a release that adds a field reaches existing
workspaces without overwriting anything a workspace changed.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.schema import Schema

BASE_UID_SUFFIX = "argus-object"
ROOT_NAME = "Item"

# The two EPIK8s importers name their types `epik8s-...`. A type made by one
# of them is the importer's, empty, and exactly what this catalogue absorbs.
IMPORTER_UID_PREFIX = "epik8s-"


# --- attribute vocabulary --------------------------------------------------

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _option_id(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def _options(values) -> list[dict]:
    """Labels, or (id, label) pairs where the id must be kept stable."""
    out = []
    for item in values:
        option_id, label = item if isinstance(item, tuple) else (_option_id(item), item)
        out.append({"id": option_id, "value": label})
    return out


def _attr(key: str, name: str, type_: str = "string", *, indexed: bool = False,
          multi: bool = False, unique: bool = False, readonly: bool = False,
          options=None, ref: Optional[str] = None, children: bool = False,
          regex: Optional[str] = None) -> dict:
    """One attribute definition, in the shape document_types.py emits.

    A reference names its target type here and is bound to that type's uid
    when the catalogue is seeded, because the uid carries the workspace.
    """
    out = {
        "id": key, "key": key, "name": name, "type": type_,
        "required": False, "multiValue": multi, "unique": unique,
        "readOnly": readonly, "indexed": indexed,
    }
    if options is not None:
        out["options"] = _options(options)
    if ref:
        out["referenceType"] = ref
        out["includeChildren"] = children
    if regex:
        out["regex"] = regex
    return out


def S(key, name, **f):  return _attr(key, name, "string", **f)          # noqa: E704
def X(key, name, **f):  return _attr(key, name, "text", **f)            # noqa: E704
def I(key, name, **f):  return _attr(key, name, "integer", **f)         # noqa: E704,E741
def F(key, name, **f):  return _attr(key, name, "float", **f)           # noqa: E704
def B(key, name, **f):  return _attr(key, name, "boolean", **f)         # noqa: E704
def D(key, name, **f):  return _attr(key, name, "date", **f)            # noqa: E704
def DT(key, name, **f): return _attr(key, name, "datetime", **f)        # noqa: E704
def E(key, name, options, **f): return _attr(key, name, "enumeration", options=options, **f)  # noqa: E704
def U(key, name, **f):  return _attr(key, name, "user", **f)            # noqa: E704
def G(key, name, **f):  return _attr(key, name, "group", **f)           # noqa: E704
def R(key, name, target, **f): return _attr(key, name, "reference", ref=target, **f)  # noqa: E704


@dataclass
class TypeSpec:
    name: str
    parent: Optional[str]
    description: str
    attributes: list = field(default_factory=list)
    abstract: bool = False
    # Other names records of this type go by in imports ("pipe", "bellows"): the mapping's rules match them.
    aliases: list = field(default_factory=list)


# The reference fields that are edges of the graph too, and the verb each one is (knowledge-graph design):
# the ledger derives the edge from the field whenever it projects the record, so the Relations tab, the graph
# and the impact walks see what the field says, and the edge follows every change, revocation and undo.
# (accelerator package, vocabulary.yaml: reference_relations)
def _reference_relations() -> dict:
    from app.packages import defaults
    return defaults.reference_relations()


REFERENCE_RELATIONS = _reference_relations()


def type_uid(workspace_id: str, name: str) -> str:
    return f"{workspace_id}:{BASE_UID_SUFFIX}:{_slug(name)}"


# --- the catalogue, parents before children ---------------------------------
# Defined in the accelerator package (backend/packages/accelerator/object_types.yaml), not here: this is the
# same list, read from it. A type's name, attribute keys and option ids are what stored records use.

def _load_catalogue() -> list[TypeSpec]:
    from app.packages import defaults
    return [TypeSpec(t.name, t.parent, t.description, list(t.attributes), t.abstract, list(t.aliases))
            for t in defaults.object_types()]


CATALOGUE: list[TypeSpec] = _load_catalogue()

BY_NAME: dict[str, TypeSpec] = {spec.name: spec for spec in CATALOGUE}


def depth(name: str) -> int:
    d, cur = 1, BY_NAME[name].parent
    while cur:
        d, cur = d + 1, BY_NAME[cur].parent
    return d


# --- what is shared, and what is one machine's own --------------------------------

SCOPE_ALL = "all"
SCOPE_GLOBAL = "global"
SCOPE_BEAMLINE = "beamline"

# The branches that belong to one machine rather than to the inventory it is built
# from: how it is arranged, how it is controlled, and what it costs. Everything else
# is shared: assets, products, vendors, locations. The engineering records are here
# for the money in them: a procurement record carries a price, and the objects of a
# global type are readable in every workspace.
def _object_section() -> dict:
    from app.packages import defaults
    return defaults.object_section()


BEAMLINE_ROOTS = tuple(_object_section().get("beamline_roots") or ())

# Names a type had before it was renamed. A workspace seeded under the old name is
# carried across in place, keeping its uid, so nothing that points at it breaks.
FORMER_NAMES = dict(_object_section().get("former_names") or {})


def scope_of(name: str) -> str:
    cur: Optional[str] = name
    while cur is not None:
        if cur in BEAMLINE_ROOTS:
            return SCOPE_BEAMLINE
        cur = BY_NAME[cur].parent
    return SCOPE_GLOBAL


GLOBAL_TYPES = [t.name for t in CATALOGUE if scope_of(t.name) == SCOPE_GLOBAL]
BEAMLINE_TYPES = [t.name for t in CATALOGUE if scope_of(t.name) == SCOPE_BEAMLINE]


# --- seeding ------------------------------------------------------------------

class CatalogueMissing(ValueError):
    """The per-beamline set was asked for, and the global types it hangs from are
    not in the catalogue workspace."""


@dataclass
class SeedResult:
    uids: dict = field(default_factory=dict)         # name -> schema uid, for every type usable here
    created: list = field(default_factory=list)
    adopted: list = field(default_factory=list)      # importer-made, now under the catalogue
    renamed: list = field(default_factory=list)      # seeded under a former name, carried across
    extended: list = field(default_factory=list)     # existing, gained attributes or was shared
    duplicates: list = field(default_factory=list)   # a same-named type that is not ours
    iconed: list = field(default_factory=list)       # given their default icon (catalogue_icons)
    reused: list = field(default_factory=list)       # a beamline type the catalogue already shares
    catalogue_created: list = field(default_factory=list)  # shared types added to the catalogue first


def _bound(attributes: list, uids: dict) -> list:
    """Attributes with each reference pointing at its target's uid."""
    out = []
    for attr in attributes:
        attr = dict(attr)
        target = attr.get("referenceType")
        if attr.get("type") == "reference" and target:
            attr["referenceSchemaUid"] = uids[target]
        out.append(attr)
    return out


def _merge(existing: list, wanted: list) -> tuple[list, bool]:
    """Add what is missing; never overwrite or drop what is there. The one thing
    refreshed is a reference's display name, which follows the type it names."""
    index = {a.get("key") or a.get("name"): i for i, a in enumerate(existing)}
    out = [dict(a) for a in existing]
    changed = False
    for attr in wanted:
        i = index.get(attr["key"])
        if i is None:
            out.append(attr)
            changed = True
        elif (attr.get("type") == "reference" and out[i].get("type") == "reference"
              and out[i].get("referenceType") != attr.get("referenceType")):
            out[i]["referenceType"] = attr["referenceType"]
            changed = True
    return out, changed


def _uid_for(db: Session, workspace_id: str, spec: TypeSpec, others: dict) -> str:
    """The uid this type has, or is about to have, in this workspace."""
    own = type_uid(workspace_id, spec.name)
    if db.get(Schema, own) is not None:
        return own
    former = FORMER_NAMES.get(spec.name)
    if former:
        old = db.get(Schema, type_uid(workspace_id, former))
        if old is not None and old.workspace_id == workspace_id and old.name == former:
            return old.uid
    found = others.get(spec.name)
    if (found is not None and found.uid.startswith(IMPORTER_UID_PREFIX)
            and found.parent_schema_uid is None):
        return found.uid
    return own


def catalogue_of(db: Session, workspace_id: str) -> Optional[str]:
    """The workspace this one's types hang from, if any: where their parents live.
    A workspace seeded with the per-beamline set has types whose parents are in the
    catalogue, so it does not have to be told which catalogue it is using."""
    parents = {p for p in db.scalars(select(Schema.parent_schema_uid).where(
        Schema.workspace_id == workspace_id, Schema.applies_to == "objects",
        Schema.parent_schema_uid.isnot(None)))}
    if not parents:
        return None
    homes = list(db.scalars(select(Schema.workspace_id).where(
        Schema.uid.in_(parents), Schema.workspace_id != workspace_id)))
    return max(set(homes), key=homes.count) if homes else None


def ensure_for_import(db: Session, workspace_id: str,
                      catalogue_workspace_id: Optional[str] = None) -> tuple[SeedResult, Optional[str]]:
    """The types an importer writes, made available before it writes: what the CLI importers always did, and
    every importer (web ones too) now does, so a workspace nobody seeded imports as well as a seeded one.

    * a workspace already hanging from a catalogue is brought up to date against it;
    * one seeded on its own (its own types, no catalogue) keeps being self-contained;
    * one with no types: against the given catalogue, else the only global catalogue there is; with several,
      the importer is told to choose rather than guess; with none, the whole catalogue goes in this workspace.

    A catalogue seeded before a shared type existed (Observable came with the beam model) is brought up to
    date first — additive, as seeding it again by hand would be — and the result says what it gained.

    Returns the seed result and the catalogue used (None: self-contained)."""
    catalogue = catalogue_workspace_id or catalogue_of(db, workspace_id)
    if catalogue is None:
        own = db.scalar(select(func.count()).select_from(Schema).where(
            Schema.workspace_id == workspace_id, Schema.applies_to == "objects"))
        if not own:
            homes = sorted({w for w in db.scalars(select(Schema.workspace_id).where(
                Schema.is_global.is_(True), Schema.applies_to == "objects", Schema.workspace_id != workspace_id))})
            if len(homes) == 1:
                catalogue = homes[0]
            elif len(homes) > 1:
                raise CatalogueMissing(
                    f"workspace “{workspace_id}” has no object types yet, and there are several catalogues "
                    f"({', '.join(homes)}): seed it against one first — `scripts/seed_asset_types.py beamline "
                    f"{workspace_id} --catalogue <catalogue>`")
    added: list = []
    if catalogue:
        shared = set(db.scalars(select(Schema.name).where(Schema.workspace_id == catalogue,
                                                         Schema.applies_to == "objects")))
        if any(n not in shared for n in GLOBAL_TYPES):
            added = ensure_asset_types(db, catalogue, scope=SCOPE_GLOBAL).created
    scope = SCOPE_BEAMLINE if catalogue else SCOPE_ALL
    result = ensure_asset_types(db, workspace_id, scope=scope, catalogue_workspace_id=catalogue)
    result.catalogue_created = added
    # The record of which packages a workspace uses stays exact for what an import seeded (app.packages).
    from app.packages.install import note_seeded
    if added:
        note_seeded(db, catalogue, "accelerator", how="seeded", options={"scope": SCOPE_GLOBAL})
    note_seeded(db, workspace_id, "accelerator", how="seeded",
                options={"scope": scope, **({"catalogue_workspace_id": catalogue} if catalogue else {})})
    return result, catalogue


def resolve_type_uids(db: Session, workspace_id: str,
                      catalogue_workspace_id: Optional[str] = None) -> dict:
    """name -> uid of every object type this workspace can use: its own first, then
    the catalogue it hangs from, then any other global one. What an importer needs
    to find the types it writes, whichever way the catalogue was seeded.

    Guessing by name alone would pick whichever global workspace sorts first; the
    catalogue is the one this workspace's own types hang from.
    """
    rows = db.scalars(select(Schema).where(
        Schema.applies_to == "objects",
        (Schema.workspace_id == workspace_id) | Schema.is_global.is_(True))).all()
    if catalogue_workspace_id is None:
        catalogue_workspace_id = catalogue_of(db, workspace_id)

    def rank(row: Schema):
        if row.workspace_id == workspace_id:
            return (0, row.workspace_id, row.uid)
        if row.workspace_id == catalogue_workspace_id:
            return (1, row.workspace_id, row.uid)
        return (2, row.workspace_id, row.uid)

    out: dict = {}
    for row in sorted(rows, key=rank):
        out.setdefault(row.name, row.uid)
    return out


def ensure_asset_types(db: Session, workspace_id: str, scope: str = SCOPE_ALL,
                       catalogue_workspace_id: Optional[str] = None) -> SeedResult:
    """Create the catalogue, or bring it up to date.

    scope "all"      every type, in this one workspace (a single-workspace hub)
    scope "global"   the shared set, in the catalogue workspace, flagged global
    scope "beamline" the per-machine set, in this workspace, under global parents
                     found in `catalogue_workspace_id`

    Idempotent and additive: types that exist keep their attributes and gain any
    they lack. A type the EPIK8s importers made (uid `epik8s-...`, no parent) is
    adopted rather than duplicated, so the order of seeding and importing does not
    matter. A type seeded under a former name is renamed in place. A same-named
    type that is anybody else's is left alone and reported: reparenting somebody's
    tree to make it fit is not the seeder's call.
    """
    if scope not in (SCOPE_ALL, SCOPE_GLOBAL, SCOPE_BEAMLINE):
        raise ValueError(f"unknown scope {scope!r}")
    if scope == SCOPE_BEAMLINE:
        if not catalogue_workspace_id:
            raise ValueError("the per-beamline set hangs from the global one: say which "
                             "workspace holds it")
        if catalogue_workspace_id == workspace_id:
            raise ValueError("a workspace cannot be its own catalogue; use scope 'all'")

    if scope in (SCOPE_ALL, SCOPE_GLOBAL):
        hangs_from = catalogue_of(db, workspace_id)
        if hangs_from:
            raise ValueError(
                f"workspace {workspace_id!r} already hangs from the catalogue in {hangs_from!r}; "
                f"seeding it in full would make a second copy of the shared types. Use the "
                f"per-beamline scope with that catalogue.")

    result = SeedResult()
    specs = [s for s in CATALOGUE if scope == SCOPE_ALL or scope_of(s.name) == scope]
    share = scope == SCOPE_GLOBAL

    if scope == SCOPE_BEAMLINE:
        shared = {
            row.name: row.uid for row in db.scalars(select(Schema).where(
                Schema.workspace_id == catalogue_workspace_id, Schema.applies_to == "objects"))
        }
        missing = [n for n in GLOBAL_TYPES if n not in shared]
        if missing:
            raise CatalogueMissing(
                f"workspace {catalogue_workspace_id!r} does not hold the global types "
                f"({len(missing)} missing, e.g. {', '.join(missing[:4])}). Seed it first with "
                f"the global scope; if it was seeded before Equipment Item and Place were "
                f"renamed, seed it again.")
        result.uids.update({name: shared[name] for name in GLOBAL_TYPES})

    others = {
        s.name: s for s in db.scalars(select(Schema).where(
            Schema.workspace_id == workspace_id, Schema.applies_to == "objects"))
    }
    if scope == SCOPE_BEAMLINE:
        # A per-beamline type the catalogue has chosen to share (its control branch, so that several
        # beamlines' IOCs are one kind of thing) is used from there: a beamline copy would sit beside
        # the shared one in every picker, with the beamline's records split between the two. A
        # beamline that already has its own copy keeps it.
        offered = {row.name: row.uid for row in db.scalars(select(Schema).where(
            Schema.workspace_id == catalogue_workspace_id, Schema.applies_to == "objects",
            Schema.is_global.is_(True)))}
        for spec in [s for s in specs if s.name in offered and s.name not in others]:
            result.uids[spec.name] = offered[spec.name]
            result.reused.append(spec.name)
        specs = [s for s in specs if s.name not in result.reused]
    # References need every uid up front, before any type is written.
    for spec in specs:
        result.uids[spec.name] = _uid_for(db, workspace_id, spec, others)

    for spec in specs:
        uid = result.uids[spec.name]
        parent_uid = result.uids[spec.parent] if spec.parent else None
        wanted = _bound(spec.attributes, result.uids)
        schema = db.get(Schema, uid)
        if schema is None:
            clash = others.get(spec.name)
            if clash is not None and clash.uid != uid:
                result.duplicates.append(spec.name)
            db.add(Schema(
                uid=uid, workspace_id=workspace_id, name=spec.name,
                description=spec.description, applies_to="objects",
                is_concrete=not spec.abstract, parent_schema_uid=parent_uid,
                attributes=wanted, is_global=share,
                metadata_json={"source": "argus", **({"aliases": spec.aliases} if spec.aliases else {})},
            ))
            result.created.append(spec.name)
            db.flush()
            continue

        touched = False
        if uid.startswith(IMPORTER_UID_PREFIX) and uid != type_uid(workspace_id, spec.name):
            schema.parent_schema_uid = parent_uid
            schema.is_concrete = not spec.abstract
            schema.description = schema.description or spec.description
            result.adopted.append(spec.name)
        elif schema.name != spec.name:
            schema.name = spec.name
            schema.description = spec.description
            result.renamed.append(spec.name)
        if share and not schema.is_global:
            schema.is_global = True
            touched = True
        # A type this catalogue owns can move in its tree (Network Device went from under Asset
        # to under IT Equipment) and can stop being concrete; a release that does so has to
        # reach workspaces seeded before it. Only types it owns: somebody else's stay theirs.
        if uid == type_uid(workspace_id, spec.name) or uid.startswith(f"{workspace_id}:{BASE_UID_SUFFIX}:"):
            if schema.parent_schema_uid != parent_uid:
                schema.parent_schema_uid = parent_uid
                touched = True
            if schema.is_concrete != (not spec.abstract):
                schema.is_concrete = not spec.abstract
                touched = True
        merged, changed = _merge(schema.attributes or [], wanted)
        if changed:
            schema.attributes = merged
            touched = True
        # Aliases are the catalogue's own knowledge: a release that adds one reaches workspaces seeded before.
        if spec.aliases and (schema.metadata_json or {}).get("aliases") != spec.aliases:
            schema.metadata_json = {**(schema.metadata_json or {}), "aliases": spec.aliases}
            touched = True
        if touched and spec.name not in result.adopted and spec.name not in result.renamed:
            result.extended.append(spec.name)
        db.flush()
    # Every type a picture: its own default, or its nearest ancestor's; never over one already chosen.
    from app.services import catalogue_icons
    result.iconed = catalogue_icons.apply(db, workspace_id, {spec.name: result.uids[spec.name] for spec in specs},
                                          share)
    return result
