# Template packages

A workspace's definitions — object types, ticket and document types, shared enumerations, workflows — come
from **template packages**: versioned YAML in `backend/packages/<id>/`, read by `backend/app/packages/`.

| Package | Holds | Depends on |
|---|---|---|
| `core-facility` 2.0 | the base ticket and document types and their kinds, the status and priority enumerations, the default ticket workflow — domain neutral | — |
| `core-objects` 2.0 | the object backbone: equipment (Asset) and what is generic about it, products and vendors, places; the Other Equipment classes — domain neutral | `core-facility` |
| `core-records` | records that are not equipment: Record, Organization, Contract | `core-facility` |
| `it` | network and computing equipment, peripherals, network records, software and licences, the IT service desk's kinds; GLPI (docs/glpi.md) | `core-objects`, `core-records` |
| `safety` | fire protection, gas and radiation monitoring, shielding, sources; fire zones and radiation areas; inspections, findings, incidents, permits to work | `core-objects` |
| `vacuum-cryo` | vacuum, cryogenics and gas handling; leak tests, bake-outs, cryogen deliveries | `core-objects` |
| `civil-access` | rooms, access zones, doors, readers, controllers, elevators, cranes; defects, civil works, access requests | `core-objects` |
| `optics-alignment` | lasers, optics, optical tables, survey points and instruments, laser controlled areas | `core-objects` |
| `environmental` | monitoring networks, stations, sensors, loggers, sampling points; calibrations, exceedances | `core-objects` |
| `administration` | budget lines, grants, purchase orders, invoices; procurement requests | `core-records` |
| `tech-transfer` | inventions, patents, licences, NDAs, spin-offs, valorization projects, research outputs | `core-records` |
| `electrical`, `hydraulic`, `hvac`, `plant` | the technical plant; `fed from`, `cooled by` | `core-objects` |
| `accelerator` 2.1 | the accelerator facility: functions, magnets, RF, diagnostics, motion, timing, control, engineering records; the beam's own impacts and criticalities (an extension) | `core-objects`, `it`, `safety`, `vacuum-cryo`, `optics-alignment` |

Every workspace has `core-facility`; the others are chosen when the workspace is made, or installed later, alone
or together: no two packages define the same type, kind, relation verb, role or restricted class, so any
combination shares one core. docs/domain-packages.md has the design of the domain packages, the types that
moved between packages (unchanged), compatibility, and the decisions their domain owners must take; none of
them establishes regulatory compliance.

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

Each content file holds one or more sections (a section lives in one file): `option_sets`, `enumerations`,
`object_types` (`types`, `beamline_roots`, `former_names`), `ticket_types` and `document_types` (`base`,
`kinds` — a kind may have `attributes` of its own), `workflows`, `equipment_classes`, `reference_relations`,
`map_layers`, `extends`, `relation_types`, `roles`, `restricted_classes`, `imports`, `queries`. An object type:

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

An attribute may also say `validator: <id>` (a check ARGUS implements: `GET` the ids from
`app/packages/validators.py`), `restricted: <class>` (hidden from anyone not given that class), and
`description`. The other sections:

```yaml
extends:                        # add to a type a dependency defines; never change what is there
  - {area: ticket_types, type: base, options: {argus_impact: [{id: beam_down, value: Beam down}]}}
  - {type: Contract, attributes: [{key: cig, name: CIG, validator: admin.cig}]}
relation_types:                 # verbs with a meaning; refused between the wrong types
  - {id: reports-to, verb: "reports to", from: [Fire Detector], to: Fire Alarm Panel,
     layer: safety, flows: reverse, carries: function}
workflows:                      # a package's workflow names its kinds; an approval step needs `approve`
  - id: permit-to-work
    applies_to: ["Permit to Work"]
    initial: requested
    states: [{key: requested, name: Requested, category: open}, …]
    transitions: [{from: under_review, to: approved, name: Approve, requires: [approver]}, …]
roles:                          # role templates, offered to workspaces with the package; never granted
  - {id: fire-safety-officer, name: …, description: …, objects: [read, create, modify], tickets: [read, approve]}
restricted_classes: [{id: source_security, description: …}]
imports: [{importer: locations, description: …}]       # importer ids from app/packages/importers.py
queries:                        # representative questions, run by the tests against the fixture
  - {id: extinguishers-due, title: …, entity: assets, jql: 'type = "Fire Extinguisher" AND …',
     fixture: fixtures/fire.yaml, expect: [EXT-01, EXT-03]}
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

Every importer's prerequisites are listed in `app/packages/importers.py` (and a package's `imports:` may
only name importers listed there):

| Import | Needs | May still create |
|---|---|---|
| EPIK8s configuration (web and `scripts/import_epik8s.py`) | `accelerator-catalogue` | its own `epik8s-…` types when the catalogue has none of that name |
| PBS workbook (`scripts/import_pbs.py`) | `accelerator-catalogue` | — |
| GLPI | `it-catalogue`, `records`, `tickets`, `documents` | workspace types and fields for GLPI's own schema, only once approved |
| Locations (CSV, GeoJSON) | `object-catalogue` | — |
| Jira issues | `tickets` | a ticket kind for each issue type the data names that the workspace lacks |
| Confluence, Markdown, Olog | `documents` | a missing core document kind it classifies into |
| Jira Insight, Git | — | the types the source's own schema defines (the data's, not a package's) |

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
installs the packages the same four ways and requires the identical result, but for what is listed as added
since (the split, the new IT types, map placement, and 1.35.26's neutral core, GLPI provenance fields and the
types of the packages the accelerator now stands on).
