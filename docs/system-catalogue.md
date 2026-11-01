# The system catalogue

Status: **proposal, for approval** (2026-10-31). Follows docs/catalogue-collections.md.

## Decision

The shared catalogue of commercial models — Vendors and Product Models, for every domain — is the
**installation's**, not a workspace's. Administrators install, upgrade and maintain it from *Administration ›
Catalogue*; every workspace reads it; workspaces keep their installed units, which point at its models.

It is **one** catalogue holding a collection per domain (IT, accelerator, vacuum, motion, timing, power, civil,
plant…), not one catalogue per domain: a vendor (Siemens, Schneider, Pfeiffer) spans domains, and separate
catalogues would duplicate it. A workspace is offered the models of the domains its packages cover.

Site data — maps, buildings, rooms, the beam model — is an installation's own and stays in workspaces and
packages' map layers. The civil and plant collections hold *products* (a door, a fire damper, an access
reader, a chiller), not places.

## What is there today (measured on the local copy of production)

- The catalogue is the workspace `accelerator-infn` ("Acceleratori-INFN"), found by
  `catalogue_workspace()` as *the workspace holding the global Asset type*: a guess, not a setting.
- It already holds **only catalogue records**: 131 Product Models and 41 Vendors, all `is_global`, and no
  installed units of its own.
- It holds the **shared accelerator types** too: 144 global types, which the beamline workspaces `btf`, `eli`
  and `sparc` hang from (scope `beamline`, `catalogue_workspace_id: accelerator-infn`, on 21 package records),
  and 78 of its own (36 object types, 22 ticket and 20 document types).
- **350 units** in other workspaces point at its models (`product_model`).
- Type uids embed the workspace id (`type_uid(workspace_id, name)`), and record keys its key prefix
  (`ACCELERATOR-INFN-PM-0121`).

So the data is already where it should be. What is wrong is everything around it: the catalogue is an
ordinary-looking workspace with an accelerator name, picked by a heuristic, managed from that workspace's pages
and through its roles, and nothing stops it being deleted, transferred or filled with units.

## Therefore: designate in place, do not move

Moving 172 records, 144 shared types and the 3 beamlines hanging from them to a new workspace would rewrite
type uids, every reference to them, 350 units' model links and 21 package records — a large, risky migration
whose only gain is a different id. Instead the existing workspace becomes the **system catalogue**: marked as
such, protected, hidden from the ordinary workspace list, and managed from Administration. Its id and keys stay
(`accelerator-infn`, `ACCELERATOR-INFN-…`); its display name can be changed to "ARGUS catalogue" by an
administrator. Nothing is moved, so nothing breaks, and the pending install (docs/catalogue-collections.md,
step 4) can go ahead in it as planned.

## Stages

Each stage is reviewable on its own, with tests and the administrator guide updated.

### C1 — The catalogue is a setting, and protected

- `workspaces.role`: `catalogue` for exactly one workspace (a unique partial index). The migration sets it on
  the workspace `catalogue_workspace()` finds today; an installation without one gets none until an
  administrator designates it.
- `catalogue_workspace()` reads the setting; the heuristic is gone.
- The catalogue workspace refuses: deletion, transfer and export as a workspace bundle, being made to hang from
  another, and records other than Vendors and Product Models (units belong in workspaces; a clear error says
  so). Its shared types are managed as today, by its packages.
- `python -m app.catalogue status` (read-only): which workspace is the catalogue, what it holds by type, any
  record that is not a Vendor or Product Model, the workspaces hanging from it, the units pointing at its models
  and its collections' versions.

**As built.** `workspaces.role` with a unique partial index (migration `c3d5e7f9a1b2`, which marks the
workspace holding the global Asset type — by most shared Product Models when several do);
`app/catalogue/system.py` (`designated`, `is_catalogue`, `refuse`, `check_record`, `designate`,
`designate_if_none`, `status`, and a `before_flush` guard that refuses any other record created in or retyped
into the catalogue, whatever writes it); the refusals in the assets, workspaces, transfers, bundles routers and
the package installer (which also designates the first workspace given the global scope when none is);
`GET /v1/admin/catalogue` and `POST /v1/admin/catalogue/designate` (administrators). The equipment classes'
monthly notice goes to the designated catalogue. On the local copy of production the migration designated
`accelerator-infn`: 131 Product Models and 41 Vendors, nothing else, 144 shared types, `btf`, `eli` and `sparc`
hanging from it, 272 units in `euaps` pointing at its models.

### C2 — Administration › Catalogue

- One administrators' page for the catalogue: its collections and their upgrades (preview, decisions, install —
  the Collections page, moved), the pinned sources, the product catalogue (browse, provenance, review), the
  corrections to send back to Git, and the history.
- GLPI matching moves there too, with the IT workspace to match chosen on the page.
- The catalogue workspace leaves the workspace switcher for everyone but its maintainers; links to a model
  still open its record wherever they are followed.

**As built.** `/admin/catalogue` (webapp/src/pages/admin/Catalogue.tsx): the catalogue workspace's status
(`GET /v1/admin/catalogue`), designating one when there is none, the collections page embedded, and GLPI matching
for a chosen workspace (`POST /v1/catalogue/glpi-matches` with that workspace's header). `/catalogue/collections`
redirects there and leaves the app's navigation; the product catalogue keeps browsing for everyone and links to
the administration page for administrators. The workspace lists carry `role`, and the switcher offers the
catalogue workspace only to those who can modify it.

### C3 — Catalogue maintainers

- A catalogue maintainers list on *Administration › Catalogue*: who may edit Vendors and Product Models, decide
  the catalogue's review queue and install collections. Everyone can read. Under the hood it is the catalogue
  workspace's own roles, managed from that page, so the permission checks do not change.

**As built.** `system.may_maintain(user)`: an administrator, or anyone with full control of the catalogue
workspace's objects (its Curators and Owners). It guards installing, deciding and correcting
(`catalogue_collections._may_install`, which tokens with admin scope on the catalogue workspace also pass) and
`GET /v1/admin/catalogue`; reading the catalogue needs no grant. `GET /v1/me` says `catalogue_maintainer`, and
Administration shows *Catalogue* to maintainers who are not administrators. The Maintainers section lists and
grants Curator and Owner on the catalogue workspace through the existing role bindings (administrators).

### C4 — Models by domain

- A workspace's model picker offers the models of collections whose domain is among its packages (an IT
  workspace: the IT devices; a beamline: accelerator, vacuum, motion, timing, power), plus local models, with a
  "show every model" switch. Nothing is hidden from search or from a unit that already points at a model.

**As built.** The proposal assumed a collection's `domain` already named a package; it did not — every
collection said `catalogue`. So: `domain` is one package id, a list of them, or `catalogue` (every workspace),
checked by the validator (`Collection.domains`); each installation keeps the collection's domains
(`catalogue_installations.domains`, migration `d4e6f8a0b2c3`), so offering models never reads Git; an
installation made before has none and is offered everywhere, as before. `system.offered(workspace)` and
`GET /v1/catalogue/collections/offered` list the models a workspace is not offered by default; the picker of a
reference to Product Model hides them behind *Show every model (n more)*, never the unit's own value. GLPI
matching still considers every model: a match in another domain is caught by its review. The NetBox-sourced
collection is `it-devices` 0.1.1, domain `it` (sources.lock.yaml). The domains of the Argus-native collections
are set in argus-catalogue (accelerator-diagnostics, accelerator-power, accelerator-rf, timing-control:
accelerator; motion: accelerator and optics-alignment; vacuum: vacuum-cryo; it-classification: it), released as
v0.2.0 after this ARGUS release, then pinned here.

### C6 — Not a workspace to the people using it

After C1–C4 an administrator could still switch into the catalogue and meet it as a workspace named
"Acceleratori-INFN". Now: it is listed in no one's switcher (only while it is the current one); a record is
edited in its own workspace (`assetsApi.update(…, workspaceId)` sends the record's workspace, so a maintainer
edits a catalogue model from anywhere, its permission checked in the catalogue); *Administration › Catalogue*
renames it (the id and keys stay), names any record that does not belong in it (`status.other_record_list`), and
offers administrators "open the catalogue as a workspace" for cleaning those up.

The 144 shared types it holds are the whole shared object type tree (locations, IT, vacuum, cryogenics, safety,
optics and lasers, RF, cables, control items, and Catalog Item with Vendor and Product Model), not accelerator
types: the beamlines' own types (magnets, monitors) are in each beamline.

### C7 — One type tree, with where each type comes from

The type tree beside the lists split the workspace's own types from the "Shared by other workspaces" ones, so a
beamline's own types (magnets, monitors) sat detached from their parents in the catalogue, and a self-contained
workspace saw its own copy of a package type and the catalogue's apart. Now it is one tree of every type the
workspace can use; a type of the same name kept in two places (the workspace's copy of a package type and the
catalogue's) is one node, its records counted and filtered together (`typeFamily` follows same-name types). Every
type says where it comes from (`origin` on the type list and a type's page, app/packages/origin.py): the
package and the version its workspace has, an import (its source), or made in a workspace — shown on hover,
when selected, and on the type's page; imported and other workspaces' own types carry a small mark.

### C5 — Production

1. Deploy C1 (the migration only adds the setting and marks one workspace); run `python -m app.catalogue
   status` (read-only) and review it: the catalogue designated, holding Vendors and Product Models only.
2. Deploy C2–C4. The pending install of the collections, with the migration manifest, runs from
   *Administration › Catalogue*.

## Not in this proposal

- Renaming the workspace id or record keys (cosmetic, and every key printed on a label or in a document would
  break).
- Splitting the shared accelerator types out of the catalogue workspace: they are definitions, managed by
  packages, and the beamlines hang from them as they do today.
- More than one catalogue per installation.
