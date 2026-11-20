# ARGUS on the LNF k8sda cluster

A second installation of ARGUS, beside INFN Cloud's, on the shared k8sda cluster
(`kubectl --kubeconfig ~/kubeconfigs/kubeda/config`), reached from the internet. Every release deploys to both
(`.github/workflows/release.yml` sets the image tags in `values-production.yaml` and `values-k8sda.yaml`).

| | |
|---|---|
| Web | `https://argus-hub.k8sda.lnf.infn.it` |
| API | `https://argus-hub-api.k8sda.lnf.infn.it` |
| Namespace | `argus-hub` (Argo CD application `argus-hub`, project `argus-hub`) |
| Public entry | namespace `ingress-public`: its own nginx, class `nginx-public`, address `192.168.108.226` |
| Manifests | `deploy/k8sda/` (applied once by hand); the chart with `values-k8sda.yaml` (Argo CD, from `main`) |

## Why it is built this way

k8sda runs the accelerators' control systems (btf, sparc, eli, euaps…), GitLab, Keycloak and more. Their sites
are served by the cluster's shared nginx (`rke2-ingress-nginx`, `*.k8sda.lnf.infn.it` → 192.168.108.10), most
over plain HTTP, and their namespaces have no network policies. Exposing that nginx would expose all of them.
So the internet reaches ARGUS through a separate entry, and ARGUS is walled off from everything else:

1. **Its own ingress controller** (`deploy/k8sda/40-ingress-public.yaml`): class `nginx-public`, its own MetalLB
   address, and it watches the `argus-hub` namespace only. An ingress of class `nginx-public` made in another
   namespace is ignored, and the shared nginx's sites are not served on this address. It hides its version,
   sends HSTS and security headers, refuses snippet annotations, limits slow clients, and limits requests and
   connections per client address, higher for INFN's networks (see "Request limits"). Its pods run only on
   the nodes MetalLB announces VLAN 108 from (`lb-network-access=vlan-108`): with `externalTrafficPolicy:
   Local` a pod elsewhere would leave the address unanswered.
2. **The controller's namespace is closed** (`10-ingress-public-policy.yaml`): in only on 80, 443 and the
   admission webhook; out only to ARGUS's web and API (and cert-manager's solver), DNS and the Kubernetes API.
3. **ARGUS's namespace is closed both ways** (the chart's `networkPolicy`): everything is denied, then only the
   public controller reaches the web and the API; only the API and its jobs reach PostgreSQL; the API goes out
   only to DNS and to public internet addresses on 443, 587 and 465 (INFN AAI, INFN mail, Gmail, the AI
   gateway, GitHub). 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, link-local and shared address space are
   excluded: a pod taken over cannot reach another namespace, a cluster service or an LNF host. A private
   address ARGUS does need is named in `networkPolicy.allowedPrivateEgress`.
4. **Pods hardened** (`security.hardened`), and the namespace enforces Pod Security `restricted`: no Kubernetes
   service-account token, non-root users (API and jobs 10001, PostgreSQL 999, nginx 101), no capabilities, no
   privilege escalation, the runtime's seccomp profile, the web's filesystem read-only.
5. **Bounded** (`quota`): a ResourceQuota and default limits, no LoadBalancer or NodePort services of its own.
6. **Deployed only where it belongs**: the Argo CD project `argus-hub` lets these two applications write only to
   `argus-hub` and `ingress-public`, and only the cluster-wide objects the controller needs.
7. **Its own certificates**: ClusterIssuer `letsencrypt-public` answers Let's Encrypt's HTTP-01 check through the
   public controller.

The web image is the same as INFN Cloud's: `web.runtimeConfig` tells it, at start (`/config.js`), where this
installation's API is.

## What LNF's network service has to do

- Forward a public address's TCP 80 and 443 to **192.168.108.226** (nothing else of the cluster).
- Public DNS: `argus-hub.k8sda.lnf.infn.it` and `argus-hub-api.k8sda.lnf.infn.it` → that public address.
  Inside LNF they should resolve to 192.168.108.226: today the wildcard `*.k8sda.lnf.infn.it` sends them to
  the shared nginx (192.168.108.10), which does not serve them.

Until then ARGUS answers only inside LNF, with nginx's own certificate; Let's Encrypt issues the real ones
once the names resolve publicly (cert-manager retries by itself).

INFN AAI: the client `argus-knowledge-hub` needs the redirect URI `https://argus-hub.k8sda.lnf.infn.it/auth/callback`
(and the web origin) beside INFN Cloud's.

## First installation

1. `kubectl apply -f deploy/k8sda/00-namespaces.yaml -f deploy/k8sda/10-ingress-public-policy.yaml
   -f deploy/k8sda/20-cluster-issuer.yaml -f deploy/k8sda/30-argocd-project.yaml -f deploy/k8sda/40-ingress-public.yaml`
2. The Secrets, made by a person, never in Git. `token-pepper` and `import-secrets-key` must be **INFN
   Cloud's** when its data is moved here (tokens and stored import credentials are sealed with them); the
   database password is new. Copied from one cluster to the other without being shown:

   ```sh
   CLOUD="kubectl --kubeconfig $HOME/kubeconfigs/cloud-config.txt -n argus"
   K8SDA="kubectl --kubeconfig $HOME/kubeconfigs/kubeda/config -n argus-hub"
   PW=$(openssl rand -hex 24)
   $K8SDA create secret generic argus-secrets \
     --from-literal=postgres-password="$PW" \
     --from-literal=database-url="postgresql://argus:$PW@argus-postgres:5432/argus" \
     --from-literal=token-pepper="$($CLOUD get secret argus-secrets -o jsonpath='{.data.token-pepper}' | base64 -d)" \
     --from-literal=import-secrets-key="$($CLOUD get secret argus-secrets -o jsonpath='{.data.import-secrets-key}' | base64 -d)" \
     --from-literal=back-end-client-oauth="$($CLOUD get secret argus-secrets -o jsonpath='{.data.back-end-client-oauth}' | base64 -d)"
   $CLOUD get secret argus-smtp -o json | jq '{apiVersion, kind, type, data, metadata: {name: .metadata.name}}' | $K8SDA apply -f -
   unset PW
   ```

   (`argus-portability`, the portability signing keys, likewise if exports are signed here.)
3. `kubectl apply -f deploy/k8sda/50-argus-hub.yaml`: Argo CD installs the chart from `main`.

## Moving INFN Cloud's data here

With both running and INFN Cloud reachable: stop writes on INFN Cloud (scale its API to 0), dump its database
(`pg_dump -Fc` in its PostgreSQL pod), restore it into `argus-postgres` here (`pg_restore --clean --if-exists`),
copy the attachments volume (`/data/attachments`), start the API (its migrations bring the schema up to date),
check, then point the users (and the mobile app's server address) here. Or an export and import
(Administration → Portability) when moving a workspace at a time.

## Request limits

The public controller counts requests and connections per client address, in two tiers
(`http-snippet`/`location-snippet` in `deploy/k8sda/40-ingress-public.yaml`):

| | Requests per second | Burst | Connections at once |
|---|---|---|---|
| INFN's networks, and LNF's private ones reaching 192.168.108.226 from inside | 150 | 750 | 200 |
| The rest of the internet | 30 | 150 | 40 |

Past them nginx answers 429. INFN's networks are the RIPE objects of organisation `ORG-INDF53-RIPE` ("INFN"),
collapsed (87 IPv4 and 18 IPv6 blocks, taken 2026-11-20); refresh them from
`https://rest.db.ripe.net/search.json?inverse-attribute=org&query-string=ORG-INDF53-RIPE&type-filter=inetnum&type-filter=inet6num`
when INFN's address space changes. The tiers rely on nginx seeing each client's own address: LNF's firewall must
forward (DNAT) without rewriting the source. If it rewrote it, every client from the internet would share one
address — and, rewritten to a private one, the INFN tier.

## Metrics

The cluster's kube-prometheus-stack (namespace `monitoring`, release `prometheus`, Grafana at
`grafana.k8sda.lnf.infn.it`) scrapes:

- **the public controller** (ServiceMonitor): requests, status, latency and bytes per host;
- **the API** (`metrics.enabled`, PodMonitor, port 9100, never in the Service nor through the ingress):
  `argus_http_requests_total` and `argus_http_request_duration_seconds` by route template, method and status,
  `argus_http_requests_in_flight`, the database pool (`argus_db_pool_*`) and the hourly storage measurement
  (`argus_storage_*_bytes` by area: local-path volumes report nothing to the kubelet);
- **PostgreSQL** (postgres_exporter beside it, port 9187): connections, transactions, cache hits, size;
- CPU and memory of every pod (cAdvisor and kube-state-metrics, already there).

Network policies let only the Prometheus pods of `monitoring` reach the two ports. The dashboard is
`deploy/k8sda/grafana-argus.json` (Grafana → Dashboards → New → Import; pick the Prometheus data source).

## When to scale

The chart's PrometheusRule `argus` raises a warning when one of these holds (thresholds in `metrics.rules`):

| Alert | Holds when | First thing to do |
|---|---|---|
| `ArgusApiSlow` | the API's 95th percentile above 1 s for 15 min | see whether CPU or the pool is the limit; more API replicas for CPU |
| `ArgusDbPoolBusy` | over 80% of the pool's connections in use for 10 min | slow queries first; then PgBouncer and more replicas |
| `ArgusPostgresConnections` | over 80% of PostgreSQL's `max_connections` | PgBouncer before any more replicas |
| `ArgusMemoryNearLimit` | a container over 85% of its memory limit for 15 min | raise the limit (and the quota) |
| `ArgusApiErrors` | over 5% of answers 5xx for 10 min | the API's logs |
| `ArgusRateLimited` | over 0.5 requests/s refused with 429 for 10 min | the controller's log: a flood, or a tier to raise |
| `ArgusStorageFilling` | an area full within 14 days at the current rate | enlarge the volume and `requests.storage` |

Where they are sent depends on the cluster's Alertmanager; they show in Prometheus and Grafana regardless.
Scaling out (more replicas, shared volumes, migrations in a Job, PgBouncer, a replicated PostgreSQL) is not
done yet: these numbers say when it is needed.

## Checks

- `curl -k --resolve argus-hub.k8sda.lnf.infn.it:443:192.168.108.226 https://argus-hub.k8sda.lnf.infn.it/`
  answers ARGUS; the same address with another k8sda host (`btf-olog…`) answers 404.
- From a pod in another namespace, `argus-postgres.argus-hub:5432`, `argus-api.argus-hub:80` do not answer.
- `kubectl -n argus-hub exec deploy/argus-api -- python -c "import socket; socket.create_connection(('192.168.108.10', 80), 3)"`
  times out (no way into the LNF networks); `('idp-test.app.infn.it', 443)` connects.
