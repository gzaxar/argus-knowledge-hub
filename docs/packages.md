# Template packages

A workspace's definitions — object types, ticket and document types, shared enumerations, workflows — come
from **template packages**: versioned YAML in `backend/packages/<id>/`, read by `backend/app/packages/`.

| Package | Holds | Depends on |
|---|---|---|
| `core-facility` | the base ticket and document types and their kinds, the status and priority enumerations, the default ticket workflow | — |
| `core-objects` | the object backbone: the root and its branches, equipment (Asset) and what is generic about it — ports, cables, supports, spares, instruments, chillers and cooling-circuit components — products and vendors, places; the Other Equipment classes | `core-facility` |
| `it` | network and computing equipment (switches, routers, firewalls, Wi-Fi access points, converters, servers, workstations, storage, patch panels) and network records | `core-objects` |
| `electrical` | switchboards, distribution panels, breakers, transformers, UPS, generators, meters, circuits; `fed from` is a power edge | `core-objects` |
| `hydraulic` | water pumps, valves, pipe segments, tanks, flow and pressure transmitters, heat exchangers; `cooled by` is a cooling edge | `core-objects` |
| `hvac` | air handling units, fan coils, dampers, cooling towers, heat pumps, ducts, sensors | `core-objects` |
| `plant` | electrical, hydraulic and HVAC together, with plant systems and technical rooms | `electrical`, `hydraulic`, `hvac` |
| `accelerator` | the accelerator facility: the machine as functions, its equipment (magnets, RF, vacuum, diagnostics, motion, timing), control and engineering records | `core-objects`, `it` |

Every workspace has `core-facility`; the others are chosen when the workspace is made, or installed later, alone
or together: no two packages define the same type, so any combination shares one core. Accelerator 2.0 is the
1.x catalogue split in three — core-objects, it, accelerator — with the same types and uids: a workspace on 1.x
upgrades with every moved type reported as *moved* (no decision, nothing changed) and gains the four new IT types.

## Format

`package.yaml` is the manifest:

```yaml
id: accelerator                 # stable; never reused for something else
version: 1.0.0                  # semantic version
name: Accelerator catalogue
description: …
owner: INFN ARGUS               # who answers for it
license: EUPL-1.2
depends: {core-facility: ">=1.0,<2"}
provides: [object-catalogue, accelerator-catalogue]   # capabilities importers will require
contents: [object_types.yaml, vocabulary.yaml]
```

Each content file holds one or more sections: `option_sets`, `enumerations`, `object_types`
(`types`, `beamline_roots`, `former_names`), `ticket_types` and `document_types` (`base`, `kinds`),
`workflows`, `equipment_classes`, `reference_relations`, `map_layers`. An object type:

```yaml
- name: Vacuum Pump
  parent: Asset                 # defined earlier, here or in a dependency
  description: …
  abstract: false
  icon: tabler/propeller        # an icon that ships in app/catalogue_icons
  behaviors: []                 # roles ARGUS's code gives a type (GET /v1/packages/behaviors)
  locatable: true               # may have a mapped location (basic GIS release)
  map_layer: vacuum             # one of the map_layers
  attributes:
    - {key: pump_kind, name: Pump kind, type: enumeration, option_set: pump_kinds}
    - {key: vendor_ref, name: Vendor, type: reference, reference: Vendor}
    - {key: rated_power_kva, name: Rated power (kVA), type: float, unit: kVA}   # a number's unit
```

A package holds **definitions only**: no site data (coordinates, records) and no code. It is read with a safe
YAML loader, and every key is checked, so neither has anywhere to go.

**Never rename** a type, an attribute key or an option id in a published package: stored records use them.
A type's uid in a workspace is `<workspace>:argus-object:<name as slug>` (tickets `:argus-ticket`, documents
`:argus-document`), independent of the package that defines it.

## Validating

```
python -m app.packages validate                 # every package that ships
python -m app.packages validate path/to/pkg     # one being written, against the shipped ones
python -m app.packages list
```

It reports, with file and place: unknown keys, invalid versions and version ranges, missing or unsatisfied
dependencies and cycles, duplicate names and keys, parents that are missing or come later, references to
types nobody defines, option sets and defaults, regular expressions, icons, map layers, workflow states,
and behaviour ids ARGUS does not implement. The backend tests run it.

## Installing, and the record

`app/packages/install.py` installs a package and its dependencies **in one transaction**: if any step fails,
nothing is applied. A preview runs the same installation and rolls it back. Each workspace records, per
package, the **exact version and the checksum** of what was applied, how it went in (for the catalogue:
self-contained, the shared catalogue, or hanging from one), and its history: `install`, `upgrade`,
`seeded` (by an import or `scripts/seed_asset_types.py`), `detected` (in place before the record began).

- Reinstalling the version a workspace has, with the same checksum, changes nothing.
- A package whose content changed without a new version is refused: raise the version.
- A newer version goes through an **upgrade** (below).

API: `GET /v1/packages`, `GET /v1/packages/{id}`, `POST /v1/packages/resolve`,
`GET /v1/workspaces/{ws}/packages`, `POST /v1/workspaces/{ws}/packages/preview`,
`POST /v1/workspaces/{ws}/packages/install` (workspace owners and administrators). Web: **New workspace →
Starts from**, and the workspace's **Packages** page.

## Upgrades

Each version a workspace is given is kept as a snapshot (`package_snapshots`). Moving to a newer version
compares three things — the snapshot, the newer version, and the workspace's definitions today (its local
edits) — change by change (`app/packages/diff.py`):

| Category | What | How it is applied |
|---|---|---|
| additive | a new type, attribute, option, kind, enumeration, class; a type that becomes concrete; an attribute that takes several values | by itself |
| definition | a label, an option's label, a description, aliases | by itself, except where the workspace changed it itself |
| breaking | a removal; a rename (an attribute's `renamed_from`, a type's `former_names`); an attribute's type or target changed; a type moved in the tree or no longer concrete; tighter validation (a pattern, unique, required, single-valued, an option removed) | only by a decision in the migration plan |

The preview (`POST /v1/workspaces/{ws}/packages/preview`, or the Packages page) lists every change with the
records it bears on, the values the newer definition would refuse, and whether it touches the workspace's
own edits. The install then needs a decision for each breaking change, `apply` or `keep` (the workspace's
definition stays), in `decisions`; without one, nothing is applied. Applying is refused while records hold
values the newer definition would not accept — change them first, or keep. What applying does:

- an attribute removed: its definition goes; the values records hold under it stay;
- an attribute renamed: the definition is renamed and the values move to the new key on every record;
- tighter validation, a new type: the new definition, when no record breaks it;
- a type removed or no longer concrete: records can no longer be made of it; existing ones stay;
- a type moved: its new parent; a type renamed: its new name, same uid;
- an enumeration or option removed: removed; a class removed: no longer offered.

A workspace's own edits are kept: an attribute it removed is not added back, a label it changed is not
changed back. The upgrade's history entry keeps the plan's decisions, what each did, and the conflicts.
A beamline workspace upgrades its machine's own types; the shared ones are upgraded in the catalogue
workspace they come from.

## Imports need packages; they never install them

An importer declares the capabilities it needs (`provides` of a package) and `app/packages/requirements.py`
checks them before anything is written. A workspace that lacks one is told what to install, and nothing is
imported. Imports never install or rewrite definitions: a workspace's definitions change only through the
installer, previewed and recorded.

| Import | Needs | May still create |
|---|---|---|
| EPIK8s configuration (web and `scripts/import_epik8s.py`) | `accelerator-catalogue` | its own `epik8s-…` types when the catalogue has none of that name |
| PBS workbook (`scripts/import_pbs.py`) | `accelerator-catalogue` | — |
| Jira issues | `tickets` | a ticket kind for each issue type the data names that the workspace lacks |
| Confluence, Markdown, Olog | `documents` | a missing core document kind it classifies into |

The base ticket and document types' fields are no longer rewritten by an import (they were reset to the
release's on every import, losing local edits). A workspace given its definitions before the record began is
recognised when an import first asks (recorded as `detected`), not reinstalled. What an import's own data
names — a Jira issue type, an Insight object type, the type a source record states — is the data's, and may
still be created; a catalogue package never is.

The automatic catalogue fallback (`asset_types.ensure_for_import`: adopt the only catalogue there was, or put
the whole catalogue in the workspace) is gone.

## Parity

The two packages were generated from the Python definitions they replace, and
`backend/tests/fixtures/package_parity/seeding.json` records what seeding wrote before them, in the four ways
a workspace is seeded (core, self-contained catalogue, shared catalogue, beamline). `tests/test_packages.py`
installs the packages the same four ways and requires the identical result.
