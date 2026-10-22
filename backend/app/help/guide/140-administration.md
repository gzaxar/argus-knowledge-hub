---
title: Administration and the production installation
summary: The administration pages, the production installation (addresses, sign-in, releases, the mobile app's distribution), backups, and where operators find the details.
keywords: [administration, statistics, storage, disk, disk space, free space, occupancy, quota, volume, usage, tokens used, active users, concurrent users, feedback, package, packages, it, electrical, hydraulic, hvac, plant, domain, template, workspace template, catalogue package, accelerator catalogue, core facility, admin, settings, workspace identifiers, users, production, deployment, release, version, argo cd, keycloak, kubernetes, backup, restore, disk, operations, google play, apk, privacy, mirror]
order: 140
---

This topic is for administrators and the people who run the installation. What people may do is set in ARGUS;
the sign-in service only says who they are.

## The administration pages

**Administration** (**⚙ Workspace** menu, top right) has two groups, and every page says which it is in:
**This workspace** (Access, Members, Packages, Keys, Imports, GLPI, icons, transfer, migration, the AI endpoint,
robot tokens) changes only the workspace named there; **Whole installation** changes every workspace and is for
administrators:

| Page | For |
|---|---|
| **Workspaces** | every workspace; **New workspace** |
| **Users** | everyone who has signed in; who is an administrator |
| **Settings** | how workspace identifiers are made from names (prefix, case, separator, length) |
| **AI** | the AI settings every workspace without its own uses (see *AI settings*) |
| **API tokens** | every personal and robot token: who made it, what it may do, expiry, last use; revoke any |
| **Portability** | exports and imports (see *Export and import*) |
| **Statistics** | how ARGUS is used, anonymously (below) |

## Statistics

**Administration → Statistics** opens with the **storage**: for the attachment files, the database and the
portability archives, what is used, the room planned (the volume's size in the deployment), what is still
available (the planned room left or the free space on the disk under it, whichever runs out first; the
database's disk is on another node and is not seen), the growth per day and, at that rate, roughly when it is
full; then the attachments' growth since their first upload, the daily measurements (taken hourly, the trend
builds up from the first day), the attachments by workspace and the largest database tables. **Measure now**
measures again.

It then shows, for the last 7 to 365 days: requests per day by client (web, Android app,
assistants through MCP, scripts); people per day and the most at the same time (per five minutes); the language
model's calls and tokens by model, purpose and workspace; activity in each workspace (requests, changes,
records created, Ask questions); the most used, slowest and failing functions; how Ask ARGUS answers; and how its
answers were rated, with those rated not useful.

Nobody is named: people are counted as a keyed hash per five minutes, and the ratings keep no author. Tokens a
provider does not report are estimated. `ARGUS_USAGE_STATS=0` switches the counting off.

## Workspace templates (packages)

A workspace's types come from **template packages**, versioned definitions that ship with ARGUS:

| Package | Gives a workspace |
|---|---|
| **Core facility** | ticket and document types and their fields, status and priority, the default ticket workflow (every workspace) |
| **Core objects** | equipment, products, vendors, places, cables, spares: what every object catalogue stands on |
| **IT** | network and computing equipment, network segments and addresses |
| **Electrical distribution** | switchboards, panels, breakers, transformers, UPS, generators, meters, circuits |
| **Hydraulic networks** | pumps, valves, pipes, tanks, flow and pressure transmitters, heat exchangers |
| **HVAC** | air handling, fan coils, dampers, cooling towers, heat pumps, ducts, sensors |
| **Technical plant** | electrical, hydraulic and HVAC together, with plant systems and technical rooms |
| **Accelerator catalogue** | the machine as functions (sections, modules, beam elements), its equipment, control and engineering records |

Packages combine: an accelerator site can add the technical plant; an IT department needs only IT. Each brings
what it stands on (Core objects first), and no type is ever defined twice.

- **New workspace → Starts from**: tick the packages; the form lists each one (and what it needs) with what it
  holds before anything is created. With the accelerator catalogue, choose whether the workspace keeps the
  whole catalogue or hangs from a catalogue workspace, sharing its equipment, products and locations.
- The workspace's **Packages** page (**⚙ Workspace → Packages**) says exactly which version of each it
  uses, with a checksum of what was applied, how it was put in, and the history: installed, upgraded, seeded
  by an import, or found in place when the record began. **Add a package** previews what it would create
  before anything changes; installing is all or nothing.
- Installing the version a workspace already has changes nothing. A package holds definitions only, never
  records or site data.
- **Upgrading** to a newer version (offered on the Packages page) lists every change first. New types, fields
  and options go in by themselves; new wording too, except where the workspace changed it itself. Anything
  that could break records — a field removed or renamed, tighter rules, fewer options, a type withdrawn —
  needs a decision, *apply* or *keep this workspace's*, with the number of records it touches; applying is
  refused while records would not satisfy it. The decisions are kept in the package history.
- Imports need the packages their records use (an EPIK8s or PBS import needs the Accelerator catalogue): a
  workspace without one is told what to install, and nothing is imported.

## The production installation

| | Address |
|---|---|
| the hub | `https://argus-hub.90.147.174.30.myip.cloud.infn.it` |
| its API | `https://argus-hub-api.90.147.174.30.myip.cloud.infn.it` |
| sign-in (Keycloak, realm `argus`) | `https://keycloak.90.147.174.30.myip.cloud.infn.it` |
| privacy policy | `https://argus-hub.90.147.174.30.myip.cloud.infn.it/privacy.html` |

- **Sign-in**: the hub's Keycloak (*Keycloak login*) or Google. Keycloak accounts are created by an administrator in
  Keycloak's admin console (*Users*); what they may do in ARGUS is set in ARGUS.
- **The version running**: `<API>/v1/meta/version` says it, with the commit it was built from; the mobile app shows
  it under *About and diagnostics*.
- **Your data** lives in the installation's database and its attachments and portability volumes.

## New versions

A release is a version tag (`v1.35.21`, for example). It:

1. runs the backend tests in the image that will be shipped, and builds the web app;
2. builds and publishes the images (the base images come from mirrors of Docker's images, so Docker Hub's download
   limits do not stop a release);
3. commits *Deploy <version>* to `main`, which Argo CD rolls out to the cluster. If the new version is not running a
   few minutes later, ask Argo CD to refresh the application;
4. builds the mobile app: an **APK** attached to the GitHub release, and an **app bundle** for Google Play (sent to the
   *internal testing* track when the Play service account is configured).

The mobile app installed from GitHub offers the newer release on its home screen; the Google Play version is updated
by Google Play. The two are signed differently: a phone keeps one or the other.

## Cleanup, backups and recovery

Unused container images are removed from the servers every two days, and finished portability files after one day:
download a portability archive you want to keep before then. Cleanup is housekeeping, not a backup.

Whoever runs the installation should write down what is backed up (database, attachments, configuration and
secrets), how often and for how long, how to restore it, and when a restore was last tested. A portability export
and a database backup serve different purposes (see *Export and import*).

## For operators

The Helm chart, secrets, storage and upgrades are described in the repository's `k8s/README.md` and
`docs/operations.md`. Keep credentials out of this guide, and keep the administrators' and support contacts beside
the deployment procedures.
