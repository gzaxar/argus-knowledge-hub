---
title: Migrating records to a package type
summary: Move records from a custom type, or a shared catalogue's type, to a standard type of a versioned package — previewed, in batches, verified, reversible.
keywords: [migrate type, change type, retype, type migration, standard type, package type, custom type, deprecated type, promote type, package yaml, map fields, mapping, provenance, workflow states, shared catalogue, catalogue]
order: 166
---

When a workspace (or a shared catalogue) made its own type before a package had a standard one, its records can be
moved to the package's type: they stay where they are and keep their key, history, comments, files, links, map
positions and indoor placements. **Administration → Type migrations** (instance administrators only).

## Migrate, step by step

1. **New migration → Source**: choose the kind (assets and records, tickets, documents), the type the records have
   now, whether the types below it are included, and the owning workspaces. Each record is migrated in the workspace
   that owns it.
2. **Target**: choose a type of a package. The table shows, for each owning workspace, where that type lives (the
   workspace, or its shared catalogue) and whether the package is installed there at the right version. If it is
   missing, **Preview the install** shows what installing it would do, and **Open … packages** takes you to that
   workspace's Packages page to install it. Give a **reason**, then **Create the plan**.
3. **Map the data**: for each old field, **Copy to** a target field (and map each value of a choice list), **Transform
   to** (with a conversion), **Keep in provenance** (removed from the record, kept with the migration), or **Hold for
   review**. Give values for required target fields; for tickets, map each state to a state of the target workflow.
   **Save the mapping**.
4. **Preview**: nothing is written. Counts by owning workspace — ready, review, blocked, not visible to you, already
   there — and, for every record, what changes and why it cannot move yet. **Leave out** a record if needed. Preview
   again after every change.
5. **Apply**: moves the records shown as ready, in batches. A record that fails is listed and the others go on;
   preview and apply again to retry — nothing is moved twice.
6. **Verify**: checks every moved record against what it had before. Tick **Deprecate the old type** to mark it
   deprecated once nothing uses it (it is never deleted). **Revert** puts the records back.

## When no package has the type you need

In step 2, **Propose this one as a package type** writes the custom type as package YAML and checks it (names, field
keys, choice ids, its parent, the package's next version). Give the YAML to the people who maintain the packages: it
goes into a new package version through review and a release. Once that version is installed, migrate the records.
