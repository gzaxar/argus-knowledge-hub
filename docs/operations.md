# Operating ARGUS

What has to run, and how to prove it works, for ARGUS to hold data as the
system of record (asset-model-revision §19).

## Scheduled jobs

| When | Command | Why |
|---|---|---|
| continuously (or every minute) | `python -m app.ledger derive-worker` | runs the derived links a user edit queued, when `LEDGER_USER_EDIT_DERIVE=manual` (the default `background` runs them in the API process) |
| every 5–15 minutes | `python -m app.ledger escalate` | escalates tickets that outstayed their state's SLA; sends pending notifications by e-mail when `SMTP_HOST` is set; removes expired idempotency keys and unfinished uploads (`docs/api-policy.md`) |
| daily, after midnight UTC | `python -m app.ledger audit-digest` | seals yesterday's audit events into the digest chain. **Copy the printed digest outside ARGUS** (a ticket in another system, a signed e-mail, write-once storage) |
| weekly | `python -m app.ledger verify-audit` | recomputes the chain; a non-zero exit names the first altered day |
| daily | `python -m app.ledger backup --out /backups` | base backup: `pg_dump`, the attachments, and a manifest with checksums and row counts |
| quarterly (at least) | `python -m app.ledger rehearse-restore /backups/argus-….manifest.json` | restores into a scratch database, checks counts and the audit chain, drops it. Keep the JSON report as evidence |
| monthly (proposed), and after every upgrade | `python -m app.portability drill --repository escrow` | imports the newest signed full checkpoint into a scratch database through staging and promotion, reconciles, drops it. Keep the JSON report as evidence (see "Restore drills" below) |

E-mail: `SMTP_HOST`, `SMTP_PORT` (25), `SMTP_FROM`, and `ARGUS_URL` for links.
Notifications are always stored in-app; e-mail is a delivery channel.

## Point-in-time recovery (RPO ≤ 15 min, RTO ≤ 4 h)

The daily dump alone gives a one-day RPO. For the §19 target, run Postgres
with continuous WAL archiving:

```
# postgresql.conf
wal_level = replica
archive_mode = on
archive_command = 'test ! -f /wal-archive/%f && cp %p /wal-archive/%f'
archive_timeout = 300          # a segment at least every 5 minutes
```

Take a physical base backup weekly (`pg_basebackup -D /base/$(date +%F) -Ft -z -X stream`).
To recover to a moment: restore the latest base backup before it into a new
data directory, then

```
# postgresql.conf of the restored cluster
restore_command = 'cp /wal-archive/%f %p'
recovery_target_time = '2026-10-03 14:25:00+00'
recovery_target_action = 'promote'
```

`touch recovery.signal`, start Postgres, and it replays WAL to that moment.
Restore the attachments directory from the tarball of the same day, then run
`python -m app.ledger verify-audit` and `python -m app.ledger backfill-checksums`
before opening the instance. Rehearse this in staging at least quarterly (§17.4
entry criterion 5) and record the elapsed time against the 4-hour RTO.

A damaged ARGUS is recovered this way — never by restoring Jira (§17.7).

## Export and load (escrow, moving instances)

*The open-format bundle below predates the portable archive. For escrow and moving instances, use
the portable export (next section), which is signed, watermarked and reconciled.*

```
python -m app.ledger export --workspace sparc --out /escrow/sparc      # every grant
python -m app.ledger load --dir /escrow/sparc --attachments /escrow/sparc-files   # into an empty instance
```

The bundle is JSON lines per kind (workspace, schemas, assets, tickets,
comments, relations, attachments, ledger). `load` checks every attachment
against its SHA-256 first and refuses a mismatch. Links to records of other
workspaces are loaded when the other workspace is already there, and listed
otherwise. `tests/test_readiness_ops.py` loads a bundle into a freshly
migrated database and compares a fingerprint of everything.


## Portable exports and the Git portability project

*Status: integration-tested as a vertical slice; not tested at production scale; not
production-approved. [`export-import-design.md`](export-import-design.md) §0 and §19 list what is
still proposed and what blocks production.*

### Backup versus portable export

| | Backup (above) | Portable export |
|---|---|---|
| For | recovering **this** deployment to a moment | rebuilding ARGUS **elsewhere**: escrow, preservation, a new deployment, a test environment, a domain transfer |
| Contains | the database as it is, WAL, the attachments directory | the ledger, domain records and their history, catalogue, governance, people as references, blobs; projections only for comparison |
| Format | `pg_dump`, Postgres WAL | `argus-archive/1`, open and versioned |
| In Git | never | manifests, schemas, signatures and small review files; data chunks and blobs as content-addressed artifacts |
| Restores with | `pg_restore`, PITR | `python -m app.portability import …`: quarantine, dry run, staging, atomic promotion |

Keep both. A portable export gives no 15-minute RPO, and a backup cannot be read without this
deployment.

### Configuration

| Variable | Meaning |
|---|---|
| `ARGUS_PORTABILITY_UI_CONFIG` | `on` (default) or `off`: whether administrators may register repositories, trusted keys and the signing key in the web app (*Administration → Portability → Set-up*). What the variables below set always comes first and is read-only there; off, what was registered in the web app is kept but not used |
| `ARGUS_PORTABILITY_ROOT` | working area: `exports/`, `quarantine/`, `staging/`, `evidence/`, `work/`, `drills/` (default `/data/portability`) |
| `ARGUS_PORTABILITY_REPOSITORIES` | `name=url,…`: the only repositories ARGUS publishes to or fetches from |
| `ARGUS_PORTABILITY_ARTIFACT_STORES` | `name=/path,…`: content-addressed artifact stores (mounted volumes) |
| `ARGUS_PORTABILITY_SIGNING_KEY` | the Ed25519 signing key (OpenSSH format), mounted from the secret store |
| `ARGUS_PORTABILITY_SIGNER` | the principal written in signatures and allowed-signers files |
| `ARGUS_PORTABILITY_TRUSTED_KEYS` | the allowed-signers file of keys an import trusts |
| `ARGUS_PORTABILITY_RESTRICTED_DESTINATIONS` | `repository=class\|class,…`: repositories approved for restricted classes |
| `ARGUS_PORTABILITY_RECIPIENTS` | `repository=/path,…`: the X25519 recipient public keys of each approved destination |
| `ARGUS_PORTABILITY_DECRYPTION_KEYS` | a directory of recipient private keys, mounted **only for an import session** |
| `ARGUS_PORTABILITY_PSEUDONYM_SALT` | the institutional secret of the `pseudonymized` identity profile |
| `ARGUS_PORTABILITY_EVIDENCE_READERS` | the user ids or e-mails that may read restricted rows of evidence archives |
| `ARGUS_PORTABILITY_STEP_UP_SECONDS` | how recent a sign-in must be for high-risk approval and restricted generation (300) |
| `ARGUS_PORTABILITY_POLICY` | `trusted` (default) or `strict`; see [`export-import-design.md`](export-import-design.md) §20 |
| `ARGUS_PORTABILITY_POLICY_<SETTING>` | overrides one policy setting, e.g. `_SEPARATION_OF_DUTIES=1`, `_OPAQUE_BLOBS=require_decision`, `_RETENTION_DAYS=180`, `_BLOB_READERS=text,pdf` |
| `ARGUS_PORTABILITY_REPOSITORY_KEYS` | `repository=/path,…`: the SSH deploy key of each repository, mounted from a secret |
| `ARGUS_PORTABILITY_SSH_KNOWN_HOSTS` | a known_hosts file pinning the Git server's host key, used with deploy keys |
| `ARGUS_PORTABILITY_REPOSITORY_TOKENS` | `repository=/path,…`: a token file per HTTPS repository, answered through `GIT_ASKPASS` |
| `ARGUS_PORTABILITY_STAGING_URL` | the PostgreSQL server for staging databases (default: the active one) |
| `ARGUS_PORTABILITY_GIT_NAME`, `ARGUS_PORTABILITY_GIT_EMAIL` | the committer of export commits (a service identity) |
| `ARGUS_INSTANCE_NAME` | this deployment's name in manifests |

The API image includes `git` and `openssh-client`. Nothing from Git is checked out or executed.

**The database role.** Each import creates `argus_stage_<import>`, migrates it to the current head,
and drops it at finalization, discard or retention cleanup. Use a **dedicated importer role** for
this, not the application's normal role, set as `ARGUS_PORTABILITY_STAGING_URL`:

```sql
CREATE ROLE argus_importer LOGIN CREATEDB PASSWORD '…';   -- from the secret store
-- It owns only the staging databases it creates, so it can drop only those.
REVOKE CREATE ON DATABASE argus FROM argus_importer;      -- no objects in the active database
```

`CREATEDB` lets the role create any database; restrict it further with a dedicated staging server, or
by monitoring that its databases are all named `argus_stage_*`. Exclude `argus_stage_*` from backups
(for example, a `pg_dump` loop over `datname NOT LIKE 'argus_stage_%'`, or a separate server that is
not backed up).

**Policy.** The deployment runs the `trusted` policy unless `ARGUS_PORTABILITY_POLICY=strict`.
`python -m app.portability policy` prints the policy and its relaxations, also shown under
Administration → Portability. Making a rule stricter is a configuration change and a restart; it
does not affect archives already made.

### In the web application

**Administration → Portability** runs the same lifecycles:

* **Exports.** Request with a scope, destination, identity profile and any restricted classes (only
  towards approved destinations). Then give dependencies and blobs their outcome, approve (another
  administrator, signed in recently, for high-risk exports), generate, publish to Git, download
  with your own credentials, or revoke.
* **Imports.** Register a tag or upload a checkpoint, then fetch, verify, dry run (with decisions:
  workspace mapping, workspace selection for selective imports, unresolved references,
  governance), approve, execute or resume in staging, and finalize (atomic promotion) or discard
  with a reason.

For a development instance, `docker compose exec api python -m app.portability dev-setup` creates a
throwaway signing key, its allowed-signers file, a local bare repository `escrow-dev` and an artifact
store `vault-dev` under the `portability` volume. Never use that key for anything real.

### Setting up the repository and its protection

1. **Create the repositories on the institutional Git server**, one per audience:
   * a general one;
   * a separate one for each set of restricted classes it is approved for.
2. **Protect them on the server.**
   * Protected tags `export/*`: cannot be deleted, moved or re-created.
   * Protected `main`: no force push.
   * Code owners for `catalogue/`, `governance/` and `mappings/`.
   * Protect `main` and the tags against deletion and force-push. One authorized maintainer may
     approve changes to protected paths initially.
   * Deploy credentials: one narrowly scoped deploy key or token per repository, write access for
     exporting instances and read-only for importing ones. Store it as a secret, mount it, and point
     `ARGUS_PORTABILITY_REPOSITORY_KEYS` (SSH) or `ARGUS_PORTABILITY_REPOSITORY_TOKENS` (HTTPS) at it.
     Rotate it periodically. Short-lived workload credentials can come later.
3. **Register them**:
   `ARGUS_PORTABILITY_REPOSITORIES=escrow=ssh://git@git.example/argus/escrow.git,escrow-costs=ssh://…`,
   and approve the restricted one with `ARGUS_PORTABILITY_RESTRICTED_DESTINATIONS=escrow-costs=costs|personnel`.
4. **Set the service identity of export commits** (placeholders):
   ```
   ARGUS_PORTABILITY_GIT_NAME="[IL_TUO_NOME]"
   ARGUS_PORTABILITY_GIT_EMAIL="[Inserisci Qui La Tua Email]"
   ```
5. **Record the retention and legal-hold policy** for the repository's history, the artifact store
   and the evidence store. Removing a file from a later commit does not remove it from history.
6. **Watch growth.** Each publication records the repository size (`git count-objects`) and how many
   files it added, on the export (`git.repository_bytes`, `git.files_in_git`). Bulk chunks and
   blobs never go into Git.

### Key management

* **Signing key.** Generate it once, in the secret store:
  `ssh-keygen -t ed25519 -N '' -C argus-portability -f argus-portability`.
  * Mount the private key into the API container (`ARGUS_PORTABILITY_SIGNING_KEY`, mode 0600). It
    never goes into a repository, an image or the database.
  * Distribute the public key as an allowed-signers line
    (`argus-portability namespaces="git,argus-archive" ssh-ed25519 AAAA…`) to every importing
    instance and independent verifier.
  * Rotate by adding the new key everywhere first, then switching, then removing the old key after
    its last checkpoint expires.
* **Recipient keys (encryption).** Each person or system entitled to decrypt a restricted
  destination's exports holds an X25519 key pair. Create one with
  `python -m app.portability recipient-key --name escrow-officer --out ./escrow-officer.key`, on the
  holder's machine, not on the ARGUS host. Put the printed public line in the destination's
  recipients file (`ARGUS_PORTABILITY_RECIPIENTS`). The private key stays with its holder, and is
  mounted into `ARGUS_PORTABILITY_DECRYPTION_KEYS` only for the duration of an import that needs it.
  * **Revocation is not cryptographic.** Revoking an export or its download tokens stops ARGUS
    serving it. It does not stop anyone who already holds a copy and a recipient key. Removing a
    recipient affects later exports only.
* **Pseudonym salt.** `ARGUS_PORTABILITY_PSEUDONYM_SALT` is an institutional secret; changing it
  changes every pseudonym in later exports.
* **Where keys live.** All of these use the deployment's secret mechanism: a Kubernetes Secret
  mounted read-only into the API pod. KMS or an HSM is optional. One Secret, for example
  `argus-portability`, holds:
  * `signing_key`;
  * `allowed_signers`;
  * the recipients files;
  * repository deploy keys or tokens;
  * the pseudonym salt.

  Decryption keys go in a separate Secret, mounted only for an import session.
* **Annual rotation** (and at once on suspected compromise). An ARGUS administrator:
  1. generates the new signing key and adds its allowed-signers line on every importing instance;
  2. replaces `signing_key` in the Secret, restarts the API, and runs one export and the restore
     drill;
  3. removes the old allowed-signers line once no checkpoint signed with it is still needed;
  4. replaces repository deploy credentials the same way, revoking the old ones on the Git server.

  Record each rotation as a change in the deployment's runbook.

### External artifacts

* Data chunks and blobs are written to the artifact store named in the export, by SHA-256, and are
  read-only.
* They are written **only after the export has passed every check**: rows and files scanned,
  every blob inspected and decided, and no file missing. A refused export leaves nothing in the
  store.
* Publish the store to institutional object storage (S3 with Object Lock in compliance mode) or an
  archive by copying the `sha256/<aa>/<digest>` files unchanged. They are immutable and named by
  content.
* Keep the store as long as the repository history that references it.

### A full export, and increments

```
python -m app.portability export --mode full --repository escrow --store vault --by alice@example.org \
       [--purpose backup|restore|migration|analysis|external_sharing|evidence] \
       [--identity-profile institutional_reference|pseudonymized|anonymous_historical_actor|full_identity] \
       [--classification costs --recipient escrow-officer]   # restricted: approved recipients
python -m app.portability approve  exp-… --by bob@example.org          # trusted policy: may be the requester
python -m app.portability generate exp-… --by bob@example.org
python -m app.portability publish  exp-… --by bob@example.org
```

* **Workspace exports.** The analysis lists dependencies outside the scope and blobs that need a
  decision. Give each an outcome with `--decide <id>=<outcome>`:
  * dependencies: `include_workspace`, `external_reference`, `exclude_referrers` or `block`;
  * blobs (`blob:<sha256>`, or `opaque_blobs` / `classified_blobs` for all of a kind):
    `approve_opaque`, `accept_classified`, `exclude`, `classify_encrypt` (encrypted exports only)
    or `block`.

  A secret found inside a file is never overridable: correct the content in ARGUS and request a
  new export.
* **Restricted classes** (`--classification costs`) are accepted only towards a destination approved
  for them, with recipients configured; the export is then encrypted.
* **Identity profile.** The default, `institutional_reference`, exports user uids and subjects and
  no e-mail, DN or names. `full_identity` is high-risk, and is needed for a `restore`.
* **Increments** take `--mode incremental --base exp-…`. They carry the base's exact watermark
  vector, and their tag names the base's tag. Run them in order. A periodic new full checkpoint
  does not remove the chain.

### Signed tags

* Each publication is one signed commit and one signed annotated tag:
  * `export/full/<date>@cp<n>-<vector hash>`
  * `export/workspace/<ws>/<date>@cp<n>-<vector hash>`
  * `export/increment/…`
* Check a tag with `git -c gpg.format=ssh -c gpg.ssh.allowedSignersFile=allowed_signers verify-tag <tag>`.
* Never move or delete one. ARGUS refuses a tag that moved after it imported it.

### Verification without ARGUS

```
git clone --branch <tag> <repository> argus-portability
argus-portability/tools/validate argus-portability/exports/checkpoints/<export-id> \
    --trusted allowed_signers --artifacts vault=/mnt/argus-artifacts
argus-portability/tools/inspect argus-portability/exports/checkpoints/<export-id>
```

`validate` fetches every external chunk and blob from the given stores, and checks them against the
signed checksums. An encrypted archive is verified as stored, without decrypting it.

### Downloads

* Prefer **Download** on the export page (or `GET …/archive`). It uses your own credentials and
  puts no capability in a URL.
* A token in the query string (`?token=`) is refused (`query_token_disabled`) unless
  `ARGUS_PORTABILITY_POLICY_QUERY_TOKENS=1` **and** `ARGUS_PORTABILITY_POLICY_PROXY_REDACTS_TOKENS=1`.
  The second variable is your confirmation that every proxy in front of ARGUS redacts `token`.
* For an out-of-band tool, `POST …/download-token` gives a token that is:
  * single use (consumed when the download starts; a broken transfer needs a new token);
  * valid for five minutes;
  * bound to the export, the issuer and the archive version;
  * stored only as a hash.

  Send it as the `X-Download-Token` header.
* ARGUS redacts `token=` from its own access logs. **Configure the reverse proxy to do the same**
  (for nginx, log `$uri` rather than `$request_uri` for `/v1/portability/`), and never log request
  headers.
* `POST …/download-tokens/revoke` revokes the unused tokens of an export. Issuance, use, refusals
  and revocation are all audited.

### Restore drills

`python -m app.portability drill --repository escrow` does the following:

1. fetches the newest `export/full/*` tag;
2. creates a scratch database at the current schema;
3. imports, stages, reconciles and promotes into it;
4. drops it.

Exit status 0 means it passed. The result goes into the audit (`portability_events`, subject
`drill`) and is printed with its `drill_id`. **Run it every six months and after any substantial
archive-format change.** One ARGUS administrator records the sign-off:

```
python -m app.portability drill --repository escrow --by alice@example.org
python -m app.portability drill-signoff drill-… --by alice@example.org --note "H2 2026 drill, reviewed"
```

**Establishing the supported size.** Run one complete measured cycle on production data, or on an
equivalent generated dataset, in a non-production deployment:

```
python -m app.portability cycle --repository escrow --store vault --by alice@example.org
```

It runs a full export (purpose `backup`), publishes it, and restores it into a scratch database. It
records the duration, peak memory and promotion-transaction time in the audit. The figures set the
initial supported size; record them in the deployment's runbook.

### Importing: dry run, staging, promotion

```
python -m app.portability import --mode clone --repository escrow --ref export/full/2026-10-03@cp184-1a2b3c4d5e6f --by carol@example.org
python -m app.portability step imp-… fetch    --by carol@example.org   # quarantine: signed tag, safe tree
python -m app.portability step imp-… verify   --by carol@example.org   # checksums, signature, external chunks, blobs
python -m app.portability step imp-… dry-run  --by carol@example.org   # what would happen, row by row
python -m app.portability step imp-… approve  --by dave@example.org    # --accept-uninspected if the archive carries opaque files
python -m app.portability step imp-… execute  --by dave@example.org    # in the staging database
python -m app.portability step imp-… finalize --by dave@example.org    # one-transaction promotion
```

**Modes.**

| Mode | Use |
|---|---|
| `restore` | an empty instance and a `full_identity` archive; the instance takes the archive's identity |
| `clone` | uids kept; this instance keeps its own identity |
| `merge` | alongside this instance's own work: new workspaces, or this origin's own |
| `selective` | choose the archive's workspaces in the dry run |
| `evidence` | read-only; nothing loaded |

**Encrypted archives.** Mount a recipient key into `ARGUS_PORTABILITY_DECRYPTION_KEYS` before
`verify`, and remove it after `finalize`.

**Execution** happens entirely in the import's staging database. It is loaded per chunk, then
rebuilt and reconciled. An interrupted run resumes there with `execute` (or API `resume`). The
active instance sees nothing of it: not its users, search, graph, AI retrieval, notifications nor
exports.

**Finalization** promotes the import in one transaction. ARGUS loads it into the active database,
rebuilds and reconciles there, writes the origin chain and one local ingestion event, and commits
only if the result equals the staged reconciliation. On any difference or error nothing is
committed, and the import stays `ready_to_finalize` with the error, to retry or discard.

**After finalization**, `GET …/origin-chain` recomputes every imported ledger row against its origin
hash.

**Imported history.** Imported events keep their original `at` and are recorded here at ingestion
time (`recorded_at`). The daily digest seals by `recorded_at`, so `verify-audit` stays green: no
sealed day changes.

### Rebuilding an installation from Git

A database backup (above) is the first choice for recovering the *same* installation. Without one, an
empty installation is filled from the last full export in the portability repository. The user guide's
"Rebuild an installation from its archive" gives the steps; for operations, the pitfalls are:

- **Trust anchors are inside the installation.** Keep, outside ARGUS, the allowed-signers line of every
  installation's signing key. Back up the Secret holding the production signing key
  (`<existingSecret>`, mounted at `/etc/argus/portability`). A lost local development key can only be
  replaced; archives it signed stay verifiable from the kept public line.
- **Self-contained archives.** Exports meant for recovery keep their data in the repository
  (`artifact_store: @repository`). An artifact store on the lost installation's volume is gone with it.
- **New deploy key.** The repository registration is in the database: the new installation makes a new
  deploy key, which must be added to GitHub/GitLab; remove the old one.
- **Empty means no records.** *Restore* needs an empty instance; the default workspace a new
  installation creates (`ARGUS_DEFAULT_WORKSPACE`, default `main`) does not count while nothing is in it.
- **Not carried:** AI settings, import configurations, API and robot tokens, devices, the knowledge index.
  Re-issue robot tokens (for example `argus-olog-upload` in each facility's namespace).

### Discarding or cleaning up an import

```
python -m app.portability step imp-… discard --by dave@example.org --reason "wrong checkpoint"
```

A discard does the following:

* drops the staging database;
* securely removes staged files, quarantine and any evidence copy;
* marks the import `discarded`.

**The active database is not touched, because nothing there was written. The import's audit trail
stays, append-only.** No audit purge is used. A finalized import cannot be discarded: correct it
with ledger decisions.

### Periodic exports

An administrator can repeat a published Git export at an interval (the export's page, *Repeat periodically*;
`/v1/portability/schedules`; `app/portability/schedules.py`). Each run makes a new export with the same scope,
destination, outcomes and identity profile — an increment on the last publication, or a complete export — and
takes it through analysis, approval (the schedule is its standing approval), generation, verification and
publication, audited as usual (`portability_events`, subject `schedule`). A run is skipped when nothing was
recorded since the last publication, waits when the analysis needs a person, and three failures in a row switch
the schedule off. Exports carrying restricted classes are not schedulable.

`python -m app.portability scheduled` runs the schedules that are due. The Helm chart runs it every 15 minutes
as the CronJob `argus-portability-scheduled` (`portabilityJobs.scheduled`), on the API's node with its volumes
and environment; a run claims its schedule in the database, so overlapping runners never run one twice. Without
Kubernetes, run the same command from cron with the API's environment.

### Retention and legal holds

`python -m app.portability cleanup` deletes, for exports and imports older than `retention_days` (90):

* local archive files;
* quarantine and staging files and databases;
* evidence copies.

It keeps every record, its audit, Git history and published artifacts. Every deletion is audited, and
a published export becomes `expired`. Run it daily, for example as a Kubernetes CronJob with the API
image and its environment:
`command: ["python", "-m", "app.portability", "cleanup"]`. `--dry-run` reports without deleting.

A **legal hold** suspends deletion: on the export or import page, or

```
python -m app.portability legal-hold export exp-… --by alice@example.org --reason "audit 2026-17"
python -m app.portability legal-hold export exp-… --by alice@example.org --release
```

### Long steps as jobs

The web pages run generate, publish, fetch, verify, execute and finalize as background jobs and
poll their state (queued, running, completed, failed). A restart marks running jobs `interrupted`:
run the step again, and an import resumes from its staging checkpoints. The CLI runs every step in
the foreground.

If a staging database outlives its import (a crash during finalization), drop it with
`DROP DATABASE argus_stage_… WITH (FORCE)` once the import is `finalized` or `discarded`. Old
`quarantine/`, `staging/` and `verify/` directories under `ARGUS_PORTABILITY_ROOT` can be removed
the same way.

## Which release is running

`GET /v1/meta/version` (no sign-in needed) answers the API's release, commit and build time, and the API
contract version. *About* in the web application shows the same for the API and for the web application
itself, and warns when they differ, as they do for a few minutes during a rollout. The release workflow
sets them when it builds the images (`ARGUS_VERSION`, `ARGUS_COMMIT`, `ARGUS_BUILT_AT`, and
`VITE_APP_*` for the web application). A local build says `dev`.

```bash
curl -s https://<api host>/v1/meta/version
```

## API tokens

ARGUS has two kinds of token, both made in the web application. Only a person signed in can make one;
a token can never make another.

- **Personal access tokens** are made on *My account*. They act as their owner, narrowed by their scopes
  (read, create, modify, delete, approve, admin) and optionally by kind of record and workspace. They
  expire within a year. They never exceed the owner's roles, and they carry administrator rights only
  with the `admin` scope.
- **Robot tokens** are made on a workspace's *Robot tokens* page by its owners. They belong to the
  workspace, are named in the history as `robot:<name>`, and expire within two years or never.

Tokens start `argus_pat_` or `argus_bot_`, so secret scanners can recognise them. Only their peppered
SHA-256 is stored. Revoked and expired tokens answer 401. A token without a write scope can only `GET`.
*Administration → API tokens* lists and revokes them all.

Tokens made with `scripts/create_token.py` or `argus_admin.py`, and those made before this change, are
robot tokens with every scope: what they always could do.

## The mobile app's sign-in client

The ARGUS Field app signs in with OpenID Connect and PKCE as the public client `argus-mobile`, and sends
its **access token**. The API accepts only tokens addressed to its audience (`OIDC_AUDIENCE`, the web
client's id), so the client needs an audience mapper. The chart's realm includes it, but Keycloak
imports the realm only on its first start. On an installation set up before, add it once in the
Keycloak admin console (realm `argus`):

1. *Clients → Create client*: OpenID Connect, client id `argus-mobile`, name *ARGUS Field (mobile)*.
   *Client authentication* off (public), only *Standard flow* on.
2. *Valid redirect URIs*: `it.infn.argus.field:/oauthredirect` (and the web app's
   `https://<web host>/auth/mobile` for app links). *Advanced → Proof Key for Code Exchange*: `S256`.
   *Access token lifespan*: 10 minutes.
3. *Client scopes → argus-mobile-dedicated → Configure a new mapper → Audience*: name *ARGUS API
   audience*, *Included client audience* `argus-webapp`, *Add to access token* on.

Or with `kcadm.sh` inside the Keycloak pod:

```bash
kcadm.sh config credentials --server http://localhost:8080 --realm master --user admin   # asks for the password
kcadm.sh create clients -r argus -s clientId=argus-mobile -s publicClient=true \
  -s standardFlowEnabled=true -s directAccessGrantsEnabled=false \
  -s 'redirectUris=["it.infn.argus.field:/oauthredirect"]' \
  -s 'attributes={"pkce.code.challenge.method":"S256","access.token.lifespan":"600"}' \
  -s 'protocolMappers=[{"name":"ARGUS API audience","protocol":"openid-connect","protocolMapper":"oidc-audience-mapper","config":{"included.client.audience":"argus-webapp","access.token.claim":"true"}}]'
```

Build the app against production with `--dart-define=ARGUS_ENV=production
--dart-define=ARGUS_API_BASE=https://<api host> --dart-define=OIDC_ISSUER=https://<keycloak host>/realms/argus`
(the variables are in `mobile/app/lib/core/config.dart`).

If the app returns from the sign-in page without being signed in, and its log says `AppAuth: No stored
state`, the Android `MainActivity` has `android:taskAffinity=""` again (Flutter's template adds it): remove
it, uninstall the app and build again.

For **Ask** by voice the app asks for the microphone the first time. It needs a usable AI endpoint in the
workspace (*Administration → AI*), as the web's Ask ARGUS does.

### Google accounts through Keycloak

The realm can offer **Google** beside its own accounts: the web app and the mobile app both see a
Google button on the Keycloak page, and nothing else changes for them or the API. A Google user is matched to
an existing ARGUS user by email (`trustEmail` is on).

1. In Google Cloud, create an OAuth client of type *Web application* with the redirect URI
   `https://<keycloak host>/realms/argus/broker/google/endpoint`.
2. Put its secret in the Secret: `kubectl -n argus patch secret argus-secrets --type merge -p
   '{"stringData":{"keycloak-google-client-secret":"<secret>"}}'`.
3. Set `keycloak.google.clientId` in the values. A new realm is imported with the provider.

The realm is imported only on Keycloak's first start, so on an existing installation also add the provider
once in the admin console (*Identity providers → Google*), or with `kcadm.sh create identity-provider/instances
-r argus -s alias=google -s providerId=google -s enabled=true -s trustEmail=true -s config.clientId=<id>
-s config.clientSecret=<secret>`.

### Signing in with Google directly, without Keycloak

With `OIDC_ISSUER=https://accounts.google.com` the app signs in with Google directly and sends the
**ID token** (Google's access tokens are opaque). In the Google Cloud console, create an OAuth client
of type *iOS* with bundle id `it.infn.argus.field`. Use it on Android too, because Google's Android
clients do not accept a custom-scheme redirect. Build with:

```
--dart-define=OIDC_ISSUER=https://accounts.google.com
--dart-define=OIDC_CLIENT_ID=<id>.apps.googleusercontent.com
--dart-define=OIDC_REDIRECT=com.googleusercontent.apps.<id>:/oauthredirect
```

The Android redirect scheme follows `OIDC_REDIRECT` automatically. The API must trust Google as a
provider whose audience is that client:

```
OIDC_EXTRA_PROVIDERS='[{"issuer": "https://accounts.google.com", "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs", "audience": "<id>.apps.googleusercontent.com"}]'
```

A Google account is matched to an existing ARGUS user by email.

## Performance targets

```
python -m app.ledger probe --base-url https://argus.example --token $TOKEN \
    --asset <uid> --asset <uid> … --query pump --query SIP --edit <probe-record-uid>
```

It reports the p95 of record pages and searches, how long an own edit takes to
be visible, and whether each meets its target (record page < 500 ms, search
< 1 s, own edit < 1 s). `--edit` writes an `argus_probe` value: point it at a
record kept for the purpose. Run it at 10× the current volume before a
cutover (§19 item 13). `--reproject <workspace>` also times a full
re-projection of that workspace in-process (rolled back, target < 30 min);
it needs `DATABASE_URL`.

### 10× volume run

`scripts/generate_volume.py` builds a synthetic workspace of that size and
prints the token and record uids to probe with:

```
cd backend
PYTHONPATH=. python scripts/generate_volume.py --workspace volume --assets 50000 \
    --tickets 20000 --documents 5000 --ledger-devices 2000 --token volume-token
python -m app.ledger probe --base-url http://127.0.0.1:8000 --token volume-token \
    --asset <uid> … --query "Ion Pump" --query SN0012345 --query "Rack C12" \
    --edit <uid> --reproject volume
```

Measured on a development container (one uvicorn worker, Postgres 16 on the
same host), with 50 000 records, 100 000 relations, 20 000 tickets,
5 000 documents and a 2 000-device configuration ingested through the ledger:

| Measure | Result | Target |
|---|---|---|
| Record page p95 (40 records) | 230 ms (median 82 ms) | 500 ms |
| Search p95 (5 queries) | 188 ms | 1 s |
| Own edit visible | 843 ms | 1 s |
| Full re-projection of the workspace | 278 s | 30 min |
| Ingest of the 2 000-device revision | 188 s | — |
| Bulk load of the rest | 18 s | — |

Two hot paths were fixed on the way. Claim presence is now cached per
session against the stream's last event, where it used to replay the whole
stream once per projected subject. And a publication re-derives only the
tickets whose links the ledger can move: those on positions, control devices
and installed units, and those with no links yet. Before, it re-derived every
ticket in the workspace. The own-edit time is the closest to its target;
watch it first when the volume grows.

## The Jira host after retirement

When Jira is retired, point its host name at ARGUS. Every old link then
opens the ARGUS lookup page, which resolves it with the reader's own
access. The redirect itself shows nothing about what exists.

```
JIRA_LEGACY_HOSTS=jira.example.org,insight.example.org
ARGUS_WEB_URL=https://argus.example.org
```

A request whose `Host` is one of these gets a 301 to
`$ARGUS_WEB_URL/lookup/<the original URL>`. A proxy that cannot route by
host name can forward the old host to `/legacy/jira/<path>` instead:

```
server {
    server_name jira.example.org;
    location / {
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_pass http://argus-api:8000/legacy/jira$request_uri;
    }
}
```

## Retiring Jira

Jira is retired once, for the whole instance, from *Migration to ARGUS →
Jira retirement* (administrators only; `GET/POST /v1/retirement`). ARGUS
checks for itself:

- every domain is past its signed exit and in T4;
- every domain's export was attested as verified at its exit;
- the retention decision (U1) is recorded, with the records policy it
  comes from (`POST /v1/retirement/retention`);
- every workspace with a domain has an access review signed in the last
  year;
- the audit chain verifies;
- every Jira workflow of a ticket domain passes its rehearsal;
- a restore rehearsal passed in the last quarter
  (`python -m app.ledger rehearse-restore` records it);
- a probe run in the last quarter measured and met all four targets,
  re-projection included (`python -m app.ledger probe … --reproject <ws>`
  records it);
- the Jira host redirect is configured.

The signer also attests three things ARGUS cannot see: a
disaster-recovery drill, the owners' sign-off of the targets (U10), and
their acceptance of items 1–13. Signing records one decision and moves
every domain from T4 to T5. A domain reaches T5 in no other way.

## Legacy migration (§12)

This converts the records the old importer inferred (`argus_keywords:
inferred`) into Positions, Equipment and Installations. It is done per
workspace, before the workspace's domain is frozen for cutover: the freeze
is refused while any item is M-BLOCK, an M-MIXED item is not yet accepted,
or an inferred record is not in a plan.

1. **Back up** (`python -m app.ledger backup`). Run it first on a restored
   copy of production.
2. **Plan**: *Migration to ARGUS → Legacy records → Plan the migration*, or
   `POST /v1/migration/plans` with an optional `inventory_workspace_id`.
   This is where Equipment that matches no inventory record gets created.
   Nothing changes. Download the decision report (CSV) and give it to the
   owners.
3. **Review**: the owners override an outcome where they disagree. Each
   override needs a reason and is recorded as a decision. An M-BLOCK item
   (an identifier held by another record) is resolved at its source, then
   re-planned or overridden.
4. **Apply**: items are applied in dependency order, each in its own
   savepoint:
   - an item whose record changed since planning becomes `stale`;
   - an item that breaks I-MIG-1 (nothing lost) or I-MIG-2 (traceable)
     becomes `failed` and leaves nothing behind.

   The plan is `verified` when every item is applied and I-MIG-2 and
   I-MIG-3 hold across the plan.
5. **Deep verification** (*Deep verify*, `POST /v1/migration/plans/{id}/verify`):
   - **I-MIG-4:** runs the data invariant report over the plan's workspaces
     (below). Every invariant must hold.
   - **I-MIG-5:** compares the relation registry's report with the
     baseline taken before the first item moved. The total number of
     violations must not grow; a rule that grew is named even when the
     total fell.
   - **I-MIG-6:** rebuilds the plan's workspaces from the ledger inside a
     savepoint, compares every record the plan touched, then rolls back.
     A difference means something was written around the ledger.

   - **I-MIG-7:** walks the workspace's golden incidents again (below) and
     compares them with the walk taken at the first apply. Every cause
     found before must still be found, either the same record or a more
     precisely resolved one: what the migration made of it, or the unit
     that realizes a Position.

   Finalizing needs a passing deep verification taken after the last
   apply. A workspace with no golden incidents can be finalized only with
   a waiver that gives a reason; the reason is recorded in the finalize
   decision.
6. **Roll back** at any point until the plan is finalized, and never after
   the domain has cut over:
   - records the migration created are retired by ledger decisions;
   - Installations are rejected;
   - labels and photos move back;
   - the legacy rows get their pre-images back.

   `migration_map` is append-only, so its rows stay as history.
7. **Finalize** after sign-off. From then on, corrections are ordinary
   decisions.

What each outcome does:

| Outcome | Result |
|---|---|
| M-FUNC | a lattice element: kept |
| M-POS | the row becomes an `Equipment Position` with key `FAC:POS:<tag>`. The old key is kept as a `former_key` label and still resolves through `/v1/lookup` |
| M-PHYS | Position, plus the inventory's matching record or new Active Equipment, plus a Confirmed Installation. `valid_from` is the day a person set in `installed_on`, otherwise `before_records` |
| M-MIXED | Position, plus Provisional Equipment (stated as the migration's inference), plus a Proposed Installation. A reviewer confirms both |
| M-RETIRE | the importer no longer produces it and no person touched it: Retired, with its relations kept in the pre-image |
| M-BLOCK | nothing moves |

**Deprecated edges** (§12.3 step 4) are planned too, one item each, and
applied after the records and before retirements. They are only
rewritten where the rewrite is mechanical:

| Edge | Becomes |
|---|---|
| `assigned to` → a Work Package | the `work_package` attribute of the source. The derived `in work package` edge follows it |
| `spare for` between two units | the source becomes a designated spare, with the target's product model if it has one |
| `on line`, `carried by`, a Serial Line's `port of` | held for a person. A Serial Line becomes a Bus Segment behind its IOC's Communication Path (§9): convert it under *Serial lines* (below), or accept the edge as a registry exception |
| `replaced` | held for a person: a replacement is an Installation swap, with its date |
| `spare for` between two Positions | held for a person: name the unit that is the spare |

Rewritten edges are removed through recorded decisions and restored on
rollback. Held edges stay, and the relation registry keeps reporting them
until someone deals with them.

## Cutover entry criteria (§17.4)

A domain is frozen for cutover (T3) only when every entry criterion holds.
They are listed in *Migration to ARGUS → the domain → Entry criteria and
freeze*, and in `GET /v1/domains/{id}` as `entry_criteria`.

ARGUS checks these itself:

| Criterion | What ARGUS checks |
|---|---|
| 2 stewards | a primary steward and a different backup, set with `PUT /v1/domains/{id}/stewards` and recorded as a decision |
| 2 blocking queues | no blocking conflict and no held revision (never waived) |
| 2 queue ageing | no open item past its §18.2 target, in working days: port mapping 5, identity candidate 10, retirement flag 10, other non-blocking 30. A safety-relevant port confirmation is never left open |
| 3 shadow validation | the domain is in T2, entered at least 14 days ago, with 10 consecutive passing reconciliation runs since. Past 8 weeks it is flagged for the governance group |
| 4 legacy migration | no M-BLOCK item, every M-MIXED item accepted, no inferred record unplanned (never waived) |
| 5 restore | a restore rehearsal passed in the last 30 days (`python -m app.ledger rehearse-restore` records it) |
| 7 performance | a probe run that met every target, in the last quarter |

People attest the rest: the readiness items and tests A33–A41 pass for
the domain's data (1), the users are trained (6), and the Jira
read-only change is approved and scheduled (6).

The governance group may waive a criterion with a reason, for example a
rehearsal on staging, or a domain it decided to cut over at the T2 limit.
The waivers and attestations are written into the `freeze` decision.

## Review queues and escalation (§18.2)

Every open review item is in one queue. Each queue has three targets in
working days: when an item is due, when it goes to the domain's backup
steward, and when it goes to the governance group.

| Queue | Due | To backup | To governance |
|---|---|---|---|
| blocking conflicts, held revisions | 2 | 3 | 5 |
| port confirmations, safety-relevant | 0 | 0 | 1 |
| other port confirmations and mappings | 5 | 7 | 10 |
| identity candidates | 10 | 15 | 30 |
| proposals (inferred facts) | 20 | 30 | 60 |
| non-blocking conflicts, possible overlaps | 30 | 45 | 90 |
| retirement flags | 10 | 15 | 30 |

The scheduled `python -m app.ledger escalate` job, or *Review queue →
Queue ageing → Escalate overdue now*, sends an in-app notification once
per level. It is also e-mailed when SMTP is configured:

- level 1 goes to the backup steward, with the steward in copy;
- level 2 goes to the governance group, with the backup in copy.

The stewards are the ones set on the workspace's domain. The governance
group is set here:

```
ARGUS_GOVERNANCE=governance-lead@example.org,platform-lead@example.org
```

A notification names the queue, the workspace and the age, never the
record. The recipient opens the review queue with their own access, so a
restricted record is not disclosed. The dashboard (`GET
/v1/ledger/review/queues`) shows, for each queue:

- its size and age distribution;
- how many items are overdue, at backup and at governance;
- the age of the oldest item.

Migration items are not in a queue of their own: they are due before the
domain's cutover, and the freeze enforces that (§12, §17.4).

## The relation registry, in warn mode (§6)

`GET /v1/ledger/registry/report` lists every edge of the workspace that
breaks the registry. It checks:

- deprecated verbs (`replaced`, `carried by`, `on line`, `spare for`, and
  `assigned to` a Work Package);
- the types each end may have (`installed at`, `installation of`,
  `realized by`, `assigned to`, `powers`, `acts on`, `port of`, `runs on`,
  `part of`);
- cardinality: one position per unit at any instant, one Installation
  edge each way, one `part of`, exclusive `composed of`;
- cycles in `part of` and `composed of`;
- edges pointing at retired or merged records.

Nothing is refused in warn mode. The report is what stewards triage
before the registry moves to `enforce` (§13 S7), and it is the measure
that I-MIG-5 compares.

## Data invariant report

`GET /v1/ledger/invariants/report` checks the workspace's data as it is,
whatever wrote it. The ledger enforces these invariants when a decision is
made; this report catches what the legacy importer, a migration or a write
around the ledger left behind.

| Invariants | What is checked |
|---|---|
| I-INS-1, I-INS-2 | no unit in two places, and no two units in one position, in definite overlap (Confirmed Installations) |
| I-INS-3 | Confirmed intervals are not inverted |
| I-INS-4 | an Installation is installed at an installable position, of Equipment |
| I-INS-5 | an Installation is in its position's workspace |
| I-INS-6 | a possible overlap has its review item |
| I-AP-1 to I-AP-3 | one Active Access Point per address; one assignment each; no definite overlap of service |
| I-AP-4 | an assigned Access Point has no asserted `implemented by` |
| I-AP-5 | an Access Point lives in the workspace whose configuration names it |
| I-PORT-1 | every derived `attached to` edge is exactly what the port matching gives now |
| I-PORT-2 | a confirmed port map names a port of its Installation's unit |
| I-PORT-3 | an unresolved mapping has its review item |
| I-TKT-1 | each ticket has exactly one subject link |
| I-TKT-2 | no ticket is counted twice on one record, and migration-split links stay possible |
| I-TKT-3 | the derived links are exactly what a fresh derivation gives (recomputed in a savepoint) |
| uniqueness | no serial (per manufacturer), inventory number, verified Insight objectId or QR code is held by two live records |

I-INS-7 and I-PORT-4 hold by construction of the checks above. The report
says which invariants they are covered by.

## Golden incidents (I-MIG-7)

The teams record past incidents: their symptoms, and the causes they know
were behind them. Use *Migration to ARGUS → Legacy records → Golden
incidents*, or `POST /v1/migration/golden-incidents` with `name`,
`symptoms`, `expected_causes`, and optionally `symptom_kind`, `healthy`
and `ticket_uid`. Keys, old keys and uids are accepted; everything is
stored by uid, so incidents survive re-keying.

*Run the walk* (`POST /v1/migration/golden-incidents/run`) runs the root
cause analysis on each incident. It reports which expected causes it
finds, and at what rank. The set is also the regression suite for any
change to the causal model or the relation registry, not only for
migrations.

## Ledger-only workspaces (§13 S5)

Every record edit made through the API or the UI goes through the fact
ledger:

- creating a record is the creator's statements of its existence, name
  and attributes, confirmed by them;
- editing changes only the fields that differ, one confirmed statement
  each, in one batch; removing a field is a statement that it has no
  value;
- adding or removing a relation is a statement that the edge holds, or no
  longer holds. An edge from before the ledger is removed with a recorded
  decision;
- every change shows in the record's audit trail, with its author.

A workspace can then be switched to ledger-only (*Migration to ARGUS →
Ledger-only writes*, or `PUT /v1/ledger/ledger-only` with a reason). This
is allowed once its legacy records are migrated (§12), and the switch is
recorded as a decision. From then on:

- a database trigger refuses any change to a record's attributes, name,
  type, key, status or merge, and any change to a relation, unless the
  ledger itself is writing. That covers scripts, direct SQL and anything
  else written around the ledger;
- the API answers such a refusal with 409 `{"invariant": "ledger-only"}`;
- deleting a record retires it, and the record keeps its history;
- display and caching fields (avatar, sharing, the relation caches) stay
  editable directly: they are not facts.

The Jira, EPIK8s and PBS importers are not used on these workspaces:
ARGUS is the source of truth for them. A workspace transfer into a
ledger-only workspace fails at the database for the same reason: it copies
records in directly.

## Equipment classes (§5.5)

Equipment that no type of its own describes is an *Other Equipment*
record with an `equipment_class`. The class vocabulary belongs to the
catalogue workspace, the one that holds the global `Asset` type. Only the
catalogue adds a class, and only an active class can be given to an
object (I-CAT-1). An object with no class is `Unclassified`.

The vocabulary starts from the classes the sources name. A class the
catalogue already has as a type of its own (PLC, I/O Module, Timing
Module, Motion Controller, Laser System, Cryogenic Device, and Cable as
Cable Run) starts out promoted. Nobody files a PLC as "Other Equipment,
class PLC".

The report is in *Equipment classes*, or at `GET
/v1/catalogue/equipment-classes/report` from the catalogue. It shows:

- objects per class, per workspace and per source;
- the share of `Unclassified` among all Equipment, and its alert: more
  than 5 % and at least 10 records, or more than 50;
- how many objects of each class appear in tickets, and how many have a
  causal relation (so the root-cause walk uses them);
- the `key: value` lines people keep writing into descriptions;
- the attributes people asked for.

**Promotion reviews** open when a class meets any threshold: 25 active
objects, objects in 2 workspaces, 3 requested attributes, or a causal
role. A query or dashboard that filters on the class is the one threshold
ARGUS cannot see, so anyone can open a review for it, with a reason. A
declined class is reviewed again only when a new kind of threshold is met.

**Promotion** does three things:

- it creates a child type of `Asset` in the catalogue, shared, with the
  requested attributes;
- it retypes the class's objects in place, keeping their uids. Each
  retype is a confirmed statement of the object's `type` in its own
  workspace, carrying the promotion's reason. The projection applies it
  and writes a `retyped` record event. This works in ledger-only
  workspaces, and in scopes that are read-only mirrors during cutover,
  because type names belong to the catalogue. A rebuild keeps the new
  type. Withdrawing an object's statement puts it back to Other Equipment;
- the class stays in the vocabulary for history, but can no longer be
  assigned.

The monthly job opens the reviews that are due and notifies the catalogue
owners about them and about the alert:

```
ARGUS_CATALOGUE=inventory-lead@example.org python -m app.ledger catalogue-report
```

Mapping source classes through a versioned table is the importers' part of
§5.5. It is left out while ARGUS itself is the source of truth.

## Enforcing the relation registry (§13 S7)

The registry runs in warn mode per workspace until it is switched to
enforce (*Migration to ARGUS → Relation registry*, or `PUT
/v1/ledger/registry/mode` with a reason, recorded as a decision). The
switch is allowed only when every violation in the workspace's report is
either fixed or accepted:

- fix an edge by removing it, or by stating the relation the registry
  allows;
- accept an edge as it is with *Accept as exception*, or `POST
  /v1/ledger/registry/exceptions` with the violation's id and a reason.
  The exception is a decision; revoking it makes the violation count
  again.

In enforce mode, every decision that adds an edge is checked before it is
recorded. That covers the API, bulk changes, the review tools and the
decisions endpoint. An edge is refused with 409 `I-REG` if it:

- uses a deprecated verb;
- has an end of a type the relation does not allow;
- goes over the relation's cardinality (a single-valued relation is
  replaced, not added to);
- closes a cycle in `part of` or `composed of`;
- points at a retired or merged record.

Removing an edge is never refused. Going back to warn mode is allowed at
any time, with a reason.

The retirement guard is already live on every source stream. A revision
that would make more than 10 % of its subjects (and at least 10)
disappear, or retire a record that still has tickets, documents or a
Confirmed Installation, is held for review. A person's own edits are not
revisions: retiring a record by hand is an explicit decision with its
author.

## Converting serial lines (§9.1, §12.4)

The old importer wrote one Serial Line per converter port. Each line had
its devices `on line`, a `port of` edge to its Access Point and a
`carried by` edge to the converter. The model has none of these edges.
*Migration to ARGUS → Serial lines* (or `GET /v1/ledger/serial-lines`)
lists each remaining line with what converting it would build:

- the Access Point it enters at (from `port of`);
- the converter (from `carried by`);
- one Communication Path per IOC of its devices (from each device's
  `provided by`);
- its port number, from `tcp_port` or the `:4003` at the end of its key;
- anything a person must settle first. A line may name several Access
  Points, in which case pick one; or a device may have no IOC. A device
  without an IOC blocks the conversion: give it one, because removing its
  edge would leave it unreachable in the model.

*Convert* (`POST /v1/ledger/serial-lines/{uid}/convert` with a `reason`,
and an `access_point_uid` when the line names several Access Points) makes
these changes, all through the ledger:

1. The line is retyped in place as a **Bus Segment**, so its uid, key,
   tickets and documents stay the same. The retype is a statement of the
   record's `type`, confirmed with the conversion's reason, and the
   projection applies it and writes a `retyped` record event. A rebuild
   from the ledger keeps it. Withdrawing the statement (stating `type` as
   empty) puts the record back to the type it had before.
2. Each path is created (`PATH:<ioc>:<line>`). The path `enters at` the
   Access Point and `continues on` the segment. The segment is
   `served by` the path, and each device `uses path`.
3. The Access Point is `implemented by` the converter, unless it already
   names equipment.
4. The port number becomes a `required_port` claim. The claim is inferred
   and advisory: it waits for a person, and a number never attaches a
   port on its own (§9.3).
5. The old `on line`, `port of` and `carried by` edges are removed. Legacy
   edges get a `remove_legacy_edge` decision each.

The golden incidents are walked before and after. If the walk would stop
finding a cause it found before, nothing is changed and the conversion is
refused (422). It goes ahead only when a person accepts the loss with a
reason (`accept_golden_loss`). That reason is kept on the
`convert_serial_line` decision. The root-cause walk follows the new edges:
a failed converter reaches the devices through `implemented by`,
`enters at` and `uses path`, and a broken segment reaches them through
`continues on`.

## Model extensions (§5.1, §13 S8)

The model grows only in the areas the first revision set as triggers:

- RF distribution;
- diagnostics;
- magnets and undulators;
- cabling;
- network topology;
- consoles;
- stores;
- safety;
- plant and electronics;
- engineering.

An extension for one of them enters only when it has **an owner, a source
and a query**. The query is the question the extension exists to answer.
It ships with a fixture and the answer expected on it.

An extension is a Python module in `backend/app/extensions/`. It defines
`EXTENSION` and is reviewed like the rule catalogue:

```python
from app import extensions as ext
from app.services import causal_model as cm

EXTENSION = ext.Extension(
    id="cabling-signal", trigger="cabling",
    owner="<the team that answers for it>",
    source="ARGUS, entered by <team>",          # or a named ledger stream
    summary="patch panels and where the cables land",
    types=[ext.ExtType("Patch Panel", "Asset", "A panel cables land on",
                       [("ports", "Ports", "integer")])],
    relations=[ext.ExtRelation("lands on", "environment", cm.REVERSE, cm.FUNCTION,
                               "cable → the panel it lands on: the panel goes, the cable is cut",
                               target_types={"Patch Panel"})],
    query=ext.ExtQuery("unlanded cables", "Which cables land nowhere?",
                       run=..., fixture=..., expect=...),
)
```

The gate (`app.extensions.check`) refuses an extension if:

- it has no owner, source or query;
- its trigger is not one of the list;
- it adds a type or a relation that exists already;
- a type hangs from a parent the catalogue does not have;
- a relation does not say which way a failure travels along it, or what
  the failure takes with it (§5.4). An unclassified relation is silently
  ignored by every root-cause walk.

`tests/test_extensions.py` runs the gate and the query on its fixture for
every declared extension. A declared extension that fails there fails CI.

The relations of a declared extension that passes the gate are known at
once to the causal model and to the registry (endpoint types,
cardinality). Its types reach a catalogue only when admitted there, under
*Equipment classes → Extensions*, or with `POST
/v1/catalogue/extensions/{id}/admit` and a reason. The gate runs again,
and the query runs on its fixture in a workspace made for it, which is
then thrown away. The admission is an `admit_extension` decision. `GET
/v1/catalogue/extensions` lists each trigger with where it stands (add
`?run_fixtures=true` to run the queries). `GET
/v1/catalogue/extensions/{id}/query` asks an admitted extension's question
of the current workspace.

No extension is declared yet: each trigger is waiting for its owner.

## Guided and AI-assisted entry (§23)

The forms for a new asset, a new ticket and a new document have a side
panel with two parts.

**The checklist** works in every workspace and needs no model. As the person
types, it checks the draft (`POST /v1/intake/guide/{asset|ticket|document}`)
and shows:

- the steps done so far;
- the next question worth answering;
- what is wrong or worth knowing, with one-click fixes where there is one.

| Kind | What the checklist checks |
|---|---|
| asset | the type is usable and concrete (a category offers its kinds); whether the type is a physical unit or a place in the machine; name and key, with a taken key linked to its record; a control-channel or PV name typed as physical equipment; Other Equipment without a class; required and invalid attributes; MAC and identifier normalization; a serial without its manufacturer; no serial or inventory number; a serial or inventory number another record holds (refused after cutover, a duplicate review before); similar records of the same type |
| ticket | a one-line title; a description that says what was seen; the kind of ticket; when an operational incident happened (I-TKT-4); the affected record, suggested from the records the report names; open tickets that look like the same problem; secrets in the text |
| document | a title; the kind of document; the code it will get, or a code already used; documents with similar titles; secrets in the text; the records it mentions |

A record the person cannot read is never named in a check. A taken key or
identifier on such a record is reported as taken, without a link (I-ACL-1).

**Describe it** appears when the workspace's AI endpoint is configured,
enabled and checked. The person writes what they know, or photographs a
nameplate for an asset, and the assistant suggests values for the form.
Endpoints: `POST /v1/intake/assist/{asset|ticket|document}` and
`/v1/intake/assist/asset/photo`.

- **Suggestions only.** Nothing reaches the form until the person clicks
  *Use* or *Use all in empty fields*, and nothing is saved until they save
  the form. *Use all* never overwrites what they typed.
- **Evidence.** Each suggestion shows its confidence and the words of the
  input it was read from. When the model cannot point to those words,
  the confidence is capped at 50 % and the suggestion says so.
- **Vocabulary.** The model answers only in the types and attributes usable
  in the workspace. Anything else is dropped and listed with the reason.
  So is a key that belongs to an existing record, with a link to it.
- **Ticket causes.** For a ticket, suspected causes are shown as
  *unresolved hypotheses*, never written into the root-cause field. The
  person's report becomes the description, and the affected record is
  matched from the text, not guessed by the model.
- **Secrets.** Passwords, keys, tokens and credentials in URLs are removed
  before anything is sent to the model.
- **Untrusted input.** The input is passed as data, and the model is told to
  ignore any instructions in it.

**Provenance.** Every call writes an `intake_runs` row: requester, model,
endpoint host, prompt version, rule id, input hashes, redaction counts,
validated output and outcome. When the record is saved, `POST
/v1/intake/runs/{id}/outcome` writes an `intake_outcomes` row saying, for
each suggested field, whether it was kept, corrected or left out. Both
tables are append-only.

For an asset, the suggestions also enter the fact ledger. They are AI
claims (`ai_extracted` or `ai_classified`, rule `ai.asset.describe/1`) in
the stream `ai:<workspace>:asset.describe`, with their evidence and
confidence. A kept suggestion is accepted, and a corrected or left-out
one is rejected with that reason. The person's own confirmed values stay
the effective facts. `GET /v1/intake/provenance/{record_uid}` shows what a
model suggested for a record and what the person did with it.

**Files.** *Add a photo or file* reads a nameplate photo (assets, with a vision
model), a PDF datasheet, a Word or Excel file, an email or a text file
(`POST /v1/intake/assist/{kind}/file`). Each piece of text keeps its origin,
such as a page, a sheet and row, or a paragraph, and the run records it.
A PDF with no text layer (a scan) is refused with a message. Formulas are
read as their cached values, and hidden sheets are skipped. An email
contributes its subject, date and body, but not its sender.

**Existing records.** The same panel is on the edit forms. The checklist
never reports a record as its own duplicate. On an asset's page, *Complete
from a file* takes a datasheet, a photo or a note and proposes every value
that differs from the record (`POST /v1/intake/propose/asset/{uid}`). The
proposals are AI claims that wait in the review queue, and nothing on the
record changes. The queue shows each one with its confidence, the words it
was read from, the value it would replace, the model and who asked. The
actions (`POST /v1/intake/proposals/{claim_id}`) are:

- *Confirm*: makes the value the reviewer's own confirmed statement and
  accepts the proposal;
- *Correct*: confirms the reviewer's value and rejects the proposal as
  `corrected`;
- *Reject*: needs a reason.

**Model profiles and the gate.** *Workspace settings → AI endpoint →
Models for guided entry* manages which model describes assets, tickets or
documents. The steps are:

1. **Add a candidate** (a model name, and for assets optionally a vision
   model).
2. **Evaluate it** on the golden dataset in
   `backend/app/intake/golden/*.json`. The cases are reviewed like code, in
   English and Italian, and include injected instructions and secrets. The
   evaluation runs the real intake code in a scratch workspace with a fixed
   vocabulary, and rolls everything back. It reports:
   - accuracy per field and per tag (language, domain);
   - whether any injected instruction changed a suggestion;
   - whether any secret reached the model;
   - p95 latency;
   - regressions against the active profile on the same dataset.
3. **Activate it** with a reason. This is an `activate_ai_profile` decision.

The proposed gates, for sign-off (U15), are:
- overall accuracy of at least 85 %;
- serial and inventory numbers at least 98 % right;
- no field more than one point worse than the active profile;
- no language or domain more than five points below overall.

A reasoning model (Qwen, DeepSeek…) is asked not to think before these
structured answers (vLLM's `chat_template_kwargs.enable_thinking=false`;
a provider that refuses the switch is asked again without it). Before
October 2026 the replies had a fixed 900-token budget, and `qwen36-27b`
spent all of it thinking: every field came back *missing*, 0 % accuracy
with no errors. An evaluation where every field is missing and nothing
is wrong is that, not a poor model. The workspace's **output-token
limit** (*Workspace → AI*, empty for none) now applies to every AI call,
and a reply cut off before any answer is reported as an error naming
the limit.

A profile that misses the gate is activated only with a stated exception.
A security failure, or an evaluation whose cases did not run, cannot be
activated at all. A new golden dataset version needs a new evaluation.

Once active, the profile's model is used for that kind. Its id is part of
each run's rule id (`ai.asset.describe/1#<profile>`), so a new model never
alters earlier claims. *Suspend* retires a profile, and intake falls back to
the endpoint's default model. Suggestions from a model that has not been
evaluated are labelled as such in the form and in the queue.

**Without a model** everything still works. The checklist runs, the form
saves, and a failed assist call leaves the form untouched and writes a
`failed` run. AI streams are internal, like person streams, and AI methods
default to `advisory` in the authority policy. No AI claim becomes
effective without a decision.

## Ask ARGUS: changes it proposes

Ask's lookups only read. Somebody who may create or change records can
also ask it for a change ("create the six screens and link their cameras
and motors"). The model can only **propose** one:

| Proposal | Checked when proposed | Applied as |
|---|---|---|
| create a record | the type is usable here; the attributes are that type's; a given key is free | `POST /v1/assets` |
| change a record | the record is this workspace's; something actually changes | `PUT /v1/assets/{uid}` |
| relate two records, or remove a relation | both exist (or one is proposed here as `new:N`); the relation registry allows the edge | `POST /v1/relations`, `DELETE /v1/relations/{id}` |

A refused proposal goes back to the model with the reason, so it can
correct it. An accepted one is kept in `ask_actions` and shown under the
answer, where the person ticks which to **Apply** or **Discard**
(`POST /v1/ai/conversations/{id}/actions/apply|discard`). Applying runs
each one, in the order proposed, through the same code as the forms:

- it needs the permission it would by hand (create, modify or delete);
- it gets the same validation and key allocation;
- it is written to the ledger as that person's statement.

Each change stands or fails on its own, and the card shows the error. A
relation to a record whose creation failed fails with it. The model's
next turn is told what became of each proposal. Nothing is applied
without the person, and the external MCP server stays read-only.



## Rehearsing the database image (before switching to PostGIS)

The basic GIS release needs PostGIS in the database. The database image `argus-knowledge-hub-postgres`
(deploy/postgres) is the PostgreSQL 16 + pgvector image production runs, with PostGIS added: the same
PostgreSQL major version and data format. Every release builds it; production keeps
`images.postgres: pgvector/pgvector:pg16-trixie` until the rehearsal below has passed **on production's
data**. Keycloak's database lives on the same server, so it is rehearsed too.

1. Take the two dumps (read-only on the server):

   ```
   kubecloud -n argus exec deploy/argus-postgres -- pg_dump -U argus -Fc -d argus    > argus.dump
   kubecloud -n argus exec deploy/argus-postgres -- pg_dump -U argus -Fc -d keycloak > keycloak.dump
   ```

   They hold everything, credentials included: keep them on an encrypted disk and delete them afterwards.

2. Rehearse, on any machine with Docker:

   ```
   KEYCLOAK_ADMIN_USER=<master admin> KEYCLOAK_ADMIN_PASSWORD=<…> \
   tools/db-image-rehearsal --argus-dump argus.dump --keycloak-dump keycloak.dump \
       --image ghcr.io/infn-argus/argus-knowledge-hub-postgres:<version> \
       --backend-image ghcr.io/infn-argus/argus-knowledge-hub-backend:<version> --realm argus
   ```

   It restores both databases into the new image and checks: the image (PostgreSQL, pgvector, PostGIS),
   the restore, a nearest-neighbour query on the knowledge index, PostGIS answering, ARGUS's migrations to
   head and its packages, Keycloak starting on the restored database with the administrator signing in,
   and a backup taken from the new image restoring with every table's row count the same. It writes a
   report: keep it with the change.

3. Only after it passes: take a fresh `python -m app.ledger backup`, set `images.postgres` to the rehearsed
   image in `values-production.yaml`, and release. The pod restarts on the same data directory; Keycloak and
   the API reconnect. Rolling back is setting the previous image again (PostGIS is created by a migration
   of the GIS release, not by the image, so the data directory stays readable by the old image until then).
