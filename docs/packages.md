# Template packages

A workspace's definitions — object types, ticket and document types, shared enumerations, workflows — come
from **template packages**: versioned YAML in `backend/packages/<id>/`, read by `backend/app/packages/`.

| Package | Holds | Depends on |
|---|---|---|
| `core-facility` | the base ticket and document types and their kinds, the status and priority enumerations, the default ticket workflow | — |
| `accelerator` | the object catalogue of an accelerator facility (153 types: functional, physical, catalogue, control, engineering, location, IT records, ports) and the Other Equipment classes | `core-facility` |

Every workspace has `core-facility`; `accelerator` is chosen when the workspace is made, or installed later.

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
- A newer version is applied additively (what a workspace lacks is added; nothing it has is changed).
  Renames, removals, type changes and tighter validation will need a reviewed upgrade with a migration plan.

API: `GET /v1/packages`, `GET /v1/packages/{id}`, `POST /v1/packages/resolve`,
`GET /v1/workspaces/{ws}/packages`, `POST /v1/workspaces/{ws}/packages/preview`,
`POST /v1/workspaces/{ws}/packages/install` (workspace owners and administrators). Web: **New workspace →
Starts from**, and the workspace's **Packages** page.

## Parity

The two packages were generated from the Python definitions they replace, and
`backend/tests/fixtures/package_parity/seeding.json` records what seeding wrote before them, in the four ways
a workspace is seeded (core, self-contained catalogue, shared catalogue, beamline). `tests/test_packages.py`
installs the packages the same four ways and requires the identical result.
