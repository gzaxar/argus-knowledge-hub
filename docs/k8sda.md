# ARGUS on the LNF k8sda cluster

A second installation of ARGUS, beside INFN Cloud's, on the shared k8sda cluster
(`kubectl --kubeconfig ~/kubeconfigs/kubeda/config`), reached from the internet. Every release deploys to both
(`.github/workflows/release.yml` sets the image tags in `values-production.yaml` and `values-k8sda.yaml`).

| | |
|---|---|
| Web | `https://argus-hub.lnf.infn.it` |
| API | `https://argus-hub-api.lnf.infn.it` |
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
- DNS, split-horizon: `argus-hub.lnf.infn.it` and `argus-hub-api.lnf.infn.it` resolve on the internet to that
  public address, inside LNF to **192.168.108.226** directly.

One name for each, inside and out: the web knows one API address (`web.runtimeConfig`), INFN AAI one redirect,
e-mails one link, the mobile app one server, and a browser keeps one session. They are names of the service,
not of the cluster (outside `*.k8sda.lnf.infn.it`, which leads to the shared nginx), so they outlive a move to
another cluster.

Until then ARGUS answers only where the names resolve to 192.168.108.226, with nginx's own certificate; Let's
Encrypt issues the real ones once the names resolve publicly (cert-manager retries by itself).

INFN AAI: the client `argus-knowledge-hub` needs the redirect URI `https://argus-hub.lnf.infn.it/auth/callback`
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

   Without INFN Cloud's keys (it unreachable, or its data brought here by an export rather than a dump),
   `token-pepper` and `import-secrets-key` are new random values; personal tokens and stored import
   credentials are then made again. `back-end-client-oauth` (JSON `{"client_id": …, "client_secret": …}`)
   and `argus-smtp` are optional: without them e-mail goes through LNF's relay `smtp.lnf.infn.it:587`
   (STARTTLS, no account — the nodes are inside LNF), which delivers to INFN addresses only.
3. `kubectl apply -f deploy/k8sda/50-argus-hub.yaml`: Argo CD installs the chart from `main`.

## Moving INFN Cloud's data here

With both running and INFN Cloud reachable: stop writes on INFN Cloud (scale its API to 0), dump its database
(`pg_dump -Fc` in its PostgreSQL pod), restore it into `argus-postgres` here (`pg_restore --clean --if-exists`),
copy the attachments volume (`/data/attachments`), start the API (its migrations bring the schema up to date),
check, then point the users (and the mobile app's server address) here. Or an export and import
(Administration → Portability) when moving a workspace at a time.

## Getting out: LNF's proxy

k8sda's nodes have no direct way to the internet's web: HTTP and HTTPS go through LNF's proxy
`squid.lnf.infn.it:3128` (193.206.84.225), as Argo CD's do. The API and its jobs carry `HTTPS_PROXY`,
`HTTP_PROXY` and `NO_PROXY` (`api.env` in `values-k8sda.yaml`), and the network policy opens that address on
3128 only (`networkPolicy.allowedPrivateEgress`). Through it go INFN AAI's and Google's signing keys, the INFN
mail service, the AI gateway, and imports and exports:

- **Git (portability, IOC pull requests):** over HTTPS with a token (`ARGUS_PORTABILITY_REPOSITORY_TOKENS`).
  SSH (port 22) does not pass, neither LNF's firewall nor the policy: a repository is named by its
  `https://` address, e.g. `https://baltig.infn.it/infn-epics/argus-knowledge.git`.
- **Imports that fetch** (Jira, GLPI, web pages, catalogues, model providers): HTTP(S) through the proxy.
  A source on LNF's private networks (192.168.x, 10.x) is not proxied (`NO_PROXY`) and is closed by the
  policy: name it in `networkPolicy.allowedPrivateEgress` with its ports.
- **Coming in:** uploads, imported archives and downloaded exports pass the public controller, up to 1 GB a
  request with 10 minutes to answer (`templates/ingress.yaml`).
- **Mail** does not use the proxy: SMTP goes to `smtp.lnf.infn.it:587` directly.

The proxy is LNF's: what it lets through (and logs) is decided there, not by ARGUS.

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
  and the application's own statistics (`backend/app/services/app_metrics.py`), read from the database at most
  once a minute (`ARGUS_APP_METRICS_SECONDS`; `ARGUS_APP_METRICS=off` turns them off): `argus_active_people`
  (by window and client), `argus_records`, `argus_records_created`, `argus_records_changed` (by workspace and
  kind), `argus_tickets_open` (by workspace and state), `argus_service_requests_open`,
  `argus_service_request_oldest_open_seconds` and `argus_service_requests_created` (the help centre, by site and
  service), `argus_llm_calls`, `argus_llm_failures`, `argus_llm_tokens` (by workspace and model),
  `argus_ask_questions`, `argus_ask_answers`, `argus_ask_feedback`, and `argus_app_metrics_up`. Windows are 1d, 7d
  and 30d. Labels never name a person. Every replica reports the same values: a panel takes `max`, not `sum`;
- **PostgreSQL** (postgres_exporter beside it, port 9187): connections, transactions, cache hits, size;
- CPU and memory of every pod (cAdvisor and kube-state-metrics, already there).

Network policies let only the Prometheus pods of `monitoring` reach the two ports. The dashboard is
`deploy/k8sda/grafana-argus.json`, imported in Grafana's organisation **System** ("ARGUS Knowledge Hub").

Grafana itself goes out through LNF's proxy, and its `NO_PROXY` exempts only names ending in `.svc`: a
Prometheus data source addressed by the bare service name (`http://prometheus-kube-prometheus-prometheus:9090`,
as the existing ones were in 2026-11) is sent to the proxy and answers 503. The dashboard uses the data source
`Prometheus (cluster, .svc)` (uid `argus-prometheus`), at `http://prometheus-kube-prometheus-prometheus.monitoring.svc:9090`.

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

- `curl -k --resolve argus-hub.lnf.infn.it:443:192.168.108.226 https://argus-hub.lnf.infn.it/`
  answers ARGUS; the same address with another k8sda host (`btf-olog…`) answers 404.
- From a pod in another namespace, `argus-postgres.argus-hub:5432`, `argus-api.argus-hub:80` do not answer.
- `kubectl -n argus-hub exec deploy/argus-api -- python -c "import socket; socket.create_connection(('192.168.108.10', 80), 3)"`
  times out (no way into the LNF networks); `('idp-test.app.infn.it', 443)` connects.
