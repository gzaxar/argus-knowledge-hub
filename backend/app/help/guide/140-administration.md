---
title: Administration and the production installation
summary: The administration pages, the production installation (addresses, sign-in, releases, the mobile app's distribution), backups, and where operators find the details.
keywords: [administration, dangerous action, delete workspace, confirm, type the name, statistics, storage, disk, disk space, free space, occupancy, quota, volume, usage, tokens used, active users, concurrent users, feedback, package, packages, it, electrical, hydraulic, hvac, plant, domain, template, workspace template, catalogue package, accelerator catalogue, core facility, admin, settings, workspace identifiers, users, production, deployment, release, version, argo cd, keycloak, kubernetes, backup, restore, disk, operations, google play, apk, privacy, mirror]
order: 140
---

This topic is for administrators and the people who run the installation. What people may do is set in ARGUS;
the sign-in service only says who they are.

## The administration pages

The **⚙ Workspace settings** menu (top right) holds what the workspace's records are made of: **Packages**, the
**Type catalogue**, the **Product catalogue**, **Global values**, **Ticket workflows**, **Equipment classes** and
**Keys**. Its last entry, **Administration**, opens on **Access** and has one section per scope; every page says which
one it is in:

- **Workspace**: changes only the workspace named there. Its pages are grouped under **People & access** (Access,
  Groups, Access reviews, Help centre destinations, and *Area permissions*, the rights given one person at a time
  before roles and groups existed, kept as an advanced setting), **Content** (Imports, Icon library, GLPI, Transfer,
  Data integrity, Storage, Quotas) and **Integrations** (AI endpoint, Robot tokens). **Migration from Jira**, for a
  team leaving Jira for good, is reached from **Imports**.
- **Site** *name*: for the site's administrators, whichever workspace is open, and for administrators of the
  installation when the open workspace is at that site. **Administrators**, **Site-wide group access** (with its
  changes to access) and **Facilities** apply to every facility currently at the site.
- **Installation**: changes every workspace, and is for administrators.
- **Groups you administer**: **My groups**, for group administrators.

| Page | For |
|---|---|

| **Workspaces** | every workspace; **New workspace** |
| **Users** | everyone who has signed in; who is an administrator |
| **Settings** | how workspace identifiers are made from names (prefix, case, separator, length) |
| **Packages (all workspaces)** | upgrade a package everywhere it is behind (see *Domain packages*) |
| **AI settings** | the AI settings every workspace without its own uses (see *AI settings*) |
| **All tokens** | every personal and robot token: who made it, what it may do, expiry, last use; revoke any |
| **Portability** | exports and imports (see *Export and import*) |
| **Statistics** | how ARGUS is used, anonymously (below) |
| **Storage** | what each storage area uses and has left, its planned room, and freeing space (below) |
| **Quotas** | what a workspace may hold and use, and what each uses (below) |

## Statistics

**Administration → Statistics** has three tabs, for the last 7 to 365 days:

- **Usage**: who is on now and the most at the same time (per five minutes), sign-ins, requests and people per
  day by client (web, Android app, assistants through MCP, scripts), and the activity in each workspace
  (requests, changes, records created, Ask questions).
- **AI**: the language model's calls and tokens by day, model, purpose and workspace; Ask ARGUS questions, how
  the answers ended, the lookups it uses most, and the ratings, with the answers rated not useful (each one a
  ticket).
- **Nerds**: for whoever looks after ARGUS — the most used routes, the slowest, those that failed (server
  errors), and the most used by client.

Nobody is named: people are counted as a keyed hash per five minutes, and the ratings keep no author. Tokens a
provider does not report are estimated. `ARGUS_USAGE_STATS=0` switches the counting off.

The same figures, as aggregates by workspace (never by person), also reach Prometheus and the Grafana dashboard
"ARGUS Knowledge Hub": active people, records held, created and changed, open tickets, the help centre's open
requests and their age, language-model calls and tokens, Ask questions and ratings (docs/k8sda.md, "Metrics").

## Storage

**Administration → Storage** is the whole installation's storage: for the attachment files, the database and the
portability archives, what is used, the room planned, what is still available (the planned room left or the free
space on the disk under it, whichever runs out first; the database's disk is on another node and is not seen), the
growth per day and, at that rate, roughly when it is full; the attachments' growth, the daily measurements, the
attachments by workspace and the largest database tables. **Measure now** measures again.

**Planned room** sets what each area is measured against. Empty uses the deployment's size (the Helm chart) or the
default (portability archives: 10 GB). It does not resize a volume: on a volume that does not enforce its size
(local-path) the disk under it is what runs out, and the gauge says so.

### Freeing space

The portability archives card has **Free up space…**: what the area holds, part by part, and the cleanups that
can be done, each with what it frees and why it is safe. Tick the ones you want and **Free the space**.

- **The export repository copy** (`work/…`): **Compact** packs the objects each export wrote loose; nothing is
  lost. **Drop** removes the copy when the remote repository has all of it: the next export clones it again.
- **Exports and imports that are over**, at any age: an import finalized, discarded or invalid, an export failed,
  revoked or expired. Their files (quarantine, staging, evidence copy, archive) go, as the retention period would
  delete them later; their records and audit stay, and a legal hold keeps them. A failed import can still resume,
  and a published export is still downloaded: they wait for the retention period.
- **Uploaded workspace bundles** older than a week, **exported workspace bundles** older than a month.
- **Left-overs** of exports and imports older than a week (staging, quarantine, verification).

Only an administrator signed in can do it, never with a token.

**Workspace → Storage** is one workspace's share, for its administrators: its attachment files (how many, how big,
their share of all attachments, what was added each day, the largest, by type) and the workspace bundles exported
of it, which an administrator of the installation can remove.

## Quotas

**Administration → Quotas** sets what a workspace may hold and use: defaults every workspace has, and a workspace's
own (open it: *the default*, *unlimited* or *its own* number).

| Quota | Counts | Built-in default |
|---|---|---|
| Storage | the workspace's attachment files | 50 GB |
| Largest file | one file uploaded or attached | 2 GB |
| AI tokens, 5 hours / week | language-model tokens over the last 5 hours / 7 days | unlimited |
| Records, Documents | those not deleted | unlimited |
| Members | people given access directly (a group counts as none) | unlimited |
| API operations, day / minute | requests made with a token (scripts, robots, assistants through MCP) | unlimited |
| Imports at once (installation) | portability imports not finalized, discarded or invalid | 1 |

Past a quota ARGUS refuses what would add to it — a new record, document or member, a file, a call to the language
model, an API request — and says which quota, what is used and when it frees up (a window: the 5 hours, the week,
the minute, the day). Reading, editing and deleting always work, so a workspace can get back under it. Every way
in is held to it: forms, the API, the Jira, GLPI and Confluence imports, workspace bundles. Administrators of the
installation signed in are never stopped, and a portability import loads anyway: its dry run lists what it would
bring over a quota first. At 80% a workspace's administrators see a warning on its administration pages
(**Workspace → Quotas** shows each), and the `ArgusQuotaNearLimit` alert fires. Every change to a quota is audited.

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

## Actions that cannot be taken back

Four actions reach a whole workspace and cannot be undone:

- deleting a workspace;
- making a workspace global (its types and records are seen from every workspace);
- deleting a type, which deletes every record of it;
- deleting the orphaned objects on the integrity page.

Removing a person from ARGUS (**Users → Remove from ARGUS**) is confirmed the same way, with their e-mail address
typed: they can no longer sign in from any identity provider, their personal tokens stop working, and their own
roles, memberships, administration rights and places in local groups go; open tickets assigned to them and planned
activities they own are left for someone else. Their name stays on everything they did. You cannot remove yourself
or the last administrator. A removed person can be invited again later.

ARGUS asks twice before doing any of them. First it asks the question, then it wants the workspace's name typed
exactly. They are done only by a person signed in. An API token cannot do them, even an administrator's token with
every scope, and an MCP client or the Ask assistant cannot either.

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
