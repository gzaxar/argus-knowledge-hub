---
title: The product catalogue
summary: The shared Vendors and Product Models every workspace points at — where they come from (two Git repositories, pinned), how a release is previewed and installed, how existing records are adopted without losing their links, which values Git manages and how a correction goes back, matching GLPI's devices to models, and what to check when something is refused.
keywords: [catalogue, catalogue workspace, system catalogue, status, protected, product model, vendor, manufacturer, collection, release, install, upgrade, preview, adopt, adoption, migration, manifest, export, netbox, device type, glpi, match, correction, git, pull request, lock, pin, datasheet, verification, duplicate, retire, transfer]
order: 168
---

Every workspace's units point at **one shared catalogue** of Product Models and Vendors, kept in the
installation's catalogue workspace. A model used by both the IT and the accelerator workspaces is one record: a Moxa NPort
5450 is `moxa/nport-5450` wherever it is installed. The units themselves — serial numbers, positions, owners —
stay in their own workspaces.

The catalogue's content is kept in Git, reviewed, and released:

| Repository | Holds |
|---|---|
| `infn-argus/argus-catalogue` | every manufacturer; accelerator equipment (vacuum, motion, diagnostics, power, RF, timing and I/O); ARGUS's classification of the IT devices |
| `infn-argus/devicetype-library` | IT devices, in the NetBox Device Type Library's format (a fork, so additions can go back to NetBox) |

Neither ever holds site data: no serial numbers, installed units, locations, sellers, prices or people.

## Where to find it

- **Settings › Product catalogue** — everyone: browse and search the models, from a collection (with their
  catalogue id), local (made here), or retired, and how many units are of each. The **Domains** navigator beside
  the list browses them by domain (IT, accelerator, vacuum…, and the models made here) › device class › vendor,
  with how many at each step; choosing one filters the list (the *Domain* filter does the same).
- **Administration › Catalogue** — administrators: which workspace is the catalogue and what depends on it, the
  pinned sources, the collections and the version installed, preview and install, the entries waiting for
  review, the corrections for Git, the history, and matching GLPI's devices (for the workspace you choose).
  The old *Catalogue collections* address leads there.

The catalogue is not a workspace to work in: it is not in the workspace switcher. Everyone reads its models from
their own workspace, and a maintainer edits a model from there too (*Open the record › Edit*: the edit is made,
and its permission checked, in the catalogue). Its shared types are upgraded on *Administration › Packages*. An
administrator renames it on *Administration › Catalogue* (its id and record keys stay, being printed on labels),
and, rarely, opens it as a workspace from there — to clean up a record that does not belong in it, which the page
names.

## Choosing a unit's model

A unit's **Product model** is typed as on its label — the model code, or part of it — on the web and on the
phone. The models already in the catalogue come first; then the **library** of the catalogue's sources: every
model of the pinned collections not yet installed, among them the whole NetBox Device Type Library — some 12,700
devices of 390 manufacturers (marked *NetBox · add*). Choosing a library model adds it to the catalogue there and
then — with its manufacturer, when the catalogue does not have it — and the unit points at it; the next person
finds it already there. A record already here that looks like it (the same vendor and model code) is never
overwritten: it is offered instead. Offline, the phone offers the models already in the catalogue.

A NetBox model comes with everything NetBox says of it: its **part number**, **height** in rack units, **full
depth**, **airflow**, **weight**, **maximum draw** per power input, its **ports** in one line, and its
**components** — every interface (with its type, PoE, management flag), console and serial port, power input and
outlet, front and rear port, module and device bay, and part — shown as tables on the model's page, with
NetBox's notes; a link in those notes is its datasheet. These are the Product Model's *Hardware* fields
(core-objects 2.3: the catalogue workspace needs that version to keep them).

On the web, a **new unit** whose Product model lists its components is offered its ports, ticked: each
interface, console and serial port becomes an Equipment Port, `port of` the unit — a C9200-24T's 24 copper ports,
its management port and its consoles. A MAC typed in the network section goes on the port of the same name.

## Linking a model made by hand to NetBox

A model created before the catalogue had it (by hand, from GLPI or a spreadsheet) gets NetBox's information by
being **linked** to the same NetBox model. On its catalogue page (*Product catalogue › the model*), a catalogue
maintainer uses **Find it in the catalogue's sources**: the model code is searched in the library, the record's
look-alikes included, and **Link to this one** adopts the record in place. Its empty fields are filled —
part number, hardware, components, datasheet — the values it has are kept as local overrides, and every unit
and link stays where it is. From then on the NetBox fields follow the library's releases.

## Which models a workspace is offered

Each collection names its **domain**: the packages whose workspaces its models are for (the IT devices for
workspaces with the IT package; vacuum, motion, diagnostics, power and timing for those with the accelerator,
vacuum or optics packages). When a unit's *Product model* is chosen, the picker shows the models of the
workspace's domains and the local ones; **Show every model** shows the rest. Nothing is hidden from search, and
a unit keeps the model it points at. Collections installed before domains were kept are offered everywhere.

## Who maintains it

Everyone can read the catalogue. It is **maintained** by the administrators and by the people and groups given
*Curator* or *Owner* on the catalogue workspace — added and removed under **Maintainers** on *Administration ›
Catalogue*. A maintainer edits Vendors and Product Models, installs and upgrades collections, decides the
catalogue's review queue and downloads the corrections for Git; an Owner also grants access to the catalogue.
Maintainers who are not administrators find *Catalogue* in Administration, and nothing else there.

## The catalogue workspace

One workspace is the installation's catalogue: an administrator sees which in
`python -m app.catalogue status` (or `GET /v1/admin/catalogue`), with what it holds, the workspaces that take
their shared types from it, and how many units in each point at its models. In an installation that had a
catalogue before, it is the workspace that already held the shared types and models; in a new one, the first
workspace given the object catalogue as the one others hang from, or the one an administrator designates.

It is protected, because every workspace depends on it:

- it holds **Vendors and Product Models only** — a unit put there would belong to no workspace, so it is
  refused, whatever tries to write it;
- it cannot be **deleted**, **exported as a workspace bundle** (its collections are its portable form), be a
  transfer's **target**, have anything **moved out** of it (copying is allowed), or be made to **hang from**
  another workspace.

Its shared types are managed by its packages, as in any workspace.

## Which release ARGUS reads

ARGUS reads each repository at exactly one commit. The lock file it ships, `backend/catalogue/sources.lock.yaml`,
pins each source at a release tag and its commit; the collections page shows the pins. A release tag must still
point at its commit: if someone moved it, ARGUS refuses to read it.

A source pinned to a release can be moved to a newer one **from the collections page**, without an ARGUS release:

1. In the repository, the release is a tag (`v0.3.0`), with its changes in `CHANGELOG.md`. The catalogue
   repository makes one by itself after each merge that changes its collections, once the ARGUS validator passes.
2. Under **Sources**, **Check for newer releases**, then **Check and pin** the one you want. ARGUS reads it and
   runs its validator over it, against the catalogue read now (nothing removed without being retired or moved,
   versions raised); a release that fails is not pinned, and the problems are listed. Pinning installs nothing.
3. **Preview** the collections that now show an upgrade, then **Install** (below).

The page says who pinned a release and when; **Back to** returns to the lock's release (what is installed stays
installed). An ARGUS release whose lock ships a newer release than the one pinned here takes over by itself.

The API pod needs to reach github.com to list releases and fetch a new pin; each pin is fetched once.
`python -m app.catalogue sources` in the pod shows the pins and reads them.

## Proposing a model made here

A model a unit needs today can be made by hand in the catalogue. To put it in the Git catalogue, open it from
the product catalogue and choose **Propose for the catalogue…**:

- ARGUS fills the entry from the record: its vendor (the catalogue's, or a new one proposed with it), model
  code, name, part number, device class, datasheet; the catalogue id is `vendor/model`.
- Choose the collection, or name a new one (with the packages its models are offered to, or `catalogue` for
  every workspace), and say what the values were **checked against** — the datasheet or manufacturer page.
  Only what the source confirms goes in: a unit's serial number, firmware, address or location never does.
- **Check the files**: ARGUS writes them against the repository's main branch (the entry in its place, the
  collection's version raised once per release) and runs its validator. Then **Open the pull request**: it
  names you, and the repository's reviewers decide. ARGUS never merges.

**Proposed to Git**, on the collections page, follows each one: pull request open, merged (waiting for a
release), closed, installed. When the release carrying it is pinned and installed, the record you made is linked
to its entry — same record, its units untouched — and takes the reviewed values.

Proposing needs ARGUS's GitHub credential (`ARGUS_GITHUB_TOKEN`, key `ioc-github-token` in the chart) with
*Contents* and *Pull requests* on the catalogue repository; `ARGUS_CATALOGUE_REPO` names another repository than
the one the lock pins.

## Installing or upgrading a release

1. **Catalogue collections**: tick the collections to install or upgrade (those they require come with them; one
   that does not validate cannot be ticked), then **Preview**.
2. Read the preview, entry by entry:
   - *New* — created, shared, every value it states managed by the collection;
   - *Changed* — a managed value the release changed, written;
   - *Already here: link or create* — a record that looks like the same product: decide (below);
   - *Kept local (review)* — the release changes a value this workspace keeps, or one edited here: the record
     keeps its value, and the entry goes to *Waiting for review*;
   - *Moved between collections* — the entry follows; the record does not change;
   - *Retired* — marked retired; the record stays, with every unit and link, and is still offered.
3. **Install** is enabled when every link has its decision. A release is installed in one go or not at all;
   installing the version already installed changes nothing.

An install is refused when a collection does not validate, when the same version arrives with other content,
when the version is older than the one installed, or when the catalogue workspace lacks a package a collection
requires (the message names it: upgrade it on the workspace's **Packages** page first).

## Adopting the records you already have

A record that existed before its catalogue entry is **adopted**, never replaced: it keeps its uid and key, and
every unit, relation, document link and alias stays where it is. For each field where the record and the
collection differ, choose:

- **the collection's** — the value is replaced now, and later releases keep it up to date;
- **keep this record's** — a local override: releases leave it alone;
- **keep, and propose to Git** — the record's value is the right one: it stays, and it is proposed back
  (below).

A field that agrees, or is empty on the record, needs no decision. A match found only because the model code
appears inside the record's name ("TPG 366 control unit") is always a person's decision: the controller of a
pump can carry the pump's name.

### The first migration: export, review, install with the manifest

For a workspace with many records, prepare the decisions in advance. In the API pod:

    python -m app.catalogue export --workspace accelerator-infn --out /tmp/export

It only reads, and writes: candidate entries for the repositories (no ARGUS ids), `report.md` and `report.csv`
(what each record becomes, and what to look at), and `migration-accelerator-infn.yaml` — **this installation's
migration manifest**: which record each catalogue id is, the duplicates to merge into it, the field decisions,
and the references counted. Keep the manifest with the installation's operations records; never put it in a
repository.

Review the candidates into the repositories and release them. Then, on the collections page, load the manifest
under **Migration manifest**, **Preview** and **Install**. The duplicates are merged (the survivor keeps its
uid; a merged record redirects to it), and afterwards the units and document links are counted again: if any
were lost, nothing is installed.

## Which values Git manages

| Values | Managed by |
|---|---|
| name, model code, part number, physical and port specifications of an IT device | the NetBox fork |
| the same, for accelerator equipment | `argus-catalogue` |
| device class, the ARGUS type of its units, end of life, successor, datasheet, related models | `argus-catalogue` |
| description, seller, support, firmware in service, anything the collection does not state | this workspace |

Each value on a model's page shows where it comes from: *from the collection*, *edited here*, *local override*,
*proposed to Git*, or the record's own.

## Editing a managed value, and proposing corrections

Editing a managed value on the record's form is allowed; the model's page then shows it as **edited here**, and
it appears under *Waiting for review*. Until someone decides, the next release keeps it and reports a conflict.
On the model's page, choose: keep it as a local override, propose it to Git, or use the collection's value.

To send the proposed corrections back: **Catalogue collections › Waiting for review › Download the corrections as
patches**. You get one patch per repository (`argus-catalogue-corrections.patch`,
`devicetype-library-corrections.patch`), against the pinned commit:

    git switch -c corrections <pinned commit>
    git apply argus-catalogue-corrections.patch
    git commit -am "Corrections from ARGUS"      # then open a pull request

A value a source's format has no place for (a NetBox model's datasheet or description) is listed instead,
with the reason. When a release carrying the corrected value is installed, the correction closes and the field
is managed again.

## Matching GLPI's devices to models

In a workspace synced from GLPI, **Product catalogue › GLPI devices in this workspace › Propose models**. For
each device with no product model, the catalogue model its GLPI manufacturer and model name is proposed —
*exact* (the vendor's name or alias, and the model code or part number) or *near* (scored). Each proposal waits
in the **review queue** under *Facts to confirm*: **Accept** sets the device's model; **Reject** keeps it from
being proposed again. Nothing is set without a person. Two equally good models are reported, not guessed; the
GLPI models nothing matches are listed, with their device counts, as candidates for new catalogue entries.

## Adding or verifying a model

New models are added to the repositories by pull request, never in ARGUS: an accelerator model to
`argus-catalogue`, an IT device as a NetBox device type to the fork (and its classification to
`argus-catalogue`). Every specification cites the manufacturer's document it was checked against. Entries added
from INFN's records first carry their identity only; `VERIFICATION.md` in `argus-catalogue` lists those still
waiting for their datasheet.

## When something is refused

| Message | What to do |
|---|---|
| *the collections are not valid* | the list names each problem; fix it in the repository and release again |
| *needs the package … and … has …* | install or upgrade that package on the catalogue workspace's Packages page |
| *… is installed with other content* | the release changed without a new version: ask its maintainers for one |
| *the tag … no longer points at the pinned commit* | someone moved a release tag: check the release before pinning again |
| *… is not a valid catalogue for this ARGUS* (pinning) | the release fails ARGUS's validator: the list says why; fix it in the repository and release again |
| *… is not newer than …, the release this ARGUS ships* | the lock already has it, or a newer one: nothing to pin |
| *… is in the catalogue already* / *… is the same model* (proposing) | link the record to that model instead (**Link to the same model in the sources**) |
| *no ARGUS_GITHUB_TOKEN is installed* | an administrator adds the credential before ARGUS opens pull requests |
| *the catalogue's sources cannot be read as pinned* | the API pod cannot reach github.com, or the commit is gone |
| *no vendor named … in the catalogue* | a NetBox device type's manufacturer is not in `vendors.yaml` (or its aliases): add it |
| *references would be lost* | an install with a manifest would leave a unit or document pointing nowhere: nothing was installed; check the manifest's merges |
