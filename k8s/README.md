# Deploying ARGUS Knowledge Hub

The hub runs on the INFN cloud cluster (`kubectl --kubeconfig ~/kubeconfigs/cloud-config.txt`) as the
Helm chart in [`charts/argus-knowledge-hub`](../charts/argus-knowledge-hub), deployed by Argo CD
([`argocd/application.yaml`](argocd/application.yaml)) into the namespace `argus`. The chart is the
docker-compose setup for a cluster:

| Part | What it is | Address |
|---|---|---|
| `argus-postgres` | Postgres 16 with pgvector (Ask ARGUS's written-knowledge search); also Keycloak's database | inside the cluster |
| `argus-api` | the API; migrates the database when it starts | `https://argus-hub-api.90.147.174.30.myip.cloud.infn.it` |
| `argus-web` | the web app | `https://argus-hub.90.147.174.30.myip.cloud.infn.it` |
| `argus-keycloak` | a temporary Keycloak, realm `argus`, for sign-in until INFN's is used | `https://keycloak.90.147.174.30.myip.cloud.infn.it` |

Google sign-in (Firebase) keeps working next to Keycloak: the API accepts both (`api.extraProviders`).
Certificates come from cert-manager (`letsencrypt-prod-issuer`) through the nginx ingress.

```
KC="kubectl --kubeconfig ~/kubeconfigs/cloud-config.txt"
```

## Releases: a tag is a deployment

```
git tag v1.34.0 && git push origin v1.34.0
```

`.github/workflows/release.yml` then:

1. runs the backend tests inside the backend image, against Postgres with pgvector, and type-checks
   and builds the web app; a failure stops the release before anything is pushed;
2. builds both images and pushes them to ghcr.io as `1.34.0` and `latest`. The web app is built
   with the production Keycloak and API addresses (`WEB_KEYCLOAK`, `WEB_API` in the workflow);
3. commits `Deploy 1.34.0` to `main`, setting the image tags in
   `charts/argus-knowledge-hub/values-production.yaml`.

Argo CD follows `main` and rolls that version out. Going back is reverting the `Deploy` commit.
Argo CD never deletes (`prune: false`) and puts back hand edits to what it manages (`selfHeal`).
The volumes are also marked to be kept if the chart or the Application is removed.

## Storage

The volumes are `local-path`: each lives on one node's own disk, and its size is not enforced; the real
limit is that disk's free space. The nodes are small (vnode-0, the control plane, 21 GB with under
2 GB free; vnode-1 and vnode-2, 42 GB each), so `values-production.yaml` places each part:

| Volume | Planned | Node |
|---|---|---|
| `argus-postgres-data` | 10 Gi | vnode-1 |
| `argus-attachments` | 15 Gi | vnode-2 (with the API) |
| `argus-portability` | 5 Gi | vnode-2 (with the API) |

Check the free space before a large import:
`$KC get --raw /api/v1/nodes/vnode-2/proxy/stats/summary | jq '.node.fs.availableBytes/1e9'`.
More room needs bigger node disks or a network storage class.

Container images share those disks, and every release pulls new ones; Kubernetes only removes unused
ones once a disk is about 85% full. So the chart removes them itself: `argus-image-prune-<node>`, one
CronJob per node (`imagePrune.nodes`), every two days from 04:00, runs RKE2's `crictl rmi --prune` on
that node, which leaves every image a container uses. To run one now:
`$KC -n argus create job --from=cronjob/argus-image-prune-vnode-2 prune-now`.

## Setting it up, once

1. **The packages accept the workflow.** On GitHub, for each of `argus-knowledge-hub-backend` and
   `argus-knowledge-hub-web`: *Package settings → Manage Actions access → Add repository*
   `infn-argus/argus-knowledge-hub`, role **Write**.
2. **The workflow may push to `main`.** If `main` is protected, let `github-actions[bot]` push the
   `Deploy` commit.
3. **The Secret**, never in Git:
   ```
   $KC create namespace argus
   PG=$(openssl rand -hex 24)
   $KC -n argus create secret generic argus-secrets \
     --from-literal=postgres-password="$PG" \
     --from-literal=database-url="postgresql://argus:$PG@argus-postgres:5432/argus" \
     --from-literal=token-pepper="$(openssl rand -base64 32)" \
     --from-literal=import-secrets-key="$(python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')" \
     --from-literal=keycloak-admin-password="$(openssl rand -base64 18)"
   ```
   The token pepper is mixed into every API token's hash: changing it invalidates every token.
4. **Argo CD takes over:** `$KC apply -f k8s/argocd/application.yaml`.

## After the first start

- **Keycloak's admin:** `https://keycloak.90.147.174.30.myip.cloud.infn.it/admin`, user `admin`, password
  `$KC -n argus get secret argus-secrets -o jsonpath='{.data.keycloak-admin-password}' | base64 -d`.
  The realm `argus` has no users: add them under *Users*, with a temporary password.
- **The first ARGUS administrators** are the emails in `ARGUS_BOOTSTRAP_ADMINS` (`api.env` in
  `values-production.yaml`): they are administrators from their first sign-in. An administrator with no
  workspace yet is offered to create one on the workspace screen. Anyone else is made an administrator
  in the app, or in the pod:
  `$KC -n argus exec deploy/argus-api -- python scripts/argus_admin.py user add <email> --admin`.
- **IOC pull requests (optional).** Ask ARGUS can open the pull requests the IOC engineer drafts, once a
  person confirms them (docs/ioc-engineer.md). It stays off until the Secret holds `ioc-github-token`: a
  fine-grained token, or a GitHub App's, with *Contents* and *Pull requests* read and write on the
  repositories in `iocEngineer.pullRequests.repositories` only:
  `$KC -n argus patch secret argus-secrets -p '{"stringData":{"ioc-github-token":"<token>"}}'`, then restart the API.
- **An API token for scripts:** `$KC -n argus exec deploy/argus-api -- python scripts/create_token.py
  <workspace> "<name>" cli`. It is printed once.

## Portable exports and imports

Repositories, trusted keys and the signing key can be registered by an administrator in the web app,
*Administration → Portability → Set-up* (on by default; `ARGUS_PORTABILITY_UI_CONFIG: "off"` under
`api.env` switches it off). They can also be set here, in the deployment, which then comes first:
settings go in `api.env` in `values-production.yaml` (`docs/operations.md`, "Configuration"), keys in
the Secret `argus-portability`, mounted at `/etc/argus/portability` when it exists
([`portability-secret.example.yaml`](portability-secret.example.yaml) shows its keys; it is a template,
never applied). Scheduled work is in the chart: a daily cleanup, which removes the files of finished
exports and imports after one day in production (`ARGUS_PORTABILITY_POLICY_RETENTION_DAYS`), and a
restore drill twice a year, created suspended (`portabilityJobs`). Background: `docs/export-import-design.md` §20.

### Keys (on an administrator's machine, not the cluster)

```
ssh-keygen -t ed25519 -N '' -C argus-portability -f signing_key
echo "argus-portability namespaces=\"git,argus-archive\" $(cat signing_key.pub)" > allowed_signers
ssh-keygen -t ed25519 -N '' -C argus-escrow-deploy -f deploy-key-escrow
ssh-keyscan <git server> > known_hosts        # check the fingerprint against the Git server's
openssl rand -base64 32 > pseudonym-salt
```

An instance that imports what another exported trusts that instance's signing key: add the other
instance's `allowed_signers` line to this one's. Register `deploy-key-escrow.pub` on the repository as a
deploy key (write access to export, read-only to import only).

```
$KC create secret generic argus-portability -n argus \
  --from-file=signing_key --from-file=allowed_signers \
  --from-file=deploy-key-escrow --from-file=known_hosts \
  --from-literal=pseudonym-salt="$(cat pseudonym-salt)"
```

and in `values-production.yaml`, under `api.env`:

```
ARGUS_PORTABILITY_REPOSITORIES: escrow=ssh://git@<git server>/<path>.git
ARGUS_PORTABILITY_SIGNING_KEY: /etc/argus/portability/signing_key
ARGUS_PORTABILITY_SIGNER: argus-portability
ARGUS_PORTABILITY_TRUSTED_KEYS: /etc/argus/portability/allowed_signers
ARGUS_PORTABILITY_REPOSITORY_KEYS: escrow=/etc/argus/portability/deploy-key-escrow
ARGUS_PORTABILITY_SSH_KNOWN_HOSTS: /etc/argus/portability/known_hosts
```

**An encrypted archive** is the only time a recipient private key enters the cluster:

```
$KC create secret generic argus-portability-decryption -n argus --from-file=escrow-officer
# … wait a minute for the files to appear, then verify, dry run, approve, execute, finalize …
$KC delete secret argus-portability-decryption -n argus
```

**Staging databases.** By default an import stages in the active Postgres. A dedicated role is safer:

```
$KC -n argus exec deploy/argus-postgres -- psql -U argus -d argus -c \
  "CREATE ROLE argus_importer LOGIN CREATEDB PASSWORD '<generated>'"
```

then `ARGUS_PORTABILITY_STAGING_URL: postgresql://argus_importer:<generated>@argus-postgres:5432/argus` in a
Secret-backed value. Exclude `argus_stage_*` and `argus_drill_*` databases from backups.

**The restore drill** is created suspended. After the first full export:
`$KC -n argus patch cronjob argus-portability-restore-drill -p '{"spec":{"suspend":false}}'`, or set
`portabilityJobs.restoreDrill.suspend: false`.

### Annual rotation

1. Generate a new signing key and add its allowed-signers line on every importing instance.
2. Replace `signing_key` (and `allowed_signers`) in the Secret.
3. Restart the API: `$KC -n argus rollout restart deploy/argus-api`.
4. Run one export and a manual drill:
   `$KC -n argus create job --from=cronjob/argus-portability-restore-drill drill-rotation`.
5. Rotate the deploy key the same way, and revoke the old one on the Git server.

## Building images by hand

`backend/deploy.sh <version>` and `webapp/deploy.sh <version>` build and push to ghcr.io (after
`docker login ghcr.io` with a PAT that has `write:packages`). The web app built that way has no
Keycloak address: pass the `VITE_*` build arguments the workflow passes. Then set the tags in
`values-production.yaml` on `main`; Argo CD does the rest.
