# Migrating records to a package type

Records of a **custom type**, or of a type a **shared catalogue workspace** defines, can be moved to a **standard
type of a versioned ARGUS package** — in place, in the workspaces that own them. Code: `app/services/type_migration.py`,
`app/routers/type_migrations.py`, `app/services/type_proposal.py`; web: Administration → Type migrations.

## What was there before, and what this reuses

| Mechanism | Before | Used here |
|---|---|---|
| Ledger retype (`ledger.service.retype`) | in place, keeps uid and key, rebuild-safe — but the statement named the type, and the projection found it **by name** (this workspace first, then any global type) | extended: a type statement can name the type's **identity** (`{"name", "schema_uid"}`); `retype_to` makes it, with field statements in the same batch. Old name-only statements still work. |
| Record mapping (`record_mapping`, `catalogue_mapping`) | maps *imported* records onto types by creating **new** records | not used: records here keep their identity |
| Document retype (`POST /v1/documents/retype`) | one workspace, type only, no fields | replaced, for migrations, by a governed move that maps every revision's fields |
| Package installer | identifies its types by derived uids, records version and checksum per workspace, keeps snapshots of each version | the provenance of the target (below) |
| Workflows | `workflow_for`, `apply_state` | the target state of each ticket |
| Attribute validation | `check_attributes` — required, choices, reference types and visibility, uniqueness | every record, against the target, before writing |
| Relation rules | `packages.relations.check` | every relation of a moved asset, with both ends' new types |
| Restricted records | grants per workspace (`visibility`) | a record the administrator may not see is neither shown nor moved |
| Workspace bundles | — | the two new tables are listed as not carried (an administrative record of this installation) |

## The target: a package's type, by its provenance

A migration names a **package**, the **type as that package declares it**, and the package **version** shipped when the
plan was made. For each owning workspace the target is resolved as the installer made it:

1. **Where it lives:** the workspace itself — or, for an object type of the shared scope, the catalogue workspace the
   workspace hangs from (from its recorded install options, or where its types hang).
2. **Installed:** the package must be installed there, at the plan's version or later (`workspace_packages`: version
   and checksum).
3. **Declared:** the installed version's recorded definition (`package_snapshots`, by checksum) must declare the type.
4. **Identity:** the type row must be the one the installer derives for it (`<ws>:argus-object:<slug>`, a former name's
   uid, or the kind and base uids of ticket and document types) — never another type that has the same name.

Otherwise the preview says what is missing and where (`package_missing`, `package_older`, `definition_unknown`,
`type_not_in_package`, `type_missing`, `abstract`), and offers the **install preview** of that workspace or catalogue
(the installer's dry run; a workspace hanging from a catalogue that lacks the package is told the catalogue goes first).

## Bringing a shared type home

A workspace that hangs from a shared catalogue uses the catalogue's copy of each shared package type. With
`target.home = "own"` (*Bring the type home* in the wizard) each owning workspace gets **its own copy** of the
package type instead — the same package, version and type, under the uid the installer derives in that workspace —
and the records move to it. A shared package type other workspaces use is a source only this way.

- The copy is the catalogue's installed definition (its fields, choices, icon), parented where the catalogue's is,
  with its origin recorded (`metadata.brought_home`: from, catalogue, package, version, migration, time).
- It is made by **apply**; a preview (or the plan's proposal) makes it inside a transaction that is rolled back.
- The package must be installed in the workspace, and its installed version must declare the type.
- Afterwards the workspace's own copy is the target of later migrations there, what its importers use, and part of
  the workspace's **upgrades** of that package (`upgrade.brought_home`); it no longer follows edits made in the
  catalogue. The catalogue's copy stays, and a package type is never deprecated.

## The plan

`type_migrations`: source type (and, optionally, the types below it), the owning workspaces chosen, the target, the
mapping, the reason, the status, the inventory taken before the first batch, the verification, and a **log** (every
decision, batch, verification and revert, with actor and time). `type_migration_items`: one row per record and plan —
owning workspace, status, batch, the record's fields **before** and **after**, the values kept in **provenance**, the
error, actor and time. The row is unique per (plan, record): a record is never moved twice.

### Mapping

Proposed, then the administrator's: each source field is

- **copy** to a target field — choices mapped value by value (proposed where the option id or label matches);
- **transform** to a target field — the same, plus a conversion (`integer`, `float`, `boolean`, `string`);
- **keep in provenance** — removed from the record, kept on the migration item;
- **hold for review** — a record with a value there is not moved until the decision changes.

Plus defaults for required target fields no source field fills, ticket **state** mappings, and individual records
**left out**. A record's `classification` is never mapped, moved or dropped; sharing flags are not touched.

### Preview (writes nothing)

Every record is judged against the target where it lives: `ready`, `review`, `blocked` (with every reason),
`hidden` (restricted, not visible to the administrator there), `already` (on the target) or `applied`. Blocking reasons:
the target missing there; a value without a choice; a required field empty; a reference the target's field does not
accept; a relation the packages' rules would refuse with the new type; **a reference another record makes to it** through
a typed field the new type would no longer satisfy; for tickets, a state the target workflow does not have. The preview
returns counts by owning workspace, the field changes, unmapped values, whether the old type could be deprecated
afterwards, and a **token**.

### Apply

Needs the preview's token (the plan and the records must not have changed). Takes an inventory of each ready record
(uid, key, comments, labels, files, relations, map positions, placements, activities; for documents, revisions; for
tickets, comments, links, files, activities) the first time, then moves the ready records in batches, **one savepoint per
record**: a record that fails is recorded (`failed`, with the error) and the others go on; the plan becomes
`partially_applied`. Applying again (after a new preview) does only what is left.

- **Assets:** one ledger batch per record — a confirmed type statement naming the target's uid, and field statements
  (a removed field is a statement of no value) — in the record's own workspace (its person stream). A rebuild of the
  ledger keeps the result. An `asset_history` entry names the migration.
- **Tickets:** the type, the fields, and the mapped state (through the workflow's `apply_state`); history entries for the
  type and the state.
- **Documents:** the type, and every revision's fields mapped; the revisions themselves (numbers, bodies, approvals)
  stay; the originals of each revision are on the item.

Uid, key, workspace, comments, files, relations, activities, map positions and indoor placements are never touched.

### Verify, deprecate, revert

**Verify** compares each applied record with its inventory (same uid and key, on the target type, everything still
there) and reports every exception, and every failed record. **Deprecate** (on request) marks the old type
`deprecated` (with the replacing package type) only when no record of it remains anywhere, no type is below it and no
reference field names it; a type is **never deleted** by a migration. **Revert** puts applied records back (through the
ledger for assets) and says so in their history.

## Who

Creating, previewing, applying, verifying and reverting a plan is for authenticated **instance administrators**
(`is_admin`), checked by the API. Records are judged with the administrator's grants in each record's own workspace;
writes are made in that workspace. Seeing a shared type gives no right over another workspace's records.

## When the standard type does not exist yet

`POST /v1/admin/type-proposals` (and the wizard's *Propose this one as a package type*) writes the custom type as a
package's YAML entry and checks it: the name must be new in every shipped package (otherwise migrate to that one), the
parent must be a type of the package or of one it depends on (or the dependency is named), field keys and option ids
must be stable identifiers, keys must not clash with inherited ones, references must point to package types. It gives
the package's next version and a checklist: add the entry, raise the version, run the checks, review, release, install —
then migrate the records. **ARGUS never rewrites a shipped package at runtime.**

## Limits

- One target type per plan: records of the types below a source go to the same target when included.
- Per-record decisions are *leave out* / *include*; field values are decided per value, not per record.
- References *from* other records are checked through typed reference fields and the packages' relation rules; free
  text that mentions a record is not.
- A revert restores fields and type; history entries written by the migration remain (they say what happened).
