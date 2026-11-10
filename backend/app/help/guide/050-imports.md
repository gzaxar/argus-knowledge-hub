---
title: Importing data
summary: Bringing equipment, tickets and documents in from EPIK8s, Jira, Confluence, DokuWiki, Git and Markdown; re-running imports, by hand or on a schedule; mapping imported records.
keywords: [confluence authentication, source metadata, source version, file viewer, missing attachment, imported parent, published import, dokuwiki, wiki, wiki.infn.it, namespace, schedule, scheduled, nightly, every day, every week, run by itself, confluence page link, share link, short link, prerequisite, missing package, install the catalogue, import, imports, epik8s, values.yaml, jira, insight, confluence, git, markdown, re-run, merge strategy, mapping, catalogue mapping, channels, hardware, infer elements]
order: 50
---

Imports read another system into the workspace you are in. They do not delete records: a re-import
updates what the source says, and what a person changed since the previous run is decided by the **merge
strategy** (by default, the person's value is kept).

## Where

The workspace's **Imports** page (**⚙ Workspace → Administration → Imports**) lists saved import configurations and past
runs. **New** starts one. Choose the source:

| Source | What it brings |
|---|---|
| **EPIK8s control** | a beamline's control configuration (`values.yaml`): IOCs, devices, services, and optionally the equipment they drive |
| **Jira objects** | Jira Insight / Assets objects |
| **Jira tickets** | Jira issues, as tickets |
| **Confluence** | a Confluence space's pages, a query's, or one page and the pages under it, as documents |
| **DokuWiki** | a wiki page (such as `wiki.infn.it`) and the pages under it, as documents with their pictures |
| **Git** | files from a Git repository |
| **Markdown** | Markdown files, as documents |

A configuration is saved with a name and can be **run again** whenever the source changes — by hand
(**Run**) or by itself on a schedule (see *Run an import on a schedule*); each run records what it read (for Git
sources, the commit).

## What a workspace needs before an import

An import writes records of the types the workspace already has; it never installs types. An **EPIK8s** or
**PBS** import needs the **Accelerator catalogue** package; Jira, Confluence, Markdown and Olog imports need
**Core facility** (every workspace made in the web app has it). If the workspace lacks it, the import stops
before writing anything and says which package to install: install it on the workspace's **Packages** page
(**⚙ Workspace** menu, top right), preview first, then import again. An import still creates the kinds its
own data names (a Jira issue type the workspace lacks), never a whole catalogue, and leaves the fields of
the workspace's ticket and document types as they are.

## A new release of an EPIK8s configuration

Run the import again, or let its schedule do it. It compares what the file says now with what the hub
holds: new records are made, only what really differs is updated, and everything else is left alone, still
naming the revision that last changed it. The job says how many records were created, updated and left
unchanged.

What the file no longer declares, such as a renamed IOC or a changed prefix, stays unless you tick **Clear
what this file no longer declares**. Those records are then retired, each one listed in the job's messages.
Tickets and documents keep their links, and a record the file states again comes back as it was. Only records
this file made are affected: never another file's, another source's, or one made by hand. A file that
declares no IOC retires nothing. A ledger-only workspace retires records through a bulk change instead.

Keys join their parts with `-` (`BTF-ELM-BPSA31`, `BTF-DEV-libera12-BPSA11`), so they don't read as PV names.
The PV itself is on the record, under `pv`.

A BPM whose IOC lists no devices is one monitor, so the import makes one Control Device for it on the IOC's own
prefix (`BTF-DEV-libera02-BPSA31`, PV `ACC:DIA:LIB02:BPSA31`).

## One supply, several magnets

Say in the values file which magnets a channel's power supply drives, with `magnets:` on the device. It works
with or without inference:

```yaml
- name: QUAA-001
  id: 2
  magnets: [QUAA101, QUAA201, QUAA301, QUAA401]
```

- The channel gets a **Power Supply** record (one already held under the channel's name is reused), and each
  magnet is linked to it with `powers`. The magnet's page then shows its supply and channel.
- With no list, a channel of a magnet IOC (`devgroup: mag`) powers the magnet of its own name, if the workspace
  has one. Channels left with no magnet are listed together in the import's messages. A channel spelt differently
  from its magnet (`CHHTL001`, `CHTL001`) needs a list, or the same name in both.
- Magnets are found by name among the beam elements, the beam model's first. A name that matches nothing, or
  several, is reported in the import's messages and no magnet is invented.
- With a list, the file decides: a magnet taken off the list loses its `powers` link at the next import.

An element the beam model or a person already recorded is also reused by **Infer equipment and lattice elements**,
which no longer makes a second record beside it.

## Import an EPIK8s configuration, step by step

1. The workspace has the **Accelerator catalogue** (its **Packages** page). Hanging from a catalogue
   workspace, it shares that one's equipment, products and locations.
2. **Imports → New → EPIK8s control**.
3. **Configuration name**: for example `epik8s-btf`.
4. **Provider** (GitHub or GitLab), **Repository URL** (for example
   `https://baltig.infn.it/lnf-da-control/epik8s-btf.git`), **Branch** (`main`) and the path of the
   values file (`deploy/values.yaml`). **Personal access token**: only for a private repository; leave
   it blank for a public one.
5. Options:
   - **Infer equipment and lattice elements (rules)**: also make what the channels drive, which the file
     never lists: magnets and their supplies, ion pumps, cameras, BPMs, screens, mirrors… They are
     marked *inferred*; a person's later edits are kept on the next run under the default merge strategy
     (check the strategy before re-running).
   - **Infer controllers**: the controller box each IOC talks to.
   - **Link to units already in the inventory**: link a channel to equipment the inventory already
     holds instead of inferring a twin (as proposals under *Channels ↔ hardware*).
   - **Ask the AI about channels the rules don't recognise**: its answers are proposals in the Review
     queue.
   - **IT workspace for converters, servers and their ports**: optionally, a shared workspace where the
     serial converters and servers the hostnames name are made, once for all beamlines.
6. Save and run. The run page shows progress, then the counts and any warnings.

Notes:
- The workspace gets the catalogue's types automatically the first time.
- A file that is an **overlay** (such as `values-linac.yaml`, with no `beamline:` of its own) takes the
  beamline and its templates' defaults from the `values.yaml` beside it. Import the main file and the
  overlay as two configurations.

## Import Confluence pages

**Imports → New → Confluence**. Name the configuration and provide credentials for the source. The importer
supports personal-access-token authentication and an email/token mode; use the mode appropriate to your
Confluence installation. A server personal access token and a Cloud email/API-token pair are not
interchangeable. The source account must be able to read the pages and files you select. ARGUS workspace
access does not grant access to Confluence.

For a personal access token, create one in the source account's **Personal Access Tokens** settings where
available. Do not paste credentials into a document body or an Ask ARGUS question. Then say which pages:

- **A page link**: the short link from the page's **Share** button (`https://confluence.infn.it/x/YwX6AQ`)
  or the page's address. It imports that page and, with **And every page under it**, its whole subtree.
  The server is taken from the link, so the server URL may stay empty.
- **A space key** (`LNF`): every page and blog post of the space.
- **A CQL query**: whatever it selects.

The server address must include its context path when required, such as `/wiki` or `/confluence`. If a browser
link works but the import returns a login page, check the authentication mode, source account permissions and
server address; being signed in in your browser does not authenticate the importer.

Pages become ARGUS documents. Type selection checks recognised labels first, then recognised title prefixes,
then uses a fallback type. Inspect the actual assigned type after import: a folder or WP prefix is not an
automatic Work Instruction classification. The page tree becomes *child of* links between available pages.

Imported revisions arrive **Published** as copies of source material. This is not a record of a local ARGUS
review/approval decision. Check the document's source, authority and applicability before treating it as a
controlled operating instruction.

## Check imported Confluence content and files

1. Open a representative imported page in **Documents**, then **Open full document** if you need its complete
   metadata and file controls.
2. Check its title, actual document type, body, state and revision. The importer records the source page ID,
   link, space, version, author, update time and labels where the source provides them. The browser shows
   source-space information and **From Confluence** when available.
3. Check the summary against the body. A summary is introductory text, not a replacement for the complete
   source. A page with no introductory prose can have no summary; read the import's warnings.
4. Open a sample image and linked PDF or other attachment. Supported Confluence file-viewer macros are
   converted into attachment links; interactive source viewers are not copied as running applications.
5. Check the run report for attachment-list, download, size-limit and conversion warnings. A page can import
   while a file needs attention. Do not infer that every source file was copied from the job's completion alone.

Files copied into ARGUS use ARGUS attachment links and the document's normal access checks. Open them while
signed in to ARGUS. A source-only link can still need Confluence access. If a link fails, distinguish these two
destinations and report the document code, revision and filename to the administrator; do not share tokens.

## Re-import Confluence without losing the navigation layout

Run the saved configuration again to update the same source. An unchanged source version is skipped rather
than receiving an identical new revision; changed source pages receive another imported revision. Source
titles and type selection are refreshed during import, so review any locally edited classification rather
than assuming it is protected by manual folder placement.

The browser's **Move in hierarchy** stores navigation separately from imported parent relationships. A manual
folder or parent-page placement is retained across re-imports; **Use relationship / imported parent** removes
that override. Preserving navigation does not promise that imported body text or metadata is protected from
source updates. Keep controlled local work in the normal revision workflow and check the import strategy.

If only a subtree was imported, a parent outside that selection is not invented. Ordinary pages without a
usable parent appear under **Unfiled documents**; root WP overview pages follow the workspace's WP naming
convention. See *Document hierarchy and subsystem pages*.

Re-running an unchanged source page is not a general attachment-repair command: the version check can skip
its content and files. If an older import has a broken file link or conversion, give an administrator its
document code, source page, revision, filename and run warning so the appropriate repair can be assessed.

## Import DokuWiki pages

**Imports → New → DokuWiki**. Give a wiki page's link (`https://wiki.infn.it/strutture/lnf/da/btf/dispositivi/stages`)
and, with **And every page under it**, its folder (namespace) and the folders below — for the calorimeter page,
also BGO, CALOBTF1 and CALOBTF2. No token: the wiki is read as anyone allowed to read it, and only the wikis this
installation allows (by default `wiki.infn.it`) can be imported.

Each wiki page becomes one **published** document (code `WIKI-…`), its text as Markdown with its tables and
lists, its pictures attached and shown in place, its wiki link kept (*Source link*). A link to another page of
the import leads to that page's document; a page under another (`calorimeter:bgo` under `calorimeter`) is its
*child*; an asset key named in a page links the document to the asset. **Running it again** finds each page's
document: a page that has not changed is skipped, one that has gets a new revision (the previous one is
superseded). At most 500 pages per run.

## Run an import on a schedule

In a configuration (new, or **Edit**), **Run again by itself**: every few hours, every day at a time, or every
week on a day at a time — a local time that stays put across the changes of daylight saving. The **Imports**
list shows each configuration's schedule, when it runs next, and how its last scheduled run went.

A scheduled run is the same as **Run**: an import of a wiki or a Confluence space checked every night adds a
revision only where a page changed.

- It runs **as the person who set the schedule**, with their permissions at the time; if they may no longer
  import there, the run fails and says so.
- It does not start while the configuration's previous run is still going (it tries again later).
- A failed run notifies that person, with the run's report. After **3 failures in a row** the schedule switches
  itself off, and the list says why.
- Set the schedule to **No** to stop it; **Run** still works.

## After an import

- **Review queue**: inferred facts, AI proposals and conflicts wait there for a decision.
- **Assets → Channels ↔ hardware**: proposed links between control channels and inventory units.
- **Assets → Map imported records**: records imported as they were in Insight are mapped onto the
  workspace's types, with a plan per source type that a person reviews before it is applied.

## Merge strategy

When an import meets a value a person changed since the previous run, the strategy decides: keep the
person's value (default), take the source's, or take whichever is newer.

## Check an import before running it again

1. Confirm the destination workspace and the saved configuration.
2. Read the previous run's counts and warnings.
3. Open a few representative records and their **Provenance**.
4. Look at the inferred facts, conflicts and proposed hardware links waiting in the **Review queue**.
5. Check the **merge strategy**, especially after people edited imported values.

Re-run the saved configuration to update the same source. Something that disappeared from the source has not
necessarily been removed or retired at the facility: find out before you change it by hand.
