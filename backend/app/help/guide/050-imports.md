---
title: Importing data
summary: Bringing equipment, tickets and documents in from EPIK8s, Jira, Confluence, Git and Markdown; re-running imports; mapping imported records.
keywords: [prerequisite, missing package, install the catalogue, import, imports, epik8s, values.yaml, jira, insight, confluence, git, markdown, re-run, merge strategy, mapping, catalogue mapping, channels, hardware, infer elements]
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
| **Confluence** | a Confluence space's pages, as documents |
| **Git** | files from a Git repository |
| **Markdown** | Markdown files, as documents |

A configuration is saved with a name and can be **run again** whenever the source changes; each run
records what it read (for Git sources, the commit).

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
