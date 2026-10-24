---
title: Workspace bundles and demo workspaces
summary: Copy one workspace into a new one, here or on another ARGUS, as a readable ZIP — and install the two synthetic demo workspaces, IT Services and Medium Linac Facility.
keywords: [bundle, workspace bundle, clone, copy workspace, duplicate, template, demo, demo workspace, sample data, example, IT Services, Medium Linac Facility, linac, synthetic, guided tour, start exploring, zip, export workspace, import workspace, preview, dry run]
order: 132
---

A **workspace bundle** is one workspace as a folder of JSON Lines files and the files they name (floor plans,
attachments, icons), zipped. Importing it **clones it into a new workspace**: on this ARGUS or on another one
that has the same domain packages.

It is not the signed portable archive (**Export and import**): the archive moves a whole installation with its
evidence ledger, signed and verified; a bundle copies one workspace's current content, readable by a person.

Bundles are for **instance administrators** only: **Administration → Portability → Workspace bundles**.

## What a bundle carries

Records with their attributes, history, comments and labels; relations; places, floors, floor plans and where
records stand on them; outlines, routes and positions on the map; tickets with comments, history and links;
documents with revisions and attachments; activities and series; beam models with their values and bindings;
the workspace's own types and icons; the people the records name (by e-mail).

**Never carried:** passwords, API keys and tokens (an AI endpoint or saved import arrives switched off, asking
for its credential); the evidence ledger (use the signed archive); assistant conversations; the search index
(index again under Administration → AI). The preview lists everything that is not carried, with the reason —
nothing is left out silently.

## Export a workspace

1. **Administration → Portability → Workspace bundles → Export a workspace**: choose it, **Export**.
2. **Download ZIP**. The ZIP is `<workspace>.argus-workspace.zip`.

## Import a bundle

1. **Import a bundle**: choose the ZIP. It is unpacked safely and its checksums are checked; nothing is imported.
2. **Install as a new workspace…**: give the new workspace's **id** and **name**.
3. Tick **Give the bundle's people their access** to recreate their memberships and roles; otherwise only you
   (as owner) can open it, and you add people afterwards.
4. **Preview** — a dry run: what would be added, identifiers renamed because they are in use here, people
   matched or added, and anything that blocks it (a missing or changed file, a package this ARGUS does not have
   at the same version, a broken reference, malformed geometry). Nothing is written.
5. **Apply** — all or nothing. **Open** the new workspace.

A bundle always makes a *new* workspace: importing into an existing one is refused, and importing the same
bundle twice gives two independent copies.

## The demo workspaces

Two fictional workspaces ship with ARGUS, under **Demo workspaces**:

* **IT Services** — Northfield IT Services: a service catalogue (network, internet, Wi-Fi, mail, DNS, hosting,
  storage, backup, monitoring, service desk, VPN), three buildings with floor plans, racks and the equipment in
  them, dependencies, incidents, requests and changes, runbooks, contracts and SLAs.
* **Medium Linac Facility** — the Valmora Linac Laboratory: a site map, the accelerator building with its
  bunker and klystron gallery, utilities, administration, radiation areas, a beam model from the gun to the
  dumps bound to its physical units, RF, power, vacuum, cooling, controls, procurement, documents and issues.

**Install as a new workspace…**, **Preview**, **Apply**. Their cockpit opens with **Start exploring**: a few
steps from the map to a building, a rack or the bunker, a record, its dependencies, an issue, planned work and a
document. Every page of a demo workspace says it is **synthetic**: the organisations, people, figures and
procedures are invented, and nothing in them is operating, safety or radiation-protection guidance.

## From the command line

On the API server: `python -m app.bundle export <workspace> <folder>`, `python -m app.bundle zip <folder>
<file.zip>`, `python -m app.bundle preview <folder|zip> --workspace <id> --name <name>` and `… import …`.
