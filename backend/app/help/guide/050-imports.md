---
title: Importing data
summary: Bringing equipment, tickets and documents in from EPIK8s, Jira, Confluence, DokuWiki, Git and Markdown; re-running imports, by hand or on a schedule; mapping imported records.
keywords: [dokuwiki, wiki, wiki.infn.it, namespace, schedule, scheduled, nightly, every day, every week, run by itself, confluence page link, share link, short link, prerequisite, missing package, install the catalogue, import, imports, epik8s, values.yaml, jira, insight, confluence, git, markdown, re-run, merge strategy, mapping, catalogue mapping, channels, hardware, infer elements]
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

**Imports → New → Confluence**. Name the configuration, give a **personal access token** (made on
Confluence under your profile, **Personal Access Tokens**): the import reads only what that account may
open. Then say which pages:

- **A page link**: the short link from the page's **Share** button (`https://confluence.infn.it/x/YwX6AQ`)
  or the page's address. It imports that page and, with **And every page under it**, its whole subtree.
  The server is taken from the link, so the server URL may stay empty.
- **A space key** (`LNF`): every page and blog post of the space.
- **A CQL query**: whatever it selects.

Pages become documents typed from their labels; the page tree becomes *child of* links. Running the
configuration again adds a revision only to pages whose version changed.

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
