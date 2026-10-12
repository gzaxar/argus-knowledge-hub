---
title: Administration and the production installation
summary: The administration pages, the production installation (addresses, sign-in, releases, the mobile app's distribution), backups, and where operators find the details.
keywords: [administration, package, packages, template, workspace template, catalogue package, accelerator catalogue, core facility, admin, settings, workspace identifiers, users, production, deployment, release, version, argo cd, keycloak, kubernetes, backup, restore, disk, operations, google play, apk, privacy, mirror]
order: 140
---

This topic is for administrators and the people who run the installation. What people may do is set in ARGUS;
the sign-in service only says who they are.

## The administration pages

For administrators, **Administration** (bottom of the side bar):

| Page | For |
|---|---|
| **Workspaces** | every workspace; **New workspace** |
| **Users** | everyone who has signed in; who is an administrator |
| **Settings** | how workspace identifiers are made from names (prefix, case, separator, length) |
| **AI** | the AI settings every workspace without its own uses (see *AI settings*) |
| **API tokens** | every personal and robot token: who made it, what it may do, expiry, last use; revoke any |
| **Portability** | exports and imports (see *Export and import*) |

## Workspace templates (packages)

A workspace's types come from **template packages**, versioned definitions that ship with ARGUS:

| Package | Gives a workspace |
|---|---|
| **Core facility** | ticket and document types and their fields, status and priority, the default ticket workflow (every workspace) |
| **Accelerator catalogue** | the object types of an accelerator facility: sections, modules, beam elements, equipment, products, vendors, control, locations, network records, ports |

- **New workspace → Starts from**: tick the packages; the form lists each one (and what it needs) with what it
  holds before anything is created. With the accelerator catalogue, choose whether the workspace keeps the
  whole catalogue or hangs from a catalogue workspace, sharing its equipment, products and locations.
- The workspace's **Packages** page (link at the bottom of the side bar) says exactly which version of each it
  uses, with a checksum of what was applied, how it was put in, and the history: installed, upgraded, seeded
  by an import, or found in place when the record began. **Add a package** previews what it would create
  before anything changes; installing is all or nothing.
- Installing the version a workspace already has changes nothing. A package holds definitions only, never
  records or site data.

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
