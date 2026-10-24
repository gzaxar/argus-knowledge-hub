# Workspace bundles

A **workspace bundle** is a directory — or the same directory as a ZIP — holding one workspace as people use it:
its settings, its packages (exact versions and checksums), its type customizations, records, history, documents,
files, activities, map and indoor plans. An instance administrator exports one, previews an import, and clones it
into a new workspace of the same or another compatible installation. The two demo workspaces
(`backend/demo_workspaces/it-services`, `backend/demo_workspaces/medium-linac`) are bundles kept in version control
and installed by the same import.

It is not the **signed portable archive** (docs/portability.md), which stays as it is. Use each for its purpose:

| | Workspace bundle | Signed portable archive |
|---|---|---|
| What it is for | cloning a workspace; demo and training workspaces; moving one workspace to another installation | backups, audited transfers between installations, restore drills, chains of incremental exports |
| What it holds | one workspace's current records and their history, files, map, plans, activities, templates | one or more workspaces including the evidence ledger (claims, decisions, provenance) with its sequence |
| Proof | checksums of every file in the inventory | Ed25519 signature, watermark vector, ledger replay |
| Who | instance administrators | the approval workflow of the archive (request, approve, sign) |
| Form | an inspectable directory (JSON Lines, files by hash) or its ZIP | a signed, compressed archive, optionally encrypted |

## Coverage of the existing archive (what this closes)

The signed archive (`app/portability/families.py`) is an allow-list of 51 tables. An inventory of every table
holding workspace data (`workspace_id`, or a record's `asset_uid`, `document_uid`, `issue_uid`) found **38 that
it does not carry**, among them everything added after it was designed:

- activities, recurring activity series and their workspaces (`activities`, `activity_series`, `activity_workspaces`);
- document templates, their versions and the record of documents generated from them (`document_templates`,
  `document_template_versions`, `document_generations`);
- the map: positions, routes and outlines (`spatial_features`), field observations (`location_observations`);
- indoors: floors (`place_levels`), floor plans and their files (`floor_plans`), placements (`indoor_placements`);
- the packages a workspace has, with versions and checksums (`workspace_packages`, `package_installations`);
- smaller workspace state: equipment-class requests, AI suggestions waiting for review, access reviews,
  escalations, golden incidents, import snapshots (the baseline that keeps people's edits on re-import), record
  followers and notification subscriptions, the AI endpoint and saved imports (without their secrets).

An export of the archive succeeds without them: they are simply not in its allow-list. The bundle's registry
(`app/bundle/registry.py`) is checked by a test against every table of the database: a new table must be placed in
the bundle, rebuilt on import, or listed as not carried with its reason, or the test fails.

## What a bundle carries, rebuilds, and leaves out

**Carried** (each table one `records/<family>.jsonl`): the workspace's settings; its packages; its own types and
icons (with files), global values, ticket workflows; the people its records name (id, e-mail, name — never
credentials) and, optionally applied, its memberships, role bindings, subscriptions and followers; assets with
comments, history, labels, external ticket references, relations and import snapshots; tickets with comments,
history, links, watchers and escalations; documents, revisions, relations, attachments (with files), templates,
their versions and generations; activities, series and their other workspaces; positions, routes, outlines,
observations, floors, floor plans (with their pictures and source files), indoor placements; the beam model, its
values and asset bindings; equipment-class requests, AI suggestions, access reviews, review escalations, golden
incidents.

**Carried without secrets, to be completed after import** (the manifest's `external_config`): the AI endpoint
(`llm_configs`, key removed, switched off until checked), saved imports (`import_configs`, credential removed,
schedule off), and the map's background tiles (an installation setting, `VITE_MAP_TILES_URL` /
`ARGUS_MAP_TILES` — a reference; floor plans and other uploaded map content are files of the bundle).

**Rebuilt on import:** the package installation history (the packages are installed), ticket–equipment links
derived from tickets (`ledger_ticket_links`), the search index (Ask ARGUS indexes the workspace again).

**Not carried, each named in the export's and the import preview's `not_reproduced` with its reason:**
the evidence ledger (streams, source revisions, claims and their events, decisions, fact state, conflicts,
migration domains and maps, policies, rulesets, bulk changes) — it keeps the source installation's sequence and
proof: move it with the signed archive; records of migration runs (`catalogue_mappings`, `legacy_migration_plans`,
`transfer_jobs`, `import_jobs`) — their results are the records; assistant conversations and feedback — personal;
AI intake runs, outcomes and model profiles — evaluations of the source installation's models; API tokens,
devices, uploads in progress, idempotency records, notifications, usage figures — runtime or secret; the archive's
own tables; instance settings.

## The format (version 1)

```
manifest.json                 what the bundle is, where it came from, packages, inventory, limitations
records/<family>.jsonl        one JSON object a line, sorted by key: the rows of a table
files/<sha256[:2]>/<sha256>   file contents by hash (attachments, plan pictures and sources, icons)
```

`manifest.json`:

- `format` `"argus-workspace-bundle"`, `format_version` `1`;
- `created_at`, `created_by`, `source` (instance id, ARGUS version, database schema revision);
- `workspace` (its id and name in the source), `demo` (for a demo: title, description, tour);
- `packages` — `[{id, version, checksum}]`, installed in this order;
- `families` — `{name: {file, rows, sha256}}`;
- `files` — `[{path, sha256, size}]`: every file of the bundle except the manifest;
- `external_config`, `not_reproduced`, `missing_files` (a file a record names but the source did not have).

A row keeps its columns as in the database, with dates in ISO 8601 and geometries as GeoJSON; a column holding a
stored file is replaced by `{"$file": "<sha256>"}`; integer keys that only number rows are left out (the target
numbers them), except a field observation's, which a position may name (it is re-mapped).

## Import

1. **Read and check, before writing anything:** the format version; every path safe (relative, no `..`, no links,
   inside the bundle) and every ZIP member within size and count limits; each file's size and SHA-256 against the
   inventory, and no file outside it; each family's columns against this installation's.
   While loading, inside the transaction that a preview rolls back: every reference (a revision's document, an
   attachment's record, a placement's plan…) to a row of the bundle or of the target, every geometry (its kind
   for its role, WGS 84, valid for PostGIS), every file a row names present in the bundle.
2. **Packages:** each must be available in the target at the same version and checksum; anything else is a blocker.
3. **Preview (dry run):** what will be added, what is renamed and why (an identifier, an asset key or a document
   code already used in the target installation), people matched or created, dependencies outside the bundle and
   whether the target has them, what cannot be reproduced, what must be configured afterwards. Nothing is written.
4. **Apply — clone into a new workspace:** in one transaction, the workspace is created with the new id and name,
   the packages installed, then the types and records loaded in reference order; files are stored and checked
   again. Any failure rolls everything back.

**Identifiers.** A row keeps its identifier when the target does not use it. One the target uses already (a second
clone into the same installation) becomes `uuid5(<new workspace id>, <old identifier>)`, and every reference to
it — columns, JSON attributes, links in Markdown bodies — follows. Workspace-scoped identifiers
(`<workspace>:argus-object:pump`) take the new workspace id. Asset keys and document codes, unique in an
installation, keep their value when free and become `<value>-<new workspace id>` when not. The same bundle cloned
into the same target state therefore gives the same identifiers: repeated imports are deterministic.

**References outside the bundle.** A relation to a record of another workspace, or an activity shared with
another workspace, is listed in the manifest's `dependencies` at export. On import, one the target has is kept;
one it lacks is skipped and reported under *not reproduced*. A reference that is neither in the bundle nor
declared is a broken bundle and blocks the import.

**Repeating an import** into a workspace that exists is refused (clone needs a new workspace id). Importing into an
existing workspace is not offered in this version: its conflict rules (which side wins for each field, what a
deletion means) are a separate design.

**People.** A person the bundle names is matched in the target by e-mail; one not found is created as a person
without administrator rights, who has access only through the memberships, if they are applied, and signs in
through the installation's identity provider. Memberships, role bindings, subscriptions and followers are applied
only when the administrator ticks *Apply people's access*.

## Who

Exporting, downloading, previewing and applying a bundle is for authenticated instance administrators
(`is_admin`), checked by the API. Each action is recorded in the audit trail (`portability_events`, subject
`bundle-export` or `bundle-import`): the actor, the source, the format version, the validation result and the
outcome.

## Demo workspaces

`backend/demo_workspaces/<name>/` holds the demo workspaces as bundles (the same format, unzipped, under version
control). They are installed only through this import — **Administration → Portability → Workspace bundles →
Demo workspaces**, or `python -m app.bundle import backend/demo_workspaces/<name> …` — never by seed code or SQL.
The manifest's `demo` section holds the title, the synthetic-content notice and the guided tour; on import it
is stored for the new workspace (`app_settings`, `demo.tour.<workspace>`, its links following renamed records)
and served by `GET /v1/workspaces/{id}/tour`, which the cockpit shows as **Start exploring** and every page as a
*synthetic demo* strip.

* `it-services` — Northfield IT Services (fictional): 107 records (11 services with an `IT Service` type of the
  workspace, buildings, rooms, 9 racks, switches, firewalls, routers, hypervisors and virtual machines, storage,
  UPS, cooling, access points, VLANs, contracts, licences, purchase orders), 117 relations, 4 floor plans and
  47 placements, 52 map shapes (outlines, fibre routes), 12 tickets, 10 documents (architecture with a diagram,
  runbooks, SLA, CAB minutes, maintenance and survey reports), 10 activities and series, 4 people.
* `medium-linac` — Valmora Linac Laboratory (fictional): 304 records across accelerator, civil, safety,
  electrical, HVAC, vacuum, optics, plant, hydraulic, administration and IT; a beam model (gun → 4 accelerating
  structures → diagnostics → main dump, with a spectrometer branch: 31 positions on 2 paths — magnets,
  correctors, monitors, a Faraday cup, sector valves — design values in the machine's own frame) bound to the
  physical units placed on the bunker plan at their beam positions; a motion controller with motor axes for the
  screens, the spectrometer slit and the laser mirror, and pneumatic actuators; cameras and BPM electronics;
  PBS codes in the demo's own `ZONE-SYSTEM-FAMILY-TYPE-NNN` scheme, 12 work packages, 7 machine modules and 5
  sections; 16 utility requirements (power, cooling water, air, compressed air, nitrogen) linked to their
  consumers and to the services that meet them — cooling water skid, compressed air, nitrogen, low-voltage
  distribution; 706 relations; 4 plans, 154 placements, 161 map shapes; radiation, fire and access areas
  described without limits or settings; 13 tickets, 13 documents, 13 activities and series, 5 people.

People are fictional, at `.example` domains. To change a demo, edit its workspace in an ARGUS, export it with
`python -m app.bundle export <workspace> backend/demo_workspaces/<name> --demo <tour.json>` and commit the
result; `tests/test_workspace_bundles.py` checks it installs, round-trips, and renders.

## Limits of version 1

* Import makes a new workspace; merging into an existing one is not offered.
* The evidence ledger is not carried: a beam model arrives with its records, values and bindings, but its
  ledger streams and decisions do not (reported under *not reproduced*). Importing the model again in the new
  workspace starts a fresh ledger history for it.
* The meaning-search index is rebuilt on the target with its own embedding model, not copied.
* Map tiles, AI endpoints and saved imports' credentials are the target's to configure (reported under
  *set up on the target*).

## Tools

`python -m app.bundle export <workspace> <directory>` writes a bundle; `python -m app.bundle zip <directory>
<file.zip>` packs it; `python -m app.bundle preview <directory|zip>` and `python -m app.bundle import
<directory|zip> --workspace <id> --name <name>` read and apply one, as the API does.
