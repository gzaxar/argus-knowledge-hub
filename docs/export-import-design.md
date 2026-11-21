# Export, import and the Git portability project

ARGUS is becoming the system of record for assets, documents and tickets. This document designs
its **institutional escape hatch**: a way to rebuild the authoritative information elsewhere, without
the original deployment, with ledger history, provenance, catalogue versions, permissions,
classifications and attachments intact. It also states how far each part has got.

* The normative rules are in [`asset-model-revision.md`](asset-model-revision.md) §25.
* Operating procedures are in [`operations.md`](operations.md) ("Portable exports and the Git
  portability project").
* Compatibility guarantees are in [`api-policy.md`](api-policy.md) ("Archive format").

## 0. Status

Each capability has one of these levels:

* **Proposed** — designed here, not built.
* **Implemented** — in the code (`backend/app/portability/`), without an automated test of its own.
* **Integration-tested** — implemented and covered by `backend/tests/test_portability.py`. Those tests
  use small fixtures, two or more fresh PostgreSQL databases at the migration head, a real bare Git
  repository and real keys.
* **Partially tested** — some paths are integration-tested, others are not (the cell says which).
* **Tested at production scale** — exercised on production-sized data, with timings recorded.
* **Production-approved** — the institution has approved it for production use.

**Nothing below is tested at production scale or production-approved.** §19 lists what must happen
first. The policy that governs approvals, step-up, content inspection, permissions and retention is
§20: the initial deployment runs the `trusted` policy, and each of its relaxations can be withdrawn
by configuration without changing the archive format.

| Capability | Status |
|---|---|
| `argus-archive/1`: manifest, NDJSON+zstd chunks, blob manifest, checksums, Ed25519 signature, JSON Schemas | Integration-tested |
| Watermark: per-table vector, canonical SHA-256, never-purged checkpoint sequence (§3) | Integration-tested (R17, A27) |
| Export modes `workspace`, `full`, `incremental`, `evidence-only` | Integration-tested |
| Export mode `backup-reference` | Proposed (refused with `not_generated`) |
| Dependency closure with explicit outcomes | Integration-tested (A25) |
| Restricted classes and fields left out, leak-free manifest | Integration-tested (A18) |
| Secret scanning of rows and of committed files | Integration-tested (A19, A20) |
| Content inspection of every blob before it is stored (§5.2) | Integration-tested (R1–R4) |
| Document readers: text, PDF, Office (docx, xlsx), e-mail, zip and tar | Tested with fixtures (`test_portability_policy.py`): each finds a planted secret and a classification marker; a reader not enabled keeps the file opaque |
| Uninspected content labelled in the manifest and accepted at import (§20) | Integration-tested (`test_portability_policy.py`) |
| Identity profiles (§5.1) | Integration-tested (R12, R13) |
| Data chunks as content-addressed artifacts; small review chunks in Git (§4, §9) | Integration-tested (R14–R16) |
| Envelope encryption of restricted exports (§7.1) | Integration-tested (R19, R20: one recipient, X25519 + AES-256-GCM) |
| Destinations approved per restricted class; unencrypted restricted export unavailable | Integration-tested (R19) |
| Step-up authentication: recent `auth_time`, or (trusted policy) a recent session and explicit confirmation | Integration-tested (R19 through the API; the confirmation path in `test_portability_policy.py`) |
| Portability policy: `trusted` and `strict` profiles, per-setting overrides, relaxations in the manifest and the audit (§20) | Integration-tested (`test_portability_policy.py`; the rest of the suite runs under `strict`) |
| Approved recipients chosen per restricted export | Integration-tested |
| Purpose → identity profile | Integration-tested |
| Per-repository deploy credentials (SSH key or token file from a secret) | Implemented |
| Directory artifact store (a mounted volume), read-only content-addressed files, behind the `ArtifactStore` interface | Integration-tested |
| S3 (Object Lock) and OCI artifact stores | Proposed |
| Git publication: signed commit and annotated tag, no force push; repository size measured | Integration-tested |
| Quarantine fetch: signed tag or commit only; hostile-tree checks; no checkout | Integration-tested (A5, A7, A21) |
| Moved-tag detection; Git LFS pointers resolved only from an independent store | Integration-tested (A5, A29) |
| Isolated staging database per import; per-chunk resume (§10.1) | Integration-tested (R22, A9) |
| Atomic promotion at finalization (§10.1) | Integration-tested (R23, R5) |
| Discard without touching active data or audit; audit of the attempt kept | Integration-tested (R6–R8) |
| Origin chain and local ingestion event (§10.2) | Integration-tested (R9–R11) |
| Import mode `clone` | Integration-tested end to end (A1) |
| Import mode `merge` | Integration-tested end to end (R5, R24, R10) |
| Import mode `restore` (empty instance, full-identity archive) | Integration-tested end to end (R24) |
| Import mode `selective` (chosen workspaces) | Integration-tested end to end (R24) |
| Import mode `evidence` | Integration-tested end to end (A24, R20) |
| Increments: chain by vector and manifest hash; equality with a checkpoint | Integration-tested (A10, A11, R18) |
| Evidence browsing by classification, counts of visible rows, audited reads | Integration-tested (R20) |
| Single-use, hashed, actor- and version-bound download tokens; no-store; log redaction | Integration-tested (R21) |
| Restore drill; drill results recorded in the audit and signed off | Integration-tested (A30); recording and sign-off implemented; schedule in operations |
| Measured full cycle (`python -m app.portability cycle`): duration, peak memory, promotion time | Implemented; not yet run at production size |
| Background jobs for long steps: queued, running, completed, failed; recovered after a restart | Integration-tested (`test_portability_policy.py`); no live progress or cancellation |
| Web pages (Administration → Portability), including jobs, policy, purpose, recipients and legal holds | Implemented; type-checked; no automated UI test |
| Committing reconciliation reports to the repository | Proposed |
| Foreign and legacy schemas through AI-assisted mapping | Proposed (§16) |
| Catalogue and policy changes reviewed in Git, then activated | Proposed |
| Retention (default 90 days) and legal holds on exports and imports | Integration-tested (`test_portability_policy.py`) |

## 1. Principles

1. The append-only ledger and the immutable domain history are authoritative.
2. Projections, indexes and derived graph edges can be rebuilt; they travel only to be compared.
3. Import and export never silently overwrite history, never bypass authority policies, never
   disclose restricted information.
4. Git versions, reviews and distributes. It is not the database, the operational backup, or the
   system of record.
5. ARGUS-to-ARGUS restoration is deterministic and needs no LLM.
6. AI may help only to map a foreign or legacy schema, under the AI Intake rules.

## 2. Four mechanisms, kept apart

| | Disaster-recovery backup | Full portable archive | Selective workspace package | Git portability project |
|---|---|---|---|---|
| What | `pg_dump`, WAL archive, attachments | `argus-archive/1`, mode `full` | `argus-archive/1`, mode `workspace` | manifests, schemas, review views, signatures, small chunks; data as artifact pointers |
| Restores | the same deployment, to a moment | ARGUS on another compatible deployment | chosen workspaces and decided dependencies | nothing by itself: it carries archives for review and distribution |
| Format | infrastructure-specific | open, documented, versioned | the same | Git plus content-addressed artifacts |
| In Git | never | its manifest and small review chunks; data chunks and blobs as artifacts | the same | — |
| Code | `app.ledger.ops` | `app.portability` | `app.portability` | `app.portability.gitrepo` |

The older `argus-export/1` bundle (`/v1/export`) stays. It is a viewer-filtered open-format view,
not an archive.

## 3. Export modes and the watermark

| Mode | Scope | Labels |
|---|---|---|
| `full` | every workspace | complete when nothing restricted or excluded is left out |
| `workspace` | chosen workspaces plus the decided closure (§8) | selective |
| `incremental` | the base export's scope: ledger rows of `(base vector, vector]`; record state at the new watermark | incremental |
| `evidence-only` | as `workspace`, meant to be read, not activated | selective, evidence-only |
| `backup-reference` | names a disaster-recovery backup | *proposed* |

**How the watermark is taken.** A short transaction:

1. takes `SHARE` locks on the ledger's sequenced tables, which waits for in-flight writers;
2. reads each table's highest `seq`;
3. allocates the next value of `portability_checkpoint_seq`, which is never purged or reset;
4. exports its snapshot.

The export then reads everything in a read-only transaction that imports that snapshot, and the
lock is released.

**The watermark is the full vector of per-table high-water marks:**

```json
"watermark": {"checkpoint_sequence": 184,
              "vector": {"ledger_claim_events": 49120, "ledger_decisions": 8217, "...": 0},
              "vector_sha256": "…", "snapshot_time": "…"}
```

* Its identity is the SHA-256 of the canonical vector, with sorted keys, integer values and no
  whitespace. It is never a sum: two vectors with the same sum are different checkpoints (R17).
* Tags carry the checkpoint number and a short form of the vector hash.
* Increments carry their base's exact vector, its hash and its manifest hash, and are refused on
  any mismatch (R18).
* The set of sequenced tables is part of the format: `importer.sequenced_families` in the manifest,
  and the capability `watermark-vector/1`. Adding a sequenced table is an explicit format change: a
  verifier refuses a vector with other keys.
* Rolled-back or discarded imports never touch the active ledger. So nothing makes a watermark or
  the checkpoint sequence move backwards (R8).

## 4. The archive format, `argus-archive/1`

```
<export-id>/
  manifest.json                      the manifest
  checksums.sha256                   every file below (encrypted bytes for an encrypted export)
  signature.json                     Ed25519 over the checksums and the manifest
  blobs.manifest.ndjson              one line per blob (encrypted for an encrypted export)
  workspaces.ndjson                  the workspaces in scope
  relation-registry.json             the relation registry and semantics, in stable form
  reconciliation.json                the exporter's counts, hashes and invariant summary
  <group>-<family>-<n>.ndjson.zst    chunks; most are artifacts, not files in Git (§9)
```

Each chunk line is an envelope, `{"f": family, "k": key, "d": row}`. It is JSON with sorted keys,
in UTF-8, compressed with zstd at level 10 in a single thread, so it is deterministic. A chunk holds
at most 50 000 rows.

Each chunk in the manifest records where it lives:

```json
{"file": "ledger-claim_events-000001.ndjson.zst", "storage": "artifact",
 "locator": "argus-artifacts://escrow/sha256/9f…", "sha256": "9f…", "bytes": 123456789,
 "content_sha256": "…", "rows": 50000, "encrypted": false}
{"file": "catalogue-types-000001.ndjson.zst", "storage": "git", "path": "catalogue-types-000001.ndjson.zst",
 "sha256": "…", "bytes": 4321, "content_sha256": "…", "rows": 146}
```

* **Where chunks live.** Only chunks of the catalogue, governance and access groups, of at most
  256 KiB, live in Git (`GIT_CHUNK_LIMIT`), and only for unencrypted exports. Every other chunk —
  identities, records, ledger, projections — is a content-addressed artifact.
* **What is signed.** The checksums cover every chunk wherever it lives, and the signature covers
  the checksums and the manifest. A missing or changed external chunk blocks verification (R15).
* **Families** are an allow-list, loaded in this order:

  | Group | Families |
  |---|---|
  | catalogue | types, icons |
  | identity | identities, as limited by the profile (§5.1) |
  | access | workspaces, roles, memberships, role bindings |
  | governance | policies, rulesets |
  | records | assets in every status, asserted relations, record subresources, tickets and their comments, history, links and watchers, documents and revisions, attachments, workflows, migration domains |
  | ledger | streams, source revisions, claims, every append-only event table, the migration map, reconciliation reports |
  | projection | not authoritative: compared, never loaded |

* **Local columns are never exported.** The only one is `recorded_at` (§10.2).

## 5. What never leaves, and what is checked

**Never selected.** These have no family:

* passwords;
* access, refresh and identity tokens;
* API keys;
* model-provider and import credentials;
* application settings;
* devices and push tokens;
* sessions;
* idempotency keys;
* upload sessions;
* notifications, caches, indexes and queues.

**Rows** are scanned for credential formats and for credential-named fields holding credential-like
values. **Committed files** are scanned again before the commit. Findings stop the export and are
reported by kind and location, never by value.

### 5.1 People: the identity profile

Historical attribution survives; personal data travels only as far as the profile allows. The
profile keeps three things apart:

* the **historical actor** (a stable actor reference, its type, and every reference to it from
  claims, decisions and records);
* **contact** data (e-mail, display name, username);
* **directory** data (DN, OIDC subject, source).

| Profile | Identities columns | Actor strings |
|---|---|---|
| `institutional_reference` (**default**) | user uid, OIDC subject, source, active | an e-mail of a known person becomes their uid; an unknown e-mail becomes a pseudonym |
| `pseudonymized` | a salted institutional pseudonym, a salted issuer hash | every person becomes their pseudonym (salt: `ARGUS_PORTABILITY_PSEUDONYM_SALT`, an institutional secret; the manifest records only its key id) |
| `anonymous_historical_actor` | a pseudonym from a per-export salt that is not kept | as pseudonymized; nothing links to a person outside the archive |
| `full_identity` | uid, subject, DN, e-mail, name, username | unchanged. **High-risk**: needs a second approver and step-up |

How the transform is applied:

* Except under `full_identity`, it is applied the same way to every string of every row,
  projections included: actor fields, person stream ids `person:<e-mail>@<ws>`, and free text. The
  archive therefore stays consistent with itself, and a person's actions stay grouped (R12).
* The manifest records the profile.
* On import, people arrive as historical references. Columns the profile did not export get
  placeholders (`<uid>@historical.invalid`).
* `restore` requires a `full_identity` archive, because it rebuilds the same instance.

**Limitation.** The *content* of blobs (a scanned form, a PDF) is not transformed. A selective
export of documents that name people still carries those names. The profile governs ARGUS's own
records, not the documents it holds.

### 5.2 Blobs: content inspection

Every blob is read and inspected before it is stored anywhere (`blob_scan.py`). That covers
source-revision contents, attachments, document files and icons.

* **What is read.** Readers are bounded and execute nothing: no macros, no scripts, no external
  entities or DTDs, no URL fetching.
  * text, JSON, YAML, XML and configuration files: as UTF-8;
  * e-mail: headers and parts, recursively;
  * PDF: the text layer and metadata (encrypted PDFs are uninspectable);
  * Office (docx, xlsx, pptx, odt): their XML parts, with macro projects detected and not run;
  * zip and tar archives: depth ≤ 2, ≤ 2000 entries, member and ratio limits;
  * legacy binary Office: not read (uninspectable).
* **What is found.** Secrets (the same detectors, plus `key = value` credentials in configuration
  text) and classification markers (confidential, personal data, export control, macros).
* **Outcomes.**
  * *Secret:* always refused. There is no override; correct the content at the source (R1, R2).
  * *Classification marker:* the content is treated as restricted and needs a decision:
    `accept_classified`, `exclude`, `classify_encrypt` (encrypted exports only) or `block`.
  * *Opaque* (images, unsupported binaries) or *uninspectable*: fails closed. It needs
    `approve_opaque`, `exclude`, `classify_encrypt` or `block` (R3). Decisions are per blob
    (`blob:<sha256>`) or for all opaque blobs (`opaque_blobs`).
* **Ordering.** Blobs pass inspection into a local staging area. Chunks and blobs are copied to the
  destination store only after every row, blob and file check has passed. A failure securely
  removes the staging area and the checkpoint directory, and nothing reaches Git or the artifact
  store (R4). Secure removal overwrites files before unlinking; on copy-on-write or flash storage
  that is best effort, and volume encryption is the real protection.
* **Before approval.** The approver sees the same inspection: findings, the decisions needed, and
  exclusions.

## 6. Restricted information

* An export names the restricted classes it includes. A record of a class not included is left
  out, together with every row naming it, and restricted fields are hidden.
* Rows naming a left-out record form the dependency `restricted_reference`, which needs the outcome
  `exclude_referrers` or `block`. In the manifest it carries neither count nor example (A18).
* **Including a restricted class has these requirements and effects:**
  * the destination repository is approved for that class (`ARGUS_PORTABILITY_RESTRICTED_DESTINATIONS`);
  * the destination has encryption recipients;
  * an approver other than the requester approves;
  * the approval and the generation have step-up;
  * the export is encrypted (§7.1).
* **Unavailable:** an unencrypted restricted export, and a restricted export to a general
  repository. ARGUS refuses both at request time (R19).
* Git has repository-level access only. A repository approved for a class must be readable only by
  people entitled to it. Removing a file from a later commit does not remove it from history.

## 7. Artifacts

Every artifact is stored by its SHA-256 (`argus-artifacts://<store>/sha256/<digest>`):

* data chunks;
* blobs;
* for an encrypted export, the ciphertext of both.

The **directory store** is implemented. It writes each file once and read-only (`0444`), and a
fetch verifies the size and the digest. *Proposed:* S3-compatible storage with Object Lock in
compliance mode for immutability, and signed OCI artifacts. Git LFS is never relied on: an LFS
pointer is resolved only from an artifact store that has the object, and verification fails
otherwise (A29).

Cloning the repository and fetching every locator the manifest names is sufficient to verify
(`tools/validate --artifacts store=/path`) and to rebuild (A28, R14).

### 7.1 Envelope encryption

* A new 256-bit data-encryption key per export.
* Every data chunk, every blob and the blob manifest are encrypted with AES-256-GCM. Each file gets
  a random 96-bit nonce, and its name (or digest) is the associated data.
* The key is wrapped per recipient, with X25519 (ephemeral) → HKDF-SHA256 → AES-256-GCM.
* The manifest records the algorithms, each recipient's name and key id, the ephemeral public key,
  the nonce and the wrapped key.
* The checksums are over the encrypted bytes. The signature covers the checksums and the manifest,
  so it covers the encryption metadata too.
* ARGUS holds recipients' *public* keys only. Private keys belong to their holders and are mounted
  only for an import session (`ARGUS_PORTABILITY_DECRYPTION_KEYS`); they are never stored in
  ARGUS, Git or the archive. An import without a recipient key stops at verification
  (`decryption_key_required`).
* The manifest of an encrypted archive still shows family names, row counts and plaintext content
  hashes. That metadata is visible to every reader of the destination repository; only approved
  repositories hold such archives.
* **Revocation is not cryptographic.** Revoking an export or its download tokens stops ARGUS from
  serving it. It does not stop anyone who already holds a copy and a recipient key. Removing a
  recipient affects later exports only.

## 8. Dependency closure

Each reference from the scope to something outside it is a dependency, grouped by rule and by the
workspace holding the target. The rules:

| Rule | What refers outside the scope |
|---|---|
| `merge_survivor` | a merged record, to its survivor |
| `relation_endpoint` | an asserted relation, to an endpoint |
| `derived_endpoint` | a derived relation, to an endpoint |
| `ticket_subject`, `ticket_involves`, `ticket_link` | a ticket, to its subject, involved records or linked tickets |
| `document_subject`, `document_relation` | a document, to its subject or related records |
| `claim_subject` | an exported stream's claim, to its subject |
| `foreign_claims` | another stream's claims, to an exported subject |
| `restricted_reference` | a row, to a left-out restricted record (§6) |

The outcomes are `include_workspace`, `external_reference`, `exclude_referrers` and `block`.
Nothing is decided silently. The catalogue, actors and subject decisions are included
automatically, and the manifest records that it did so.

## 9. The Git portability project

```
argus-portability/
  README.md  VERSION  .argus-portability.json
  format/      manifest.schema.json  record.schema.json  ledger.schema.json  blob-manifest.schema.json
               families/<family>.schema.json
  catalogue/   types.yaml  attributes.yaml  units.yaml  enumerations.yaml  relations.yaml
  governance/  authority-policy.yaml  workflows.yaml  retention-policies.yaml
  mappings/    jira-insight/  legacy-inventory/  foreign-schemas/
  exports/checkpoints/<export-id>/   manifest.json  checksums.sha256  signature.json
                                     blobs.manifest.ndjson  workspaces.ndjson  relation-registry.json
                                     reconciliation.json  (+ small review chunks)
  tools/       validate  inspect  dry-run  import  reconcile
```

**What goes in Git** is small and reviewable: schemas, views, manifests, checksums, signatures and
reports, plus catalogue, governance and access chunks of at most 256 KiB. Bulk data stays in the
artifact store, so repeated full checkpoints add kilobytes to Git history, not data volume (R16).
Each publication records the repository's size (`git count-objects`) and the number of files it
added, so growth can be measured and governed. An encrypted export puts no derived views in Git.

**Tags** name a checkpoint by number and vector hash, never by a branch:

```
export/full/<date>@cp<n>-<vector-hash-12>
export/workspace/<workspace>[+k]/<date>@cp<n>-<vector-hash-12>
export/increment/<full|workspace>/<date>@cp<n>-<vector-hash-12>
```

**Rules:**

* Each publication is one SSH-signed commit and one signed annotated tag, pushed without force.
* An existing checkpoint directory is never rewritten (`immutable`).
* Increments name their base, and their tag names the previous tag. An increment out of order, or
  with a gap, is refused.
* No Git merge resolves ledger conflicts.
* Import accepts only a signed tag or a signed commit named by its hash.
* Protected tags, no force push, code owners and short-lived credentials are server settings
  (operations.md).
* ARGUS refuses a tag that moved after it imported it.
* *Proposed:* CI on the repository.

## 10. The import pipeline

| # | Step | Status |
|---|---|---|
| 1 | Register: a registered repository name, never a URL from the caller | Integration-tested |
| 2 | Fetch into quarantine (a bare repository, no checkout, no hooks) | Integration-tested; short-lived credential injection proposed |
| 3–4 | Refuse unsigned, lightweight, branch or unexpected input; verify identity and signatures | Integration-tested |
| 5–7 | Manifest, external chunks fetched by locator, checksums, signature, artifacts | Integration-tested |
| 8 | Decrypt for this import session (recipient keys mounted for it) | Integration-tested |
| 9–10 | Format and capability compatibility; format migrations (none needed yet) | Integration-tested / Implemented |
| 11–13 | Catalogue, governance, closure, dry run | Integration-tested |
| 14 | Approvals: a second person for merge, restore and restricted content | Integration-tested |
| 15–21 | Load, blobs, rebuild, invariants — **in the import's staging database** (§10.1) | Integration-tested |
| 22–23 | Reconcile with the manifest; sign the report | Integration-tested |
| 24 | Commit the report to the repository | Proposed |
| 25 | Finalize: **one-transaction promotion into the active database** — or discard | Integration-tested |

### 10.1 The isolation boundary

Each import gets its own staging database, `argus_stage_<import>`, on the active server or on
`ARGUS_PORTABILITY_STAGING_URL`, migrated to the current head (`staging.py`).

1. **Seed.** The staging database receives a copy of the active rows the import is reconciled
   against. That is every row of the active workspaces the archive touches (for an increment, the
   chain's earlier state), the same origin's row map and chain, and every row these and the archive
   refer to, recursively.
2. **Load, rebuild, reconcile in staging.** This happens per chunk, with each finished step
   committed to staging and recorded on the import. An interrupted import resumes there (R22).
3. **Promotion.** At finalization ARGUS loads the same verified archive into the active database
   inside one transaction, rebuilds and reconciles there, writes the origin chain (§10.2), records
   the chain position, and commits — only if the result equals the staged reconciliation.
   * **Readers see all or nothing.** APIs, search, graph, AI retrieval, projectors and
     notifications read the active database, which holds nothing of the import until that commit
     (R5, R23).
   * **Concurrent exports** take their watermark lock before reading, so they wait for the
     promotion to commit or roll back.
   * **If promotion fails** (any difference from staging, any error), the transaction rolls back,
     and files it copied into the attachments store are removed. Active tables are byte-for-byte
     what they were (R6), and the import can be retried or discarded.
4. **Discard.** The staging database is dropped, and the staged files and quarantine are securely
   removed. Nothing in the active database is deleted, because nothing there was written. The
   append-only audit of the attempt stays (R7): requester, approvers, source repository, commit and
   tag, manifest hash, verification and dry-run results, checkpoints, the failure, the discard, its
   reason, who discarded it, and when. The audit purge (`allow_purge`) is not used by portability
   at all.

**What an import may write in the active database.**

* A workspace that is new here, or one this same origin wrote earlier (an increment). A workspace
  with independent local history is refused; map the archive's workspace to another id. No active
  workspace is ever partially modified.
* Shared catalogue rows, and people as references.

**Operational requirement.** The ARGUS database role needs `CREATEDB` on the staging server.

### 10.2 The origin chain

Imported history is never inserted into a local audit day that is already sealed.

* Every ledger event table has `recorded_at`: when the row was written *here*. For local events it
  equals `at`. For imported rows, `at` keeps the origin's time and `recorded_at` is the local
  ingestion time.
* The daily digest seals by `recorded_at` (and still hashes `at`). An import therefore lands in the
  day it arrives, and a previously sealed day never changes (R9, invariant I-PORT-8). A schema
  migration back-filled `recorded_at = at` for existing rows. That is the only write to existing
  audit rows, and it leaves sealed digests unchanged.
* At promotion ARGUS writes one append-only **local ingestion event** (`portability_events`, kind
  `ingested`). It records the origin instance, the export id, the origin checkpoint (manifest)
  hash, the **origin chain hash**, the per-family row counts and the watermark vector hash. The
  daily digest covers it.
* Every imported append-only ledger row gets an append-only `portability_origin_records` row:

  | Field | Meaning |
  |---|---|
  | `origin_instance_id` | the exporting instance |
  | `origin_family` | the family the row came from |
  | `origin_sequence` | the origin's `seq`, or the key for id-keyed rows |
  | `origin_recorded_at` | the origin's record time |
  | `origin_event_hash` | the SHA-256 of the row's exact archive line |
  | `origin_checkpoint_hash` | the manifest hash |
  | `local_table`, `local_key` | where the row lives here |
  | `local_ingested_at` | when it arrived here |
  | `local_ingestion_event_id` | the ingestion event that brought it |
  | `position` | its place in the chain |

  Sequence translation is deterministic: rows are loaded in archive order, so local sequences
  follow origin order. Claims, decisions, source revisions and conflicts keep their stable ids;
  local decisions refer to imported facts through those.
* `GET …/origin-chain` (`importer.verify_chain`) recomputes every imported row's archive line from
  the row here and compares it with its recorded hash. A changed row is found (R10, R11).
* By mode:
  * `restore` adopts the origin's instance identity in an empty deployment.
  * `clone` and `merge` keep their own identity, and give imported rows new local sequences.
  * `evidence` keeps the verified chain, and its hash, without activating anything.

## 11. Import modes and merge outcomes

| Mode | What it does |
|---|---|
| `restore` | an empty instance and a `full_identity` archive: it becomes the exporting instance (identity adopted) |
| `clone` | uids and provenance kept; own identity |
| `merge` | into an instance with its own work, in new workspaces or this origin's own; governance families only by decision |
| `selective` | only the workspaces chosen (`select_workspaces`); the catalogue comes as context (shared types may create a stub owner workspace with no records); references outside the selection follow `unresolved_references`; projections that derive from unselected records are left out of the comparison and counted |
| `evidence` | verified (and decrypted for the session) and kept read-only in the evidence store; nothing loaded |

| Situation | Outcome |
|---|---|
| identical row | skip |
| export already applied from this origin | identical history: nothing changes (A8) |
| next increment, exact base vector and manifest | resume the chain |
| new row | create |
| same key and origin, unchanged here since the last import | update (an increment) |
| same uid, divergent content | block (A12) |
| matching immutable external identifier | identity candidate; never a merge (A13) |
| same type id, other definition | a catalogue conflict to review; never overwritten (A14) |
| a column this release added, absent from an older archive and empty here | equal (`groups.email_domains`) |
| a derived column (`assets.site_shared`) | the archive's value; the flush guards that derive it stand aside while an archive loads |
| a `ledger` relation of a record with no ledger facts (no binding, no decision) | kept as the source had it: a rebuild has nothing to make it from |
| projections this release rebuilds differently (an archive from an older release, or stale at the source) | reconciliation fails, unless decision `projections: accept_rebuilt` and every authoritative row equal: then the rebuilt projections stand, and what differed, with any invariant failing on the archive's data, is listed under `accepted` in the signed report; so are the fields the ledger projects onto a record it manages (its name, type, status and the attributes a claim or decision names), rebuilt from the ledger where the source had overwritten them |
| an empty multi-value attribute (`[]`, `[[]]`, null) | nothing: equal to the key left out |
| missing reference | block, or `defer` by decision (listed in the reconciliation) |
| unknown person | a historical reference |

### 11.1 Evidence: who reads what

Evidence archives may hold identities and restricted history. Access works as follows:

* Being an instance administrator gives access to the evidence import. It does **not** give access
  to its restricted rows.
* Restricted rows, rows naming a restricted record, and, under a `full_identity` archive, the
  identities family are shown only to the institution's **evidence readers**
  (`ARGUS_PORTABILITY_EVIDENCE_READERS`, an explicit list, R20).
* Counts are of the rows the viewer may see. A family with nothing visible is not listed, and
  asking for it answers "no family".
* Every list and read is audited (`evidence_list`, `evidence_read`), with the family, the position
  and the number of rows returned.
* Evidence is **browsed only**: not searched, not indexed, not downloadable.
* Retention and legal holds of the evidence store follow the institution's records policy (§19).
  The store is a directory under `ARGUS_PORTABILITY_ROOT/evidence/<import>`.

## 12. Projections

The importer never loads a projection. In staging and again at promotion it:

1. replays identity bindings and stream heads from events;
2. runs the engine's rebuild;
3. replays event-sourced conflicts;
4. restores record timestamps;
5. compares every exported projection with what it rebuilt.

Finalization is blocked on any difference. The rebuild's own new events (identity candidates) are
reported.

## 13. Increments

* An increment states the ledger as a strict delta over its base vector.
* It states records as their state at the new watermark. Same-origin rows are updated only when
  unchanged here since they were imported, judged against the row map's hash of the row as the
  import left it.
* Set-valued families are restated whole, and same-origin rows absent from them are removed.
* Applying the chain equals a checkpoint at the final watermark (A10).

## 14. API and state machines

The API is under `/v1/portability/`, because `/v1/imports` belongs to the Jira, Insight and Git import
jobs.

```
POST /v1/portability/exports                      request and analyse (closure, content inspection)
GET  /v1/portability/exports[/{id}]
POST /v1/portability/exports/{id}/decisions       dependency, blob and identity-profile decisions
POST /v1/portability/exports/{id}/approve         step-up for high-risk
POST /v1/portability/exports/{id}/generate        step-up for restricted
POST /v1/portability/exports/{id}/publish-git
GET  /v1/portability/exports/{id}/manifest
GET  /v1/portability/exports/{id}/archive         the tar, with the caller's own credentials (preferred)
POST /v1/portability/exports/{id}/download-token  single use, 5 minutes, stored as a hash
GET  /v1/portability/exports/{id}/download        X-Download-Token header (or ?token=, redacted from logs)
POST /v1/portability/exports/{id}/download-tokens/revoke
POST /v1/portability/exports/{id}/revoke

POST /v1/portability/imports
POST /v1/portability/imports/{id}/fetch-git | upload | verify | dry-run | approve
POST /v1/portability/imports/{id}/execute | resume       in staging
POST /v1/portability/imports/{id}/finalize               atomic promotion
POST /v1/portability/imports/{id}/discard                {"reason": …}
GET  /v1/portability/imports/{id}/reconciliation | provenance | origin-chain
GET  /v1/portability/imports/{id}/evidence[/{family}]
GET  /v1/portability/config
```

The state machines are those of [`lifecycle.py`](../backend/app/portability/lifecycle.py).
`importing`, `rebuilding` and `reconciling` now happen in staging, and `finalized` is the
promotion.

* Every transition is checked, audited in the append-only `portability_events`, sealed in the
  digest chain, and idempotent.
* Errors use the one problem shape. Codes include `step_up_required`,
  `restricted_destination_required`, `encryption_unavailable`, `blob_review`, `secret_found`,
  `decryption_key_required`, `promotion_mismatch`, `missing_chunk` and `staging_failed`.

## 15. Security and key management

* **Who may act.** Only people: API tokens are refused. Administrators are needed for imports and
  for high-impact export steps.
* **Separation of duties.** A high-risk export, or a merge, restore or restricted import, needs a
  second person. High-risk exports are full, evidence-only, restricted-class and `full_identity`.
* **Step-up.** Approving a high-risk export, and generating a restricted one, needs a token whose
  `auth_time` is within `ARGUS_PORTABILITY_STEP_UP_SECONDS` (300 by default). The identity provider
  must send `auth_time`; ask for it with `max_age` or a dedicated re-authentication. The operator
  CLI runs with host access and counts as stepped-up; the audit records that.
* **Signing and verification keys.** One Ed25519 key, mounted from the secret store, signs
  checkpoints, commits and tags. Importers trust an allowed-signers file.
* **Encryption keys.** Recipients' X25519 public keys live in a file per destination
  (`ARGUS_PORTABILITY_RECIPIENTS`). Private keys are mounted only for import sessions.
* **Repositories** are registered by name. Credentials are never in a manifest. *Proposed:*
  short-lived tokens per operation.
* **Downloads.** Prefer `GET …/archive` with your own credentials. A download token is:
  * random, stored only as a SHA-256;
  * single use, and consumed when the download starts (a broken transfer needs a new token);
  * five minutes long;
  * bound to the export, the issuing actor and the exact manifest hash.

  Responses carry `Cache-Control: no-store` and `Referrer-Policy: no-referrer`. ARGUS redacts
  `token=` from its access logs; proxies must do the same (operations.md). Issuance, use, refusals
  (unknown, used, expired, revoked, another version) and revocation are audited.
* **Untrusted Git content.** No checkout, hooks off, no submodules, `transfer.fsckObjects`.
  Symbolic links, gitlinks, unsafe paths, executables outside `tools/` and oversized objects are
  refused. Reads are bounded, and nothing from a repository is executed.

## 16. Foreign and legacy schemas (proposed)

An exact ARGUS export is imported deterministically. A foreign or legacy schema goes to
`awaiting_mapping` and through the governed path of `asset-model-revision.md` §23.17. Not built.

## 17. User experience

**Administration → Portability** (implemented, checked by hand) shows, for each export and import:

* labels: complete or selective, full or incremental, signed, encrypted, Git-published,
  artifact-complete, verified, restorable, evidence-only;
* the dependency and content-inspection reports, with their decisions;
* the identity profile;
* the vector watermark;
* the Git tag, the repository size and what Git holds;
* the manifest;
* staging status, the dry run (with workspace selection for selective imports), the reconciliation
  and the origin-chain check;
* evidence browsing with visible counts;
* the audit timeline.

Downloads use the caller's own credentials. *Proposed:* live progress for long steps, which still
hold the request today.

## 18. Acceptance tests

`backend/tests/test_portability.py`, 27 tests. A1–A30 are the original acceptance tests; R1–R24 are
the additional requirements of the second revision.

| Tests | Covering |
|---|---|
| `test_A1_A2_A3_A28_…` | clone end to end; A15–A17 and A26 under the default profile |
| `test_A4_A5_A7_…`, `test_A6_A29_…`, `test_A21_…` (4 cases), `test_A22_…` | Git, tampering, LFS, hostile trees, decompression |
| `test_A8_A10_A11_…` | chains and increments |
| `test_A9_A23_R6_R7_R8_R22_…` | resume in staging; discard leaves active state byte-for-byte; the audit stays; watermarks and digests |
| `test_A12_A13_A14_…`, `test_A13_…` | merge outcomes |
| `test_A18_A19_A20_…` | restricted rows, secrets, no artifacts on failure |
| `test_A24_…`, `test_A25_…`, `test_A27_…`, `test_A30_…` | evidence, closure, watermark, drill |
| `test_R1_R4_…`, `test_R2_R3_…` | secrets and markers inside blobs; opaque content |
| `test_R5_R23_…` | invisibility before promotion; atomic promotion |
| `test_R9_R10_R11_…` | sealed days unchanged; the origin chain after clone and merge |
| `test_R12_R13_…` | identity profiles |
| `test_R14_R15_R16_…` | external chunks; nothing bulky in Git |
| `test_R17_…`, `test_R18_…` | watermark identity; wrong base vector |
| `test_R19_R21_…` (API) | destinations, encryption, step-up, single-use downloads, evidence classification (R20) |
| `test_R24_…` | restore, merge and selective end to end |

## 19. Limits, open decisions and blockers

**Compatibility limits.**

* An importer refuses unknown families, unknown columns and an unknown set of sequenced tables.
* Attribute values naming other records are values, not dependencies.
* Blob content is not transformed by identity profiles.
* The knowledge index and search are rebuilt by their own jobs after promotion.
* Chunks are built in memory per family; a streaming writer is needed for very large families.
* Promotion re-runs the load in one transaction. For very large imports that transaction is long,
  and its size and lock duration must be measured.

**Decisions for stakeholders.** Decided (2026-10); recorded with their implementation in §20.

**Blockers before production activation**, and how each is resolved under the initial policy (§20.2).
"Open" means work an operator still has to do in the target environment.

1. Step-up: `auth_time` is preferred; without it a recent session plus explicit confirmation is
   accepted (configurable to strict). *Resolved in code.*
2. Artifacts on a mounted volume, accepted if the volume is backed up; archives are checksum-protected;
   the `ArtifactStore` interface is in place for S3, OCI and immutable storage later. *Resolved in code;
   the volume's backup is open.*
3. Branch protection against deletion and force-push on the portability repository; one maintainer
   approves. *Open (Git-server settings, operations.md).*
4. Keys in a Kubernetes Secret, replaced by hand, rotated yearly. *Procedure in operations.md; open.*
5. A narrowly scoped deploy credential per repository, from a secret, rotated periodically.
   *Resolved in code (`ARGUS_PORTABILITY_REPOSITORY_KEYS` / `_TOKENS`); provisioning open.*
6. A dedicated importer role that can create and drop only `argus_stage_*` databases; staging
   databases excluded from backups. *SQL in operations.md; open.*
7. One full cycle on production data or an equivalent generated set, with duration, peak memory and
   promotion time recorded; that sets the initial supported size. *Command implemented
   (`cycle`); the run is open.*
8. Only readers with tested fixtures are enabled; other formats stay opaque with a warning.
   *Resolved.*
9. Downloads with the person's own credentials or the `X-Download-Token` header; query-string tokens
   off unless enabled together with the operator's confirmation that proxies redact them.
   *Resolved.*
10. A job page with queued, running, completed and failed states, refreshed by polling. *Resolved;
   live progress and cancellation later.*

## 20. Policy

ARGUS begins with a simple, permissive policy for an internal, authenticated, trusted environment.
Every control that an institution may want stricter is a setting of `app.portability.policy`, so
stricter rules can be introduced **without changing the archive format or the import workflow**:
policy decides gates, warnings and labels, never what an archive contains or how it is read. An
archive made under one policy verifies and imports under any other.

Rules that do not depend on policy: secrets are never exported; restricted classes leave only
encrypted, for approved recipients at an approved destination; nothing that did not reconcile is
promoted; every step is audited.

### 20.1 The two profiles

`ARGUS_PORTABILITY_POLICY` picks `trusted` (the default) or `strict`. Any single setting can be
overridden with `ARGUS_PORTABILITY_POLICY_<SETTING>`, for example
`ARGUS_PORTABILITY_POLICY_SEPARATION_OF_DUTIES=1`. `python -m app.portability policy` and
`GET /v1/portability/config` show the policy in force and its **relaxations**: every setting that
differs from `strict`.

| Setting | `trusted` (initial) | `strict` |
|---|---|---|
| `separation_of_duties`: a second person approves high-risk work | no — one administrator suffices | yes |
| `step_up` | `session_confirmation`: `auth_time` if sent; otherwise a session issued within `session_seconds` (30 min) plus an explicit confirmation | `strict`: `auth_time` within `step_up_seconds` only |
| `full_identity_high_risk` | no — the profile for backup, restore and migration | yes |
| `opaque_blobs`, `uninspectable_blobs` | `allow_with_warning`: travel, labelled uninspected | `require_decision` |
| `classified_blobs` | `require_decision` | `require_decision` |
| `blob_readers` | readers with tested fixtures: text, email, pdf, office, archive | same |
| `export_permission`: the right needed on each workspace | `read` | `approve` |
| `import_permission` | `workspace_admin`: administrators of every existing target workspace; new workspaces and `restore` need an instance administrator | `instance_admin` |
| `evidence_workspace_admins`: workspace administrators read their workspace's restricted evidence rows | yes | no — named evidence readers only |
| `query_tokens` | off; enabling also needs `proxy_redacts_tokens` | off |
| `retention_days` | 90 | 90 |

**Visibility.** Each archive's manifest records the policy it was made under (`policy`, with its
relaxations) and the export's `purpose`; the request, approval and import approval events record the
policy profile, its relaxations and whether the approver was the requester (`self_approved`). The web
pages show the policy in force and the policy an archive was made under.

### 20.2 Stakeholder decisions (2026-10) and their implementation

1. **Retention.** Archive files, quarantine, staging databases and evidence copies are deleted after
   90 days (`retention_days`) by `python -m app.portability cleanup` (a daily job); the export or
   import record, its audit, Git history and published artifacts are kept. A **legal hold**
   (`POST …/legal-hold`, or the CLI) suspends deletion; placing and releasing it are audited, and a
   hold needs a reason.
2. **Keys and approval.** ARGUS administrators manage the keys. One authorized administrator approves
   an export or an import (`separation_of_duties=false`); requiring a second approver is one setting.
3. **Storage.** The institution's existing Git service holds the portability repository; large
   artifacts go to a mounted volume (`dir:` store). S3, OCI, replication and Object Lock are later
   `ArtifactStore` backends; the locator scheme keeps old archives readable.
4. **Who.** Authenticated people export what they can read (`export_permission=read`); a full export,
   restricted classes or `full_identity` still need an instance administrator. People import into
   workspaces they administer. A restricted export names its **approved recipients**, chosen by an
   administrator from those configured for the destination. Workspace administrators read the
   evidence records of their own workspace; the named evidence readers read all of them.
5. **People.** A `purpose` sets the default identity profile: `backup`, `restore` and `migration` →
   `full_identity`; `analysis` and `external_sharing` → `pseudonymized`; `evidence` →
   `institutional_reference`. The institutional pseudonymization salt is permitted and comes from a
   secret (`ARGUS_PORTABILITY_PSEUDONYM_SALT`).
6. **Opaque files** travel, listed in `manifest.blobs.uninspected` with the reason and whether policy
   or a decision let them through, and the archive carries the `uninspected_content` label. Importing
   them needs an administrator to accept the warning (`acknowledge_uninspected`). Under a stricter
   policy they are held for a decision, as before.
7. **Restore drills** every six months and after a substantial archive-format change:
   `python -m app.portability drill` records its result in the audit; one ARGUS administrator signs it
   off with `drill-signoff`.

### 20.3 Long steps as jobs

Generating, publishing, fetching, verifying, executing and finalizing accept `?background=true` and
return a job (`queued → running → completed | failed`) that the web pages poll at
`GET /v1/portability/jobs/{id}`. A subject runs one job at a time. Jobs left running by a restart are
marked failed (`interrupted`); every step is idempotent and an import resumes from its staging
checkpoints. The API and CLI still run steps synchronously. Not provided yet: live progress within a
step, cancellation, a separate worker pool.

