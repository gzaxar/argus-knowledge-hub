# Catalogue collections — design proposal (draft, for review)

Status: **R5 done (2026-10-31); first release pending deployment** — the collections live in two Git repositories under `infn-argus` (§A,
below), no longer in `backend/catalogue/`; the draft collections that were there, written as examples and not
checked against manufacturer documentation, were removed. The format and its validator
(`python -m app.catalogue validate`) are in `app/catalogue/` (S1). Install, preview and upgrade are in `app/catalogue/install.py`
and `/v1/catalogue/collections` (S2): records change only when an administrator installs. The pages are
`/catalogue/models`, `/catalogue/models/:uid` and `/catalogue/collections` (S3). The export, the migration
manifest and the report are `python -m app.catalogue export` (S4). The
production inventory ran on 2026-10-31 (§0.1), and the format was revised from it.

Template packages (`backend/packages/`, docs/packages.md) hold **definitions**: the Product Model and Vendor
*types*. This proposal adds **catalogue collections**: the reusable Product Model and Vendor *records* — the
manufacturers and their models — kept in Git, versioned, reviewed, and installed into the shared catalogue
workspace. Installed equipment stays in its own workspace and points at the shared models.

| | Template package | Catalogue collection | Installed asset |
|---|---|---|---|
| Holds | types, attributes, workflows | Vendors, Product Models | a unit: serial number, position, owner |
| Lives in | `backend/packages/` (Git) | `infn-argus/argus-catalogue`, `infn-argus/devicetype-library` (Git, pinned) | a workspace's database |
| Goes into | every workspace that installs it | the shared catalogue workspace only | its own workspace |
| Example | `Product Model` has `model_code` | `moxa/nport-5450` | `SPARC-CONV-07`, instance of `moxa/nport-5450` |

## A. Two sources, one catalogue (decided 2026-10-31)

| Repository | What | Format | Licence |
|---|---|---|---|
| [`infn-argus/devicetype-library`](https://github.com/infn-argus/devicetype-library) | IT devices: a fork of the NetBox Device Type Library. INFN's additions on branch `infn`, under the upstream schema and checks, so suitable ones go back upstream from topic branches. Nothing ARGUS-specific. | NetBox device type YAML | CC0-1.0 (upstream's) |
| [`infn-argus/argus-catalogue`](https://github.com/infn-argus/argus-catalogue) | Manufacturers (all of them, once); accelerator equipment (pumps, gauges, power supplies, DAQ, ADCs, motion, …); the ARGUS metadata of the IT models (device class, instance type, EOL, successor). Releases are tags `vX.Y.Z`; CI runs this validator, with `--against` the previous tag. | the collections of §2 | CC0-1.0 |

Inspected before creating them: upstream (head `f3a04d6`) already defines all five Moxa serial device servers
INFN uses (NPort 5250A, 5410, 5450, 5650-8, 5650-16), so the fork adds nothing for Moxa; it has no Basler
device type, so INFN's three Basler cameras (a2A1920-51gmBAS, a2A2600-20gmBAS, scA640-70gm) are its first
additions, each checked against Basler's documentation first.

**Identity, across both sources:**

- One commercial model, one entry. Model ids are `vendor/model-slug`, unique over both sources: the validator
  runs over every collection of both, and a model the NetBox library defines is never defined again in
  `argus-catalogue` — which may only add its ARGUS metadata, keyed by the same id.
- A NetBox device type's id is its vendor's id and its slug without the manufacturer's prefix
  (`moxa-nport-5650-16` → `moxa/nport-5650-16`).
- Vendors live only in `argus-catalogue/collections/vendors`. A NetBox `manufacturer` is matched through the
  vendors' aliases; an unknown one stops the import until it is added.
- No site data in either repository: serial numbers, installed units, locations, sellers, prices, people.
- Each source is pinned by a lock file in ARGUS (`backend/catalogue/`, stage R3): repository, commit (and tag),
  and for NetBox the selected device types. ARGUS reads the files at that commit, never a branch head; changing
  a pin is a reviewed pull request, and the install records each collection's checksum.

**Which fields Git manages:**

| Fields | Managed by |
|---|---|
| name, model code, part number, physical and port specifications of an IT device | the NetBox fork |
| the same, for accelerator equipment | `argus-catalogue` |
| device class, instance type, EOL, successor, datasheet, related models | `argus-catalogue` |
| description, seller, support, firmware in service, anything no collection states | the workspace (local) |

A value a site corrects is marked *propose to Git* (§3); the correction is exported as a patch against the
file it belongs in — the fork's device type or `argus-catalogue`'s entry — for a pull request (stage R5).

### As built (R2, R3)

- **The fork** (`infn` branch, `25e998f`): INFN's three Basler cameras, each value from Basler's own
  documentation (the ace 2 pages of docs.baslerweb.com; the scout GigE user's manual AW00011919000 v19), passing
  upstream's yamllint and schema tests. The five Moxa NPort models INFN uses are upstream already.
- **`argus-catalogue` v0.1.0** (`63a81dd`): 18 manufacturers; 50 accelerator models in six collections, identity
  only (manufacturer, model code, name, device class, the ARGUS type of their units), each saying its
  specifications are not yet verified, listed in `VERIFICATION.md`; and `it-classification`, the ARGUS side of
  the eight NetBox device types. Records whose identity is not a clear manufacturer designation (25:
  pump-and-controller combinations, product families, site-made or unclear names) are left for a person.
- **`argus-catalogue` v0.2.0** (`c0121da`, pinned in ARGUS 1.35.60): every collection names its domain, the
  packages whose workspaces its models are offered to (docs/system-catalogue.md, C4); no entry changed.
- **The format** gains `classifications`: ARGUS's metadata (device class, instance type, EOL, spares,
  relations) for a model another source defines, by the same id. When ARGUS reads its sources, a NetBox model
  with no classification, a classification with no model, and a classification of a model the Argus-native
  collections define themselves are each refused.
- **`backend/catalogue/sources.lock.yaml`** pins both repositories by full commit (and the release tag, which must
  still point at it; a newer release can be pinned from Administration, §4); `app/catalogue/sources.py` fetches only that commit into a bare cache and reads files with
  `git show` — nothing is checked out or run — maps the selected NetBox device types to the `it-devices`
  collection (id, vendor by alias, model code, part number; height, weight, network, serial and power ports
  as specifications) with their classification, and writes the result once per lock. `load_tree()` reads
  it, so validation, preview, install, upgrade and export all work on both sources together.
  `python -m app.catalogue sources` shows the pins. The API pod must reach github.com.
- **A code found only inside a record's name** (the export, and the install's link candidates) is a
  possible match for a person, never a link or a merge by itself: the export's first run against the
  sources would otherwise have merged the TwisTorr 305 FS pump's remote controller (8 units) into the pump.
- **Migration report on the local copy:** 172 records → 70 match the pinned entries exactly, 8 possible
  matches for a person (six are the same product: TPG 366, 4UHV, XGS-600, the two ace 2 cameras, a Parker
  valve; two are not: the TwisTorr controller, an ET-7226/PET-7226 pair), 72 to export, 1 duplicate vendor, 21
  skipped. Installed with the manifest and the six same-product matches decided (rolled back): 76 records
  adopted in place, none created, only the duplicate vendor merged — the TwisTorr controller untouched — and
  every reference kept.

**Stages from here:** R1 the repositories (done); R2 entries from INFN's records, each verified against the
manufacturer's documentation, and the Basler additions in the fork; R3 ARGUS reads the pinned sources (lock
file, NetBox mapping) under the existing preview, adoption and upgrade; R4 GLPI devices matched to models
through review; R5 corrections as patches, administrator documentation, and an upstream pull request with
the owner's go-ahead.

## 1. What is there today (inspected)

- **Types.** `core-objects` 2.1 defines `Product Model` (vendor, vendor_ref → Vendor, model_code, device_class,
  datasheet_url, firmware_version, eol_date, mtbf_hours, typical_spares, inventory_url) and `Vendor` (contact,
  support_contract, support_expires, rma_procedure, website), with the behaviours `product_model` and
  `vendor`. An asset's `product_model` reference ("Instance of") and `spare_for` point at a Product Model.
- **Sharing.** A record is visible outside its workspace only when it is `is_global`
  (app/services/visibility.py). The catalogue workspace is the one that holds the global `Asset` type, and
  anything created in a global workspace is flagged global.
- **Writing.** Records are created through the fact ledger (`ledger.service.create_record`). A value has a
  method: `manual` is authoritative by default, `stated` contributory (app/ledger/policy.py). So a value
  someone set or confirmed by hand already outranks one a source states.
- **Aliases.** `asset_labels` keeps keys from other systems (type, namespace, value, verified). Catalogue
  mapping (app/services/catalogue_mapping.py) already turns Insight "… Models" into Product Models and Vendors
  this way, with duplicate detection and undo.
- **GLPI** (app/integrations/glpi) brings installed devices, with the manufacturer as text and the model as
  GLPI's `ComputerModel` and `NetworkEquipmentModel` dropdowns. Today nothing links them to a Product Model.
- **Demo data.** `it-services` has 9 Product Models and 5 Vendors, all synthetic and local (not global).
  `medium-linac` has none.
- **Production.** The INFN shared Accelerator workspace can only be read by an administrator, and its data
  has not been inspected yet. The format is therefore **not frozen** until the read-only inventory (§0) has run
  there, and its evidence may still change the fields and collection boundaries below.

## 0. Before freezing the format: a read-only inventory (S0)

`backend/scripts/catalogue_inventory.py`, run by an administrator in the API pod. It opens a read-only
transaction and writes nothing. For every workspace, or the one named, it reports:

- the Product Models and Vendors, global and local, with their counts;
- the vendors as written: text only (`vendor` with no `vendor_ref`), the spellings that normalise to one
  name (alias candidates), and the references to a vendor record that no longer exists;
- the models with no model code, no vendor or no device class;
- the duplicates: the same normalised vendor and model code, in one workspace or across several;
- **cross-domain use:** for each model, the object types and workspaces of the units that point at it, so a
  model used by both IT and accelerator units is visible before the collection boundaries are fixed;
- the references that point at the models: units (`product_model`, `spare_for`, any other reference
  attribute), relations, labels and document links, with counts;
- the attribute keys actually in use on models, beyond the type's own: candidates for `specifications`;
- a sample of 20 models per workspace, with names and attributes, and no other record.

The output is JSON and Markdown, and the decisions it informs are listed at the end of the Markdown.
`sh backend/scripts/run_catalogue_inventory.sh` runs it in the production pod and copies the report back.

### 0.1 What production holds (2026-10-31) and what it changed

| | |
|---|---|
| Shared models (`accelerator-infn`) | 131, all global; 33 used by units |
| Shared vendors | 41, all records (no vendor written only as text) |
| No model code | **119 of 131**: the designation is in the name (`PKR 251`, `KIM101`) |
| No vendor | 21, some of them not products (a company name, a type name, `Controller Motor Models`) |
| Device class | set on all 131, in 26 spellings (`switch` and `network switch`, `host` and `server`, `chassi`) |
| Description | 33 longer than 300 characters (datasheet text pasted in); 13 name the seller ("Sold by: …") |
| Extra attribute keys | none: no specification is structured today |
| References to models | 305 unit `product_model`, 383 relations, 289 labels, 0 document links; none dangling |
| Cross-workspace use | 1 model (a Basler camera, in `btf` and `euaps`) |
| Duplicates found | 0 by the old normaliser; it missed `INSTRUMENTATION TECHNOLOGIES DD` = `Instrumentation Technologies` |
| `it-services-demo` | 9 local, synthetic models (`synthetic-demo`): not part of the migration |

What the format now says (S1, revised):

1. **`model_code` is required.** The duplicate check relies on it. The export proposes it from the name when
   it is empty, and the reviewer confirms it; a record whose code cannot be told stays local.
2. **`device_class` is required, from one list** (`DEVICE_CLASSES` in `app/catalogue/validate.py`): the 26
   spellings, merged into 23 classes. Adoption maps the old spelling (`controller motor` → `motion controller`)
   as a proposed change.
3. **`category` is dropped.** Nothing uses it; the device class and the instance type already sort the
   models. `core-objects` 2.2 no longer needs it.
4. **`specifications` stay optional** and are written by hand: there are no structured keys to carry over,
   only datasheet text. The export does not try to parse it.
5. **A description is at most 500 characters.** A pasted datasheet is the manufacturer's text, which a
   CC-BY collection cannot relicense: the figures go in `specifications`, and the datasheet is linked.
6. **The seller is site data.** "Sold by" in a description, and `fornitore` / `supplier_ref` on units, are
   never exported; the export moves them to the migration manifest as local values (§3).
7. **A vendor is the manufacturer**, not the national subsidiary that sold it: `AGILENT TECHNOLOGIES ITALIA
   S.P.A.` becomes an alias of `agilent`. The normaliser now also drops `d.d.` and `d.o.o.`.
8. **Collections are cut by domain, not by facility.** Units come from facilities (`btf`, `euaps`), and only
   one model crosses them. Units per class (from the local copy of the same data): motor axes and motion controllers (118), vacuum (120), cameras
   (24), serial converters (5), servers (5). So a **`motion`** collection (PI, Thorlabs, Phytron, Faulhaber)
   joins the list in §2, and it carries the most-used models.
9. **Adoption is in place**, as planned: with 305 unit references, 383 relations and 289 labels to keep,
   every adopted model keeps its uid.

## 2. Layout and identity

```
backend/catalogue/
  vendors/                     # every manufacturer, once
    collection.yaml
    vendors.yaml
  it-network/                  # switches, routers, APs, firewalls, serial device servers
    collection.yaml
    models.yaml
  it-compute/
  accelerator-power/           # magnet power supplies
  accelerator-diagnostics/     # BPMs, cameras, current transformers
  accelerator-rf/
  vacuum/                      # gauges, pumps, controllers
  motion/                      # motors, stages, motion controllers (the most used in production)
  timing-control/              # event systems, PLCs, digitizers
```

- **One manufacturer, one entry.** Manufacturers live only in `vendors/`, and domain collections reference
  them by id. A model id is unique across all collections, which the validator checks over the whole tree.
  The same Moxa therefore serves both IT and accelerator collections, and no two collections can both define
  `moxa/nport-5450`.
- **Stable ids.** A vendor's id is a slug (`moxa`). A model's id is `vendor/model-slug` (`moxa/nport-5450`).
  Ids are never reused or renamed; a rename is a new name with `former_ids`.
- **The link to a record** is a row in a new table, `catalogue_entries`, not a free label:

  | column | |
  |---|---|
  | `catalogue_id` | `moxa/nport-5450`, **unique** (one record per id, in the database) |
  | `record_uid` | the Argus record, **unique** (one id per record) |
  | `kind` | vendor or model |
  | `collection_id`, `collection_version`, `collection_checksum` | which release last stated it |
  | `managed_fields` | the fields the collection manages for this record (§3) |
  | `status` | active, retired, or transferring (§3) |
  | `adopted_at`, `adopted_by` | for a record that existed before its entry |

  The unique constraints hold for every path that writes them — install, adoption, the NetBox and GLPI tools,
  and a second install running at the same time. The second writer fails, and its transaction is rolled back.
  Each install also takes a lock on its collection, so two installs of one collection queue rather than race.
  The record keeps its uid and key, and every existing reference, relation, document link and alias stays
  where it is. A label `catalogue-id` mirrors the id, so search and lookup find it like any other key.
- **Installed releases** are recorded per collection (`catalogue_installations`: collection, version,
  checksum, who, when, the preview's decisions), like `workspace_packages` for template packages.

### collection.yaml

```yaml
id: it-network                    # stable
version: 1.2.0                    # semantic; content changed without a new version is refused
name: IT network equipment
domain: it                        # it | accelerator | vacuum-cryo | safety | electrical | … (package ids)
owner: INFN ARGUS — network team  # who answers for it and reviews changes
license: CC-BY-4.0
requires:                         # the definitions its records need
  packages: {core-objects: ">=2.2,<3", it: ">=1.1,<2"}
  collections: {vendors: ">=1.0,<2"}
contents: [models.yaml]
```

### vendors.yaml

```yaml
vendors:
  - id: moxa
    name: Moxa Inc.
    aliases: [Moxa, MOXA Technologies]          # matched case- and suffix-insensitively (S.p.A., Inc., GmbH…)
    website: https://www.moxa.com
    country: TW
    sources:
      - {kind: netbox-devicetype-library, ref: device-types/Moxa, revision: 4f3c2a1}
```

### models.yaml

```yaml
models:
  - id: moxa/nport-5450
    vendor: moxa                                 # a vendor id
    model_code: NPort 5450                       # required: as the manufacturer writes it
    part_number: NPORT 5450
    name: Moxa NPort 5450 serial device server
    device_class: converter                      # required, one of DEVICE_CLASSES (§0.1)
    instance_type: Serial Converter              # the object type its units are (validated against packages)
    specifications:                              # typed, with units; the keys are reviewed per collection
      serial_ports: 4
      serial_interfaces: [RS-232, RS-422, RS-485]
      ethernet_ports: {count: 2, speed: 100M}
      power_input: {value: 12-48, unit: VDC}
      rack_units: 0
    datasheet_url: https://www.moxa.com/…/nport-5400-series-datasheet.pdf
    eol_date: null
    typical_spares: [power adapter]
    relations:
      - {verb: successor-of, model: moxa/nport-5410}
      - {verb: compatible-with, model: moxa/nport-5650-8}
    sources:
      - {kind: netbox-devicetype-library, ref: device-types/Moxa/NPort-5450.yaml, revision: 4f3c2a1}
      - {kind: datasheet, ref: "NPort 5400 datasheet v1.6", checked: 2026-10-30}
    retired: null                                # or {since: 1.3.0, reason: …, replaced_by: moxa/nport-6450}
```

**Never in a collection:** serial numbers, positions, prices, contract terms (a restricted class), people, or
anything about a site. A collection is read with the safe YAML loader and every key is checked, like a
package.

### Checking a collection

```
python -m app.catalogue validate                       # every collection shipped, together
python -m app.catalogue validate path/to/new-coll      # one being written, with the shipped ones
python -m app.catalogue validate --against <dir>       # and against the previous release (the last tag, checked out)
python -m app.catalogue list
```

A content file holds `vendors`, `models` and `moved` (tombstones, `{id, moved_to}`). The validator reports,
with file and place:

- unknown keys, so site data (a serial number, a price) has nowhere to go;
- ids that are not slugs, and a model id whose vendor part differs from its `vendor`;
- a vendor, an instance type, a relation target or a replacement that does not exist;
- an instance type that is abstract, or that comes from a package the collection does not require;
- the same id twice anywhere (including `former_ids`);
- two vendors whose names or aliases normalise to one company;
- two models with the same vendor and model code;
- a transfer stated on one side only;
- malformed specifications, sources, dates and addresses.

With `--against`, it also reports an entry that disappeared without being retired or transferred, a
collection that disappeared, and changed content without a newer version. `tests/test_catalogue_collections.py`
runs it on the shipped collections.

### What the Product Model type needs (core-objects 2.2, additive)

`part_number` (string, indexed), `instance_type` (string), `specifications` (text: the YAML block rendered as a readable table, the values also in `specs.*` search
fields), and `successor` (reference → Product Model). It also needs three relation verbs: `successor-of`,
`compatible-with`, `accessory-of`. All of this is additive, so no workspace needs a migration plan.

## 3. Install, preview, upgrade

A collection is a **ledger source**: a stream `catalogue:<collection-id>`, with one source revision per
released version (version and checksum). Its values are `stated` claims. This is what gives the rules the
requirement asks for, using the ledger's existing precedence:

### Which values Git manages, and which stay local

"Git is authoritative" holds only for the **managed fields** of an entry: on those, a new release updates the
record. Every other field is the workspace's. The ledger's ordinary precedence (`manual` over `stated`) is
not enough on its own: a record that existed before its entry may have every value already marked `manual`,
and then no release would ever update it. So the rule is explicit, and recorded per record
(`catalogue_entries.managed_fields`):

- **A record the collection created:** every field the collection states is managed.
- **A record adopted** (it existed before): the adoption step lists each field the entry states, with the
  record's value beside it, and an administrator decides field by field:
  - *managed* — the collection's value replaces the local one now and in later releases (the local value is
    kept in the history);
  - *local override* — the record keeps its value, and later releases do not change that field;
  - *propose to Git* — the local value is the correct one: it stays, and a correction entry is written for
    the collection (below). The field becomes managed once a release carries that value.

  The default for each field is *managed* when the values agree, and *local override* when they differ. An
  adoption without a decision for a differing field is not applied.
- **A managed field edited in ARGUS later** is not silently overwritten. The edit asks whether it is a
  local override (the field leaves the managed set) or a correction for Git (it is proposed back, and stays
  local until a release carries it).
- **A correction proposed back** is a review item that holds the YAML change for the entry (the collection,
  the entry id, the field, the old and new values, who and why). A maintainer downloads it as a patch and
  merges it through a normal Git review. When a release with that value is installed, the item closes and
  the field returns to managed.
- **Conflicts** then mean only one thing: a release changes a field that is a local override, or one with a
  correction still pending. The preview shows them, the record keeps its value, and they go to the review
  queue. A managed field is updated without a conflict.

### Removal, transfer and retirement

Absence from a collection never retires anything. Each entry's fate is stated:

- **Retirement** is explicit: `retired: {since, reason, replaced_by}` on the entry, which stays in the YAML.
  The record is marked retired in the catalogue, never deleted, and still offered while units point at it.
- **Transfer** to another collection is explicit too. The new collection carries the entry with
  `transferred_from: it-network`, and the old one keeps a tombstone, `{id: …, moved_to: timing-control}`. The
  install moves `catalogue_entries.collection_id` to the new collection, and the record, its id, its managed
  fields and its references stay unchanged. If only one of the two releases is installed yet, the entry
  stays with the collection it was in (status `transferring`) until the other one arrives.
- **An entry missing without either** blocks the release. The validator reports it against the previous
  release's snapshot: the entry must be retired, transferred, or put back.
- **Idempotent.** Installing the version already installed, with the same checksum, changes nothing. A change
  of content without a new version is refused.
- **One transaction** per release. Nothing is applied when any step fails.

The preview (`POST /v1/catalogue/collections/preview`) compares each entry with the records and, once every
decision is made, also runs the real installation and rolls it back (`trial: ok`, or why it would fail). It
lists, per record:

| Category | Meaning | Applied |
|---|---|---|
| add | a new vendor or model | by itself |
| change | a value the collection changed, and nobody changed locally | by itself |
| link | a local record that is the same product (same vendor + normalised model code, or an alias match) and has no catalogue id yet | by decision: link it (it gets the label, no new record) or create a separate one |
| duplicate | the release itself, or two collections, name one product twice | blocks the release (validator) |
| conflict | the release changes a local override, or a field with a correction pending | kept local, and queued for review |
| transfer | `transferred_from` here and `moved_to` in the other collection | the entry changes collection; the record does not change |
| retire | `retired:` set in this release | marked retired; if units use it, it is flagged and stays |
| missing | an entry neither retired nor transferred | blocks the release (validator) |
| unchanged | | — |

Upgrading uses the same comparison: the previous release's snapshot, the new release, and the records today.

## 4. In the shared catalogue workspace

- The records go into the catalogue workspace and are global. Every workspace can find and reference them,
  and only the catalogue workspace changes them.
- Search knows them by name, model code, part number, alias and catalogue id (`moxa/nport-5450`).
- **Local entries** are records made by hand, with no catalogue id. They work like any other record.
- **Promote to Git.** On a local entry, the action *Propose for the catalogue* writes the YAML entry, checks
  it with the validator, and opens a pull request on the catalogue repository. When that release is installed,
  the local record is linked by the `link` step: same uid, now with a catalogue id.

  **As built (2026-11-05).** `app/catalogue/proposals.py`: `draft` reads the entry from a Product Model of the
  catalogue workspace (vendor by its catalogue entry, else by name or alias, else a new vendor proposed with
  it); `build` writes the files against the repository's default branch — the entry inserted by id, a new
  collection's manifest, the collection's version raised once since the last release tag (two proposals raise
  it the same way, so they merge cleanly) — and runs `validate_tree` with them over the catalogue read now;
  `propose` opens the pull request with `ARGUS_GITHUB_TOKEN` (one commit on `argus/model-…`, its body naming
  the person) and keeps a `catalogue_proposals` row. Installing a release gives each open or merged proposal's
  entry a `link` decision to its record, the differing fields taking the release's (reviewed) values
  (`fields_default: managed`), and marks it installed. API: `GET/POST /v1/catalogue/collections/proposals`,
  `GET …/proposals/draft`, `POST …/proposals/preview` (maintainers; opening needs a signed-in person). The
  catalogue repository releases each merge by itself (`release.yml` there: validator, next version, CHANGELOG,
  tag).
- **A release pinned from Administration.** `app/catalogue/pins.py` and `catalogue_pins` (migration
  `b7d9f1a3c5e8`): a maintainer pins a newer release tag of a source the lock pins by tag; the tag's commit
  is read with `git ls-remote`, the catalogue it makes is checked with the validator against the one read now,
  and the pin is kept only if it passes. `sources.effective()` reads the stored pin over the lock while it is
  newer, so an ARGUS release that ships a newer lock wins. API: `GET …/releases`, `POST …/pin`,
  `DELETE …/pin/{source}`. Pinning installs nothing.

## 5. The UI

- **Catalogue page** (`/catalogue`): browse by domain → device class → manufacturer, filter by instance type and
  status (catalogue, local, retired), and search.
- **A model's page**: its values, with the source of each (the collection and version, or local, with who
  and when); its specifications; how many units in which workspaces (counts only, for workspaces the reader
  cannot see); its relations and successor; and its versions (the releases that touched it).
- **Catalogue updates** (catalogue workspace, administrators): the installed collections and their versions,
  the releases available, and the preview with decisions for `link` and `conflict`. It reuses the Packages
  page's preview pattern.

## 6. Export and reconcile the INFN shared Accelerator workspace

`python -m app.catalogue export --workspace <id> --out catalogue-export/` (run in the cluster by an
administrator; it only reads). It writes:

1. Candidate `vendors.yaml` and per-domain `models.yaml`: **portable**, with no Argus uid. The domain comes
   from the instance types of the units that use the model.
2. **An installation migration manifest**, `migration-<workspace>.yaml`, which never goes into the public
   collections. It maps each catalogue id to the existing record that adopts it (`moxa/nport-5450 →
   <record uid>`), and lists the duplicates to merge into it and the proposed field decisions (§3). It is
   specific to this ARGUS installation. It is kept with that installation's operations records, not with the
   catalogue, and is given to the install as a separate input.
3. **A migration report** (Markdown and CSV), one line per record, with:
   - the proposed catalogue id;
   - the duplicates (same normalised vendor and model code, or names an alias resolves to one product);
   - vendors that are only text (`vendor` with no `vendor_ref`);
   - models with no vendor or no model code;
   - every link that points at the record: units (`product_model`, `spare_for`), documents, relations and
     labels, with counts.

After review (merging the duplicates the report names and fixing what it flags), the curated collections are
merged in Git. Then they are installed **with the migration manifest**. An entry the manifest maps is linked
to its existing record (a `catalogue_entries` row, and the field decisions applied), not created. Any other
installation of ARGUS installs the same collections without a manifest, and gets new records. A duplicate is merged with the ledger's existing merge,
which keeps the survivor's uid and redirects the merged record (`merged_into_uid`, aliases). So every
existing link still resolves, and the report's link counts are checked again after the install.

## 7. NetBox Device Type Library

`python -m app.catalogue netbox --library <checkout> --revision <sha> --select "Moxa/*" "Cisco/C9200*"`

It reads a local checkout of `netbox-community/devicetype-library` (or an INFN fork) at a pinned commit, and
only what is selected. It writes collection YAML for review: it never writes to the database. The mapping:

| NetBox | Argus |
|---|---|
| `manufacturer` | vendor id (an existing one through its aliases, otherwise a new entry in `vendors.yaml`) |
| `slug` | model id `vendor/slug` |
| `model` | `model_code`, `name` |
| `part_number` | `part_number` |
| `u_height`, `is_full_depth`, `airflow`, `weight` | `specifications` |
| `interfaces`, `console-ports`, `power-ports` | counts and kinds in `specifications` |
| `comments` | kept in `sources[].note` |
| file path and commit | `sources: [{kind: netbox-devicetype-library, ref, revision}]` |

Argus metadata — `device_class`, `instance_type`, spares, EOL and successor — is written on the
Argus side of the entry, and a later NetBox import never overwrites it. The library's own licence is
recorded in the collection's sources, and should be checked before redistribution.

## 8. GLPI as a source of installed devices

A GLPI sync already makes the units. A new step proposes, for each unit with no `product_model`, the
catalogue model its GLPI manufacturer and model name match: the normalised vendor alias plus model code or
part number, exact first, then a near match with its score. The proposals are `resolved` claims on the review
queue, and a person accepts them. A GLPI model that matches nothing is listed as a candidate for a new local
entry.

### §8 as built (R4)

- `app/catalogue/glpi.py`; `POST /v1/catalogue/glpi-matches` (update on objects in the workspace) runs it for the
  current workspace, `GET` lists what nothing matches; the Product catalogue page has the button and the list.
- Units: those with `argus_source: GLPI` and GLPI's `manufacturer` and `model`. Models: the catalogue
  workspace's live Product Models with a model code or part number; a vendor matches by its name or any alias
  (the `alias` labels the install writes), legal-name words aside.
- **Exact** (score 1): the same vendor, and the model code or part number, case, spaces and punctuation aside.
  **Near**: the same vendor and a code at least 85 % alike (score 0.9 × ratio), or the code inside GLPI's model
  text (0.8). Two equally good models: no proposal, reported as ambiguous.
- Each proposal is an `attr:product_model` claim, method `inferred`, rule `match.glpi_model/1` (locked in
  `rules.lock.json`), from the stream `catalogue-match:<workspace>`, with GLPI's text, the catalogue id, the kind
  and the score as evidence. `inferred` is advisory, so nothing is set until a person accepts it in the review
  queue (Facts to confirm), where it reads "is a Moxa NPort 5450 — GLPI says Moxa / NPORT-5450, exact match".
  A rejection is remembered: the same proposal does not come back.
- A unit whose model someone set is never proposed over; one whose model is the accepted match keeps its
  claim on every run, so accepting is never undone by the next run.
- Not tried on the local copy of production: it has no GLPI units. The tests use GLPI-like units.

### R5 as built

- **Corrections as patches** (`app/catalogue/corrections.py`, `GET /v1/catalogue/collections/corrections`, and
  *Download the corrections as patches* on the collections page): every open correction becomes a change of the
  file its value is written in, at the pinned commit — an Argus-native entry's key; a NetBox model's `model:`
  in its device type; its device class, end of life or spares in its `classifications` entry (added when there is
  none). Only the changed lines move; the result is one unified diff per repository for `git apply`. A field a
  source's format has no place for is listed with the reason.
- **Administrator documentation**: the user guide's topic *The product catalogue*
  (`backend/app/help/guide/168-product-catalogue.md`), also found by Ask ARGUS.
- **Upstream**: the fork's branch `basler-cameras` is NetBox's master plus the three Basler device types only,
  ready for a pull request to `netbox-community/devicetype-library`, which is opened only with the owner's
  go-ahead.

## 9. Stages

| Stage | Content | Changes records? |
|---|---|---|
| S0 | read-only inventory of production (`scripts/catalogue_inventory.py`); the format and collection boundaries revised with its evidence | no |
| S1 | format, validator (`python -m app.catalogue validate`), core-objects 2.2 (additive), initial collections (vendors; it-network, it-compute; accelerator-power, accelerator-diagnostics, vacuum), docs, tests | no |
| S2 | `catalogue_entries` and `catalogue_installations` (unique catalogue id and record, collection lock); install, preview and upgrade through the ledger; managed fields, local overrides and corrections; transfer and retirement; API; tests for idempotence, upgrades, conflicts, transfers, concurrent installs and reference preservation | only when an administrator installs |
| S3 | catalogue page, model provenance, updates review | no |
| S4 | export (portable YAML, installation migration manifest, report); adoption with field decisions | report: no. Adoption: on install |
| S5 | NetBox selected import (to YAML); GLPI match proposals (to review) | no / reviewed only |
| S6 | local entry → promotion item → YAML for Git | no |

### S2 as built

- **API** (catalogue workspace): `GET /v1/catalogue/collections` (shipped, valid or not, installed version,
  history), `GET /v1/catalogue/collections/entries` (`needs_review=true`: conflicts and corrections),
  `POST …/preview` and `POST …/install` with `{collections, decisions}`. Reading needs read on objects there;
  preview and install, the workspace's owner or an administrator.
- **Decisions**, per catalogue id: `{action: link | create, record_uid?, fields: {field: managed | local |
  propose}}`. `record_uid` names the record when the match is not found — the hook the migration manifest
  (S4) uses. A field whose values agree, or that is empty on the record, needs no decision: it is managed.
- **Writes** go through the ledger as the administrator, with `catalogue <collection> <version>` as the
  reason. A collection is a stream of the ledger only in this sense: precedence is replaced by the explicit
  managed-field rule (§3), so no `stated` claims are needed to decide which value wins.
- **Matching** a link candidate: the same vendor (its record, or a name or alias) and the same model code —
  or, for a record with no code, the code found inside its name ("TPG 366 control unit"), when exactly one
  record has it. A `+` counts (Libera Brilliance ≠ Libera Brilliance+). A candidate is always a person's
  decision.
- **Refused:** a collection that does not validate; the same version with other content; an older version;
  a package the collection requires missing or out of range. Locally, `accelerator-infn` has `core-objects`
  2.0.0, so the collections (≥2.1) wait for that upgrade.
- **Not stored yet:** `part_number`, `instance_type`, `specifications` and `relations` have no field on the
  Product Model type; the preview counts them, and they are written once core-objects 2.2 adds the fields.
- **Not yet:** the corrections' download as a patch is S6.

### S3 as built

- **Product catalogue** (`/catalogue/models`, `GET …/models`): search by name, key, code, vendor or catalogue
  id; filters by device class, vendor, source (from a collection, local, retired) and collection, with counts;
  units per model; a mark on models waiting for review.
- **A model's page** (`/catalogue/models/:uid`, `GET …/records/{uid}`): each value with its source — *from
  the collection*, *edited here*, *local override*, *proposed to Git*, or the record's own — the collection's
  value beside any that differs, a release conflict with the value it kept; what the collection states that
  the type cannot hold yet (specifications); related models; units per workspace, by name only where the
  reader may read (the rest as "other workspaces"); sources; and the collection's releases.
- **Deciding a field after the install** (`POST …/entries/{catalogue id}/fields`, owners and
  administrators): *managed* (writes the collection's value), *local* or *propose*. It resolves a conflict.
- **A managed value edited here** is not intercepted in the record's edit form. It shows as *edited here* on
  the model's page and in the review queue, where a person says what it is; until then, the next release
  treats it as a conflict and keeps it. Asking in the edit form itself is left for later.
- **Catalogue collections** (`/catalogue/collections`): the shipped collections, invalid ones not offered,
  installed versions and upgrades; preview, with each link decided (link or create, and every differing
  field) before *Install* is enabled; the trial's failure if any; the review queue; the history.

A dry run on the local copy of the production data: 15 entries → 9 links (6 vendors; NPort 5450,
TPG 366, 4UHV) and 6 additions, every link offered for a decision, and the trial installation passing.

### S4 as built

- `python -m app.catalogue export --workspace <id> --out <dir>` (`app/catalogue/export.py`) reads in a
  read-only transaction and writes `collections/<id>/models.yaml` (and `vendors/vendors.yaml`) with the
  candidate entries, a draft `collection.yaml` for a collection that does not ship yet,
  `migration-<workspace>.yaml`, `report.md` and `report.csv`. The candidates are validated together with the
  shipped collections before anything is written, and the report says what the validator would refuse.
- **What becomes of a record:** *export* (a new entry), *link* (a shipped entry is the same product: same
  vendor, and the same code or the code inside its name), *merge* (a duplicate: same vendor and code as
  another; the one with most units survives), *skip* (no vendor; a company's name; synthetic demo data), or
  *already* (has a catalogue id).
- **What an entry takes:** name, vendor, model code (proposed from the name when empty, flagged to confirm),
  device class (spellings merged to the list: `switch` → `network switch`, `host` → `server`, `chassi` →
  `chassis`, `controller motor` → `motion controller`), datasheet, firmware, end of life, the instance type of
  its units when the collection requires that type's package, and an `argus-export` source. **Descriptions are
  not exported**: what they hold today is manufacturers' text and sellers. They stay on the records.
- **The collection** follows from the units' type (Motor Axis → `motion`, Turbo Pump → `vacuum`, …), else from
  the device class. New collections proposed: `motion`, `it-compute`, `accelerator-rf`, `timing-control`.
- **The manifest** holds, per catalogue id, the record (uid and key) and the field decisions: `vendor` and a
  cleaned device class *managed*; a field where the record differs from a shipped entry *local*. It also holds
  the duplicates to merge, the values that stay local, and the references counted per entry.
- **Installing with the manifest** (`manifest` in `POST …/preview` and `…/install`, or a file on the
  collections page): its decisions, under any made on the page; the duplicates merged with the ledger's merge;
  then units and document links counted again, through the merged records' redirects. Fewer than the export
  counted, and nothing is installed. Relations are not compared, since a merge rightly folds two identical
  edges into one.
- **A dry run on the local copy of the production data:** 172 records → 141 exported, 9 matched shipped entries,
  1 duplicate vendor (`INSTRUMENTATION TECHNOLOGIES DD`), 21 skipped (no vendor: among them `Hi Scroll 6` and
  `Micro pusher MP21`, with 17 and 18 units, which need a vendor first). With the candidates merged into the
  collections, the install with the manifest linked 150 entries, created 6 (shipped drafts with no record),
  merged the duplicate, and lost no reference. It was rolled back.
- **Not done:** a merged duplicate's units still name it (it redirects); they are not rewritten to the survivor,
  so unit counts on the catalogue pages count the survivor's own units only.

**Outside the first release:** opening the Git pull request automatically; fetching an external catalogue
repository at runtime (the first release reads collections shipped with the release, and an INFN fork is used
through the NetBox tool and Git review); Equipment Port templates generated from NetBox interfaces; images and
front panels; signing releases; more than one shared catalogue workspace.
