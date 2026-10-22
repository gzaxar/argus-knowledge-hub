---
title: Export and import (portability)
summary: Moving workspaces or a whole instance between ARGUS installations, step by step: by downloaded file or through a GitHub or GitLab repository, and from a local ARGUS to production.
keywords: [periodic, periodically, schedule, scheduled, recurring, every day, automatic export, rebuild, recover, recovery, disaster, lost, wiped, clean installation, reinstall, re-populate, repopulate, set-up, setup, deploy key, host key, fingerprint, register repository, export, import, portability, backup, restore, clone, migrate, migration, move, copy, transfer, git, github, gitlab, repository, escrow, escrow-dev, artifact store, signing key, trusted keys, allowed_signers, deploy key, token, checkpoint, tar, download, upload, dry run, finalize, local to production]
order: 130
---

**Portability** moves data between ARGUS installations as a signed, verifiable archive: one workspace,
several, or the whole instance with its settings. Use it to move a local ARGUS's work to production, to
keep an off-site copy, or to give another installation a copy.

It is not the database backup: a backup restores *this* installation exactly as it was; an export is a
portable copy that another ARGUS verifies before it loads anything.

Exports and imports are for **administrators**: **Administration → Portability**.

## How it works, in one picture

**On the exporting ARGUS:** Export → Approve → Generate → then either **Publish to Git** or **Download
checkpoint (.tar)**.

**On the importing ARGUS:** Import from Git (the tag) or Upload (the `.tar`) → Verify → Dry run → Approve →
Execute → Finalize.

An export has three parts:

- the **checkpoint**: the signed manifest, saying exactly what is in the archive. It is what you
  download, or what is committed and tagged in Git;
- the **data**: the records, history and attached files, kept as content-addressed files either **in the
  repository**, committed with the checkpoint (the simplest), or in a separate **artifact store** (a
  directory on the exporting installation);
- the **signature**: made with the exporting installation's **signing key**. The importing installation
  checks it against its **trusted keys** (an `allowed_signers` file) and refuses anything unsigned,
  altered or signed by a key it does not trust.

So, to import elsewhere, the importing installation needs: the checkpoint (a Git tag or a file); the
data (with it in the repository, nothing more; with an artifact store, a copy of that store **under the
same store name**); and the exporter's public key among its trusted keys.

## What an export carries, and what it does not

**Carried:** the types and their icons; the equipment classes; people (as the identity profile allows); the
workspaces, their roles, who holds them, and the groups roles are granted to, with their members; global
values; authority policies; assets with their relations, comments, history and labels; tickets with their
comments, history, links and watchers; documents with their revisions and relations; attachments; ticket
workflows; **beam models** (their documents, the values along their paths and their components' bindings to
assets); and the fact ledger with its full audit.

**Not carried**, to set up again on the other installation: the **AI endpoint** settings and model profiles,
saved **import configurations** (and their tokens and history), **API tokens**, field devices, Ask ARGUS
conversations, and the **written-knowledge index** (rebuild it on *AI endpoint → Build the index*).

An archive made before a kind of data was carried simply lacks it: export again and import the new archive on
top. Everything already imported is found identical and left as it is; only what is new is created.

## Words you will see

| Word | Meaning |
|---|---|
| **Scope** | *Selected workspaces*, *Everything* (all workspaces, with the types, people and roles they use), *An increment* of an earlier published export, or *Evidence only* (a read-only copy) |
| **People in the archive** | how people are written: *Institutional reference* (ids only, the default), *Pseudonymized*, *Anonymous*, or *Full identity* (emails and names, needed to move people's accounts) |
| **Purpose** | backup, restore and migration keep full identities; analysis and external sharing are pseudonymized |
| **Restricted classes** | costs, personnel, security incidents…: included only if chosen, and only encrypted for an approved destination |
| **Repository** | a Git repository the archive is published to (*None* = generate only, then download) |
| **Where the data goes** | *In the repository, with the archive* (committed with it; the importer needs nothing else), or an *artifact store* (a directory; the importer needs a copy) |
| **Import mode** | *clone*: records keep their ids, this installation keeps its own identity; *restore*: an empty installation takes the archive's identity; *merge*: alongside existing work; *selective*: choose workspaces in the dry run; *evidence*: read-only, nothing loaded |
| **Quarantine** | where an import's files wait until they are verified |
| **Staging** | a separate database where an import is loaded and checked before it touches the real one |

## Export, step by step

1. **Administration → Portability**, **Export**.
2. **Scope**: *Selected workspaces* (tick them) or *Everything (a full archive)*.
3. **Repository**: the Git repository to publish to, or *None (generate only)* to download a file.
4. **Where the data goes**: *In the repository, with the archive* (recommended with a repository: the
   importing installation needs only the repository; each file must stay under the provider's size
   limit, 100 MB on GitHub), or an *artifact store*.
5. **Purpose** and **People in the archive**: to move your work to another installation of your own,
   choose *Migration* and *Full identity*, so people's accounts and authorship come along.
6. **Restricted classes to include**: leave empty unless you mean it.
7. Create it. The export page shows its steps:
   - **Approve**: under the default (*trusted*) policy you may approve your own export; under a stricter
     one, another administrator must.
   - **Generate**: ARGUS takes a consistent snapshot, writes and signs the archive, and checks it.
   - **Publish to Git** (with a repository): commits it and pushes a signed tag such as
     `export/full/2026-10-05@cp12-3f9a…`. Note the tag: the import asks for it.
   - **Download checkpoint (.tar)** (without a repository).

## Repeat an export periodically

Once an export is **published to a Git repository**, its page offers **Repeat periodically** (administrators):
every hour, 6 or 12 hours, day or week, ARGUS makes a new export with the same scope, destination and
outcomes and publishes it to the same repository — analysed, approved, generated, verified and audited as the
first one was.

- **As increments on the last publication** (the default): the repository holds the first export and a chain of
  increments, each a signed tag naming the one before; an import applies them in order. Or **a complete export
  each time**.
- **Only when something changed** (the default): a run finds nothing recorded since the last publication and
  does nothing.
- Setting it is the **standing approval** of its runs. For a high-risk export (a full one, or one carrying
  people's identities) it needs a recent sign-in and, under separation of duties, an administrator other than
  the export's requester. An export carrying **restricted classes** is not repeated: generating one needs a
  recent sign-in every time.
- A **new dependency** does not stop a run: a record now referring to something outside the export (or to
  something no longer on this installation) is kept as an **external reference**, the outcome that changes
  neither the scope nor what the export carries. The run records that outcome on the schedule, for the runs
  after it, and in the audit.
- A run stops only for what it cannot settle so: an attachment to inspect, a secret found, a dependency that can
  only be blocked or brought in. The export then **waits for you** on the Portability page (the ★ recommended
  outcomes are already chosen: **Save outcomes and analyse again**, then **Approve**), and the next run carries
  it on once it is settled. Three failures in a row switch the schedule off; switch it on again once the cause
  is fixed.

**Administration → Portability → Exports** lists the periodic exports, with their last and next run, **On**,
how often, **Run now** and **Remove** (what was published stays published). Runs are started every 15 minutes
by the deployment's scheduled job (`python -m app.portability scheduled`).

## Import, step by step

1. **Administration → Portability**, **Import**.
2. **Source**: *Git* (choose the **Repository** and give the **Signed export tag**; optionally the
   **Expected commit** you were told) or *Upload* (choose the `.tar` file).
3. **Mode**: *clone* for a copy that keeps its ids (the usual choice); *restore* only into an empty
   installation that should become the exporting one.
4. Create it. The import page shows its steps:
   - **Fetch into quarantine** (Git) — or the upload lands there.
   - **Verify**: signature, checksums, every data file in the artifact store. A failure says what is
     wrong and nothing is loaded.
   - **Dry run**: what would happen, row by row, per workspace. On a full archive it takes minutes; a
     progress bar shows which part it is checking and how many rows it has gone through, and you can leave
     the page meanwhile. If it is **blocked**, *Next step* says why and what to do: usually set
     *References the archive and this instance both lack* to *leave unresolved and list them in the
     reconciliation* under *Decisions for the dry run*, and run it again. In *selective* mode, choose the
     workspaces there too, and their ids if they should differ.
   - **Approve**: as shown by the dry run. Under a stricter policy, or for *merge* and *restore*,
     another administrator approves.
   - **Execute**: loads it into the **staging** database and checks it there. Nothing in the real
     database changes. If it is interrupted, **Resume in staging**.
   - **Finalize**: moves it into the real database in one step, and commits only if the result equals
     what staging showed. If anything differs, nothing is committed and you can retry.
5. Changed your mind before *Finalize*? **Discard**: nothing it loaded remains.

After an import, finished files (quarantine, staging, evidence copies) are removed by the daily cleanup
(after one day in production).

## Set up a GitHub or GitLab repository from the web app

A Git repository is the convenient way to move archives repeatedly, or to keep them off-site. An
administrator registers it once, on **Administration → Portability → Set-up**:

1. Create an **empty, private repository**: on GitHub *New repository* (private, no README); on GitLab
   (for example `baltig.infn.it`) *New project → Create blank project*, private.
2. Under **Git repositories**, press **Add a repository**. Give it a **Name** (for example `escrow`) and
   its **Address**:
   - **SSH** (recommended): `git@github.com:<org>/<repo>.git` or `ssh://git@baltig.infn.it/<group>/<repo>.git`.
     ARGUS makes a deploy key for it; you never handle a private key.
   - **HTTPS**: `https://x-access-token@github.com/<org>/<repo>.git` (GitHub) or
     `https://oauth2@<gitlab host>/<group>/<repo>.git` (GitLab), and a **Token**: on GitHub a fine-grained
     token with *Contents: read and write* on that repository; on GitLab a project access token with
     *write_repository*. Leave the token empty for a public repository you only import from.
   - A **path on this installation**, inside its portability area, for a repository copied here.

   Press **Register** and confirm.
3. For SSH, open the repository's **Details** and follow its three steps:
   1. **Add the deploy key** shown to the repository: GitHub *Settings → Deploy keys → Add deploy key*,
      ticking **Allow write access** if this installation exports to it; GitLab *Settings → Repository →
      Deploy keys*, ticking **Grant write permissions to this key**.
   2. **Confirm the fingerprints** of the server's host keys, after comparing them with the ones the
      provider publishes (the page links them). They are pinned from then on.
   3. **Test it**: **Read**, or **Read and write** (it pushes a branch `argus-connection-test` and deletes
      it at once).
4. Under **This installation's signing key**, press **Make a signing key** (unless the deployment
   provides one) and give its **public line** (*Copy*) to the installations that import from this one.
5. On an installation that imports, under **Trusted keys**, paste the other installation's public line and
   press **Trust it**.

The export form then offers the repository. Under a policy that separates duties, each registration
waits until **another administrator approves** it. Every change is recorded in the audit. Tokens and
private keys are stored encrypted and never shown again.

An installation can switch this off (`ARGUS_PORTABILITY_UI_CONFIG=off`): then repositories and keys come
only from its deployment, as below, and the Set-up tab says so.

## Set it up in the deployment instead

The same can be configured by whoever runs the installation, outside the web app (the values go in the
API's environment, in production `api.env` in the chart's `values-production.yaml`, and the keys in the
`argus-portability` Secret). What the deployment sets is read-only in the web app:

1. **Create an empty, private repository**: on GitHub *New repository* (private, no README); on GitLab
   (for example `baltig.infn.it`) *New project → Create blank project*, private.
2. **Choose how ARGUS authenticates**:
   - **SSH deploy key** (recommended):
     ```
     ssh-keygen -t ed25519 -N '' -C argus-escrow-deploy -f deploy-key-escrow
     ```
     Add `deploy-key-escrow.pub` to the repository: GitHub *Settings → Deploy keys → Add deploy key*,
     tick **Allow write access** on the installation that exports; GitLab *Settings → Repository →
     Deploy keys*, with **Grant write permissions**. An installation that only imports needs read only.
     Pin the server's host key: `ssh-keyscan github.com > known_hosts` (or your GitLab host), and check
     the fingerprints against the ones the provider publishes.
   - **HTTPS token**: a GitHub fine-grained token with *Contents: read and write* on that repository, or
     a GitLab project access token with *write_repository*. Save it in a file. Put a user name in the
     address so Git asks only for the password, which ARGUS answers with the token:
     `https://x-access-token@github.com/<org>/<repo>.git` (GitHub) or
     `https://oauth2@<gitlab host>/<group>/<repo>.git` (GitLab).
3. **Tell ARGUS about it**, naming the repository (here `escrow`):
   ```
   ARGUS_PORTABILITY_REPOSITORIES=escrow=ssh://git@github.com/<org>/<repo>.git
   ARGUS_PORTABILITY_REPOSITORY_KEYS=escrow=/etc/argus/portability/deploy-key-escrow
   ARGUS_PORTABILITY_SSH_KNOWN_HOSTS=/etc/argus/portability/known_hosts
   ```
   or, with a token:
   ```
   ARGUS_PORTABILITY_REPOSITORIES=escrow=https://x-access-token@github.com/<org>/<repo>.git
   ARGUS_PORTABILITY_REPOSITORY_TOKENS=escrow=/etc/argus/portability/token-escrow
   ```
4. **Signing and trust**: each installation that exports has a signing key
   (`ARGUS_PORTABILITY_SIGNING_KEY`, an Ed25519 key, and `ARGUS_PORTABILITY_SIGNER`); each that imports
   lists the exporters it trusts in `ARGUS_PORTABILITY_TRUSTED_KEYS` (an `allowed_signers` file, one
   line per exporter's public key).
5. Restart the API (in production, Argo CD does it when the values change). **Administration →
   Portability** then lists the repository under *Repositories*, and the export form offers it.

With the data **in the repository**, the repository is all the importing installation needs. With an
**artifact store** instead, give the importing installation a store with the same name and a copy of its
files. Stores can be added under **Set-up → Artifact stores** (a directory in the portability area) or in
the deployment (`ARGUS_PORTABILITY_ARTIFACT_STORES`).

## Change what was registered

Under **Set-up**, a registered repository's **Details** has **Change address or provider**: the kind of
access (SSH, HTTPS, or on this installation) stays; to change it, remove the repository and register it
again. A new SSH server must have its fingerprints confirmed again, and under a policy that separates
duties the change waits for another administrator's approval. A trusted key's note can be edited; the key
itself never changes (trust the new one and remove the old). Removing an artifact store unregisters it;
its files stay on the volume.

## From your local ARGUS to production

The usual first load of a new production installation, with the local one's workspaces. The simplest
way goes through a private GitHub or GitLab repository both installations can reach, with the data in it.

**Once, on both installations** (*Administration → Portability → Set-up*):

1. Create an empty private repository (for example `infn-argus/argus-escrow`).
2. On the **local** installation: register it (*Add a repository*), add its deploy key with **write**
   access, confirm the fingerprints, **Read and write** test. Under its signing key, **Copy** the public
   line (the local deployment provides one; or *Make a signing key*).
3. On **production**: register the same repository (its own deploy key, read access is enough), confirm,
   test; under **Trusted keys**, paste the local public line and **Trust it**.

**Each time:**

4. **Local → Export**: *Everything (a full archive)*, purpose *Migration*, people *Full identity*,
   repository the one above, **Where the data goes**: *In the repository, with the archive*. Approve,
   Generate, Publish to Git; note the tag.
5. **Production → Import**: source *Git*, the repository, the tag, mode **clone**. Then Fetch into
   quarantine, Verify, Dry run, Approve, Execute, Finalize.

Without a shared Git server, copy the local repository instead: export to the local `escrow-dev` with the
data in the repository, copy `/data/portability/dev/escrow.git` into production's portability volume
(`kubectl -n argus cp escrow.git <api pod>:/data/portability/escrow-local.git`), and register it on
production with the address `/data/portability/escrow-local.git`.

Then set up on production what an export does not carry: the AI endpoint (*AI endpoint*, then *Build the
index*) and import configurations (*Imports*). The local
installation's test users come along with *Everything*; remove or deactivate the ones you do not want
afterwards (*Administration → Users*).

## Rebuild an installation from its archive

When an installation is lost (a wiped server or laptop, a deleted volume), a new, empty one is filled again
from the last export in the Git repository.

**Keep these outside ARGUS, before you need them.** They live in the installation, so they are lost with it:
- the **public line** of each installation's signing key (*Copy*, under *This installation's signing key*):
  without it, the new installation cannot trust the archive. Keep it in a password manager or in the
  repository's README. Do not trust a key taken from the archive itself, unless you can compare it with
  the one you kept;
- the signing key itself, where the deployment provides it (production: its Kubernetes Secret), so the
  rebuilt installation keeps signing with the same key;
- exports whose data is **In the repository, with the archive**. An archive whose data went to an
  artifact store needs a surviving copy of that store: if its only copy was on the lost installation, the
  checkpoint alone cannot restore the data.

**Then, on the new installation:**
1. Sign in as its first administrator (the deployment's `ARGUS_BOOTSTRAP_ADMINS`). A new installation
   opens on a workspace of its own, *Main*; leave it empty.
2. **Administration → Portability → Set-up**:
   - **Add a repository** with the same address. It gets a **new deploy key**: add it to the repository
     (and remove the lost installation's), **Confirm the fingerprints**, test with **Read**.
   - Under **Trusted keys**, paste the public line you kept and press **Trust it**.
   - Make a signing key for this installation (or let the deployment provide the old one), and keep its
     public line.
3. **Import**: source *Git*, the repository, the tag of the latest **full** export. Mode **restore** to
   become the lost installation again (it needs an archive made with *Full identity*, and an installation
   with nothing in it but the empty *Main*); otherwise **clone**. Then follow *Import, step by step*.
   An increment builds on its full export: import the full one first, then each increment in order.
4. **Set up again what an export does not carry**: the AI endpoint (then *Build the index* in each
   workspace), import configurations, **robot and personal tokens** (machines such as a facility's
   logbook uploader need new ones), and field devices. People get back their access by signing in.

What an archive holds is what existed when it was made: data that came later, or kinds of data the
archive did not yet carry (before 1.35: beam models, global values, groups, equipment classes), have to be
brought back by hand.

## Check the result after finalizing

Compare the workspaces and record counts with the dry run and the reconciliation. Open a few assets, tickets,
documents and attachments, and check their relations, revision history and beam-model bindings. Review the
roles and the people imported, test users included.

Then set up again what an archive does not carry: the AI endpoint and its index, new integration tokens, field
devices. Check that a few people can sign in, see what they should and find what they search for, before handing
the installation over.

## When something goes wrong

| What you see | What it means, and what to do |
|---|---|
| *no signing key is configured* | this installation cannot export yet: **Set-up → Make a signing key** (or the deployment's `ARGUS_PORTABILITY_SIGNING_KEY`) |
| *setting up portability from the web app is switched off* | this installation takes its set-up only from the deployment (`ARGUS_PORTABILITY_UI_CONFIG=off`) |
| Test fails: *Host key verification failed* | the server's host keys changed since they were confirmed: **Read them again**, compare, confirm |
| Test fails: *Permission denied (publickey)* or *403* | the deploy key or token is not on the repository, or lacks write access |
| *an artifact store is needed* | in the export form choose where the data goes: *In the repository, with the archive*, or an artifact store (Set-up → Artifact stores) |
| *artifact store 'vault-dev' is not configured here* | the export kept its data in a separate store: the importing installation needs a store with that same name, holding a copy of the exporter's files. Export again with the data in the repository to avoid it |
| *push refused* mentioning a file size | a data file is above the provider's limit (100 MB on GitHub): use an artifact store for that export |
| Verify fails on the signature | the exporter's public key is not in this installation's trusted keys, or the archive was changed |
| *another administrator must approve* | the policy wants two people: ask a second administrator |
| Dry run blocked: *same key, different content, not from this chain* | records with the same id already exist here, made here and different: ARGUS never overwrites them. Look at the conflicting records and the reconciliation with the administrator responsible, then resolve them deliberately or discard the import. Do not delete records here just to make the import pass |
| Dry run blocked: unresolved references | the archive refers to records neither side has (for example deleted ones): look at what refers to them first; when that is acceptable, choose *leave unresolved and list them in the reconciliation* and run the dry run again |
| Execute stopped half way | **Resume in staging**; nothing reached the real database |
| Finalize reports a difference | nothing was committed; read the reconciliation, then retry or Discard |
| Not enough space | an import needs room for the files in quarantine and the staging database; ask for disk space first |
