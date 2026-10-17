# ARGUS Knowledge Hub

Structured-knowledge backbone for **ARGUS** (*AI-based Retrieval-Grounded Understanding and
Supervision for Accelerator Operations*, INFN CSN5).

It manages the three bodies of structured knowledge an accelerator facility needs to keep
alongside its live machine data — **assets & spare parts**, **tickets/incidents** and
**controlled documentation** — and exposes them over a REST API so they can feed ARGUS'
hybrid knowledge layer (Knowledge Graph + vector retrieval).

Within the ARGUS work-package breakdown this is the data substrate for **WP3 — AI-Native
Services** (*Asset & Maintenance Management*, *Intelligent Incident Management*) and a source
for **WP2 — Hybrid Knowledge Layer**.

## Why it matters for ARGUS

The typed `Asset` + `Relation` model is already a property graph: a chain such as

```
EPICS IOC → serial port → Ethernet/serial converter → power supply → quadrupole magnet
```

is stored as typed relations between assets, which is exactly the topology ARGUS walks for
root-cause analysis. Documents carry a full revision workflow (draft → review → approved →
published → superseded/retired) so retrieval can be pinned to the *currently published,
currently valid* revision rather than to an arbitrary PDF.

## Components

| Path       | What it is                                                                 |
|------------|----------------------------------------------------------------------------|
| `backend/` | FastAPI + SQLAlchemy + Alembic on PostgreSQL. REST API, imports, auth/RBAC. |
| `webapp/`  | React + TypeScript + Vite + Tailwind operator/admin UI.                     |
| `charts/`  | The Helm chart (Postgres with pgvector, API, web app, Keycloak) Argo CD deploys. |
| `k8s/`     | The Argo CD Application and the deployment notes.                            |

## Main capabilities

- **One application for assets, service and knowledge.** Every asset shows its tickets and the
  documents that apply to it (its own, its product model's and its type's); every ticket shows its
  equipment, the relevant procedures and what else is open on that equipment; every document shows
  where it applies and what is broken there. A single search (Ctrl/⌘ K) covers all three, and the
  operations cockpit opens on what needs attention. Served by `/v1/hub` (`search`, `overview`,
  `assets|tickets|documents/{uid}/context`), which fills each section only for callers who may read it.
- **Workspaces** with per-user, per-resource permissions (read/create/modify/delete/approve),
  OIDC sign-in (*INFN login* through Keycloak, which can also offer Google; Google through
  Firebase on the web) plus API tokens for automation. The ARGUS Field mobile app signs in through
  Keycloak and can ask the assistant by voice.
- **Types (schemas)** with inheritance: attributes are inherited down the hierarchy, and a type
  can be marked *global* to be referenced across workspaces.
- **Assets** with typed attributes (string/number/date/enum/reference/user/…), typed relations,
  attachments, comments, history and labels.
- **Tickets** with configurable types and a status workflow (New → In Progress → Pending →
  Resolved → Closed), priority, assignee and links to the affected asset.
- **Documentation** with the controlled revision workflow described above, confidentiality
  levels, authority levels and relations to assets/types/other documents.
- **Global values**: shared enumerations (status, priority, …) scoped per context.
- **Imports** from Jira Insight/Assets and from Git repositories, with saved, re-runnable
  import configurations and merge strategies (override / don't override / update-if-newer).
  Imports never delete: a re-import keeps values people edited since the last run (import
  snapshots) and records the commit it read. The old wipe-and-reimport strategy is retired.
- **Fact ledger and installations.** Sources (EPIK8s configuration, Insight) are ingested as
  revisions of claims in an append-only ledger; an authority policy decides which source owns
  each fact, people's confirmations stick, and every value on a record can show where it came
  from (*Provenance* tab). A position's history of installed units is kept as Installation
  records, with swaps and "what was installed on date X" queries. A revision that would retire
  too much is held, and conflicts, inferred facts and proposed installations wait in the
  *Review queue*. Served by `/v1/ledger` and `/v1/installations`.
- **Connectivity and attribution.** An address's Access Point is assigned to one position, once:
  when the configuration moves the address, the old Access Point retires with a successor and
  keeps its tickets, and "who used this address on date X" answers with a certainty around the
  handover. Bus segments attach to the port of whichever unit is installed now, but only on a
  unique, registry-backed, compatible match; safety-classed segments need a person to confirm
  the port for each new installation. Tickets are linked to the unit installed at incident time,
  and counts never add up the same ticket twice. Inference rules are versioned: a new meaning
  needs a new rule id, which a CI check enforces (`python -m app.ledger.rules`). Served by
  `/v1/access-points` and `/v1/ledger` (`segments`, `tickets`, `rules`, `rulesets`).
- **Migration from Jira and Insight, domain by domain.** A migration domain moves through the
  stages T0 Prepare … T5 Retire (*Migration to ARGUS*). While a domain is imported and shadowed,
  ARGUS holds it read-only (no dual write); at cutover its streams are frozen at the watermark W,
  and a reconciliation report compares the export manifest with ARGUS — records, comments,
  history, links, attachments by SHA-256, workflow states and users. The exit is signed only
  when every difference is resolved or explained and the criteria hold; ARGUS is then the
  system of record. Old Jira keys, Jira URLs, Insight keys and objectIds resolve through
  `/lookup/<key>`, or point to the archive when never migrated. Served by `/v1/domains`,
  `/v1/lookup` and `/v1/export` (JSON lines).
- **Identity.** Insight objects are bound by their objectId, so a re-keyed object stays the same
  record with its old key as an alias. Different source objects sharing a serial (per
  manufacturer), inventory number or MAC become a review item — merged by a person, never
  automatically — and once a scope is cut over, creating a duplicate is refused.
- **Restricted records.** A record or ticket classified `restricted:<class>` (costs, personnel,
  security incidents, safety investigations, sensitive designs) is absent from lists, search,
  counts, exports, MCP tools and the ledger views for anyone without that grant, and appears in
  graphs only as an anonymous node. Grants come from a role's `restricted` permissions or a
  token's `restricted_grants`.
- **Equipment lifecycle, custody and spares.** A unit's lifecycle moves only along allowed
  transitions (Installed follows from its installation); custodian and location keep their full
  history with who changed them and when; designated spares show whether they are available, and a
  position lists the spares that fit it (*Lifecycle & custody* tab). Served by `/v1/equipment`.
- **Controlled bulk changes.** Set an attribute on, or retire, many records at once: always
  previewed first, approved by a second person above 100 records, applied as one ledger batch and
  undone as one (*Bulk changes*). Plain bulk deletes above 100 records are refused. Served by
  `/v1/bulk-changes`.
- **Tamper-evident audit log.** The ledger's audit tables are append-only in the database itself
  (a trigger refuses UPDATE and DELETE). Each day is sealed with a SHA-256 digest chained to the
  previous day (`python -m app.ledger audit-digest`, run daily; keep the digests outside ARGUS);
  `python -m app.ledger verify-audit` finds the first altered day. Every record has an audit trail
  under *Provenance*. Restricted fields (an attribute definition with `"restricted": "<class>"`)
  are hidden, and kept intact on edit, for viewers without that grant.
- **Ticket workflows.** Each ticket type follows its own workflow: states (open, active, waiting,
  done), the transitions allowed between them, and what a move needs (an assignee, a resolution,
  a comment). Jira workflows are imported as they are and rehearsed against the migrated tickets'
  Jira history before the ticket cutover. Tickets without a workflow keep the built-in one.
  Reporters and assignees watch their tickets; watchers, assignees and @mentioned people are
  notified in-app (and by e-mail with `SMTP_HOST`), never about a ticket they may not read; a state
  with an SLA escalates a ticket that outstays it. *Service desk → Workflows*; served by
  `/v1/workflows`, `/v1/issues/{uid}/transition|transitions|watchers` and `/v1/notifications`.
- **Controlled documents.** Each document has a retention class (permanent, 10, 5 or 2 years,
  or none), counted from its last publication or its retirement. A released document cannot
  be deleted before its retention runs out, only retired. Its retention can be lengthened
  but not shortened. The author of a revision cannot approve it. A document superseded by
  another retires and points to its successor. An attachment can prove it is still the file
  that was uploaded (`/v1/attachments/{uid}/verify`).
- **Roles per domain and access reviews.** Ready-made roles cover inventory and IT stewards,
  beamline operators, service-desk agents, document controllers, safety investigators,
  procurement officers and auditors, each with the restricted classes it needs. An access
  review snapshots every grant in a workspace: people directly and through groups, API
  tokens, open defaults and administrators. It shows what changed since the last review and
  is complete once enough distinct owners have signed it. *Access → access review*; served
  by `/v1/access-reviews`. What each role allows, and how access is worked out:
  [docs/roles.md](docs/roles.md).
- **Legacy migration (§12).** Records the old importer inferred are classified by their
  evidence: serials and who wrote them, labels, inventory links, photos, edits, tickets and
  history. Each becomes a Position, Equipment or an Installation, or is retired or blocked.
  First comes a decision report that changes nothing; then owners' overrides; then an apply
  that checks its invariants item by item. Rollback works until the plan is finalized. A domain
  cannot be frozen for cutover while any of its records is blocked, unreviewed or unplanned.
  The freeze itself waits for the §17.4 entry criteria: a steward and a backup, empty blocking
  queues, the other queues within their ageing targets, two weeks of shadow validation with
  10 consecutive clean runs, a recent restore rehearsal and probe run, and the attested items.
  The governance group can waive a criterion only with a reason, recorded in the freeze decision.
- **Ledger-only writes (§13 S5).** Every record created or edited through the API or the UI
  (attributes, name, relations) is a person's confirmed statement in the fact ledger, with its
  author in the record's audit trail. A workspace whose legacy records are migrated can be
  switched to ledger-only. The database then refuses any change to record facts or relations
  written around the ledger, and deleting a record retires it.
- **Relation registry (§6, §13 S7).** The registry reports every edge that breaks it: deprecated
  verbs, wrong end types, cardinality, cycles, edges to retired records. A workspace switches to
  enforce mode once each violation is fixed or accepted as an exception with a reason. From
  then on, a new edge that breaks the registry is refused.
- **Guided and AI-assisted entry (§23).** New asset, ticket and document forms have a checklist that
  works without a model. It flags missing and invalid fields, taken keys and identifiers, likely
  duplicates, channel names typed as equipment, and incident times, and it asks the next question.
  Where an AI endpoint is configured, the person describes the item or photographs its nameplate
  and the form is filled with suggestions that show their evidence and confidence. Secrets are
  removed first, and ticket causes stay hypotheses. Each call and what the person kept are
  recorded; for assets, the suggestions are AI claims in the ledger.
- **Model extensions (§5.1, §13 S8).** New areas of the model (RF distribution, cabling,
  safety, …) enter as declared extensions. An extension needs an owner, a source and a query
  that gives the expected answer on its fixture, and the test suite runs every one. Its
  relations must say how a failure travels. Admitting an extension into a catalogue adds its
  types and is recorded as a decision. *Equipment classes → Extensions*.
- **Serial line conversion (§9.1).** The old importer's Serial Lines are converted one at a time.
  Each line is retyped in place as a Bus Segment behind a Communication Path, running from its
  IOC to the Access Point. The port number becomes an advisory `required_port`, and the old
  edges are removed. The golden incidents are walked before and after; a conversion that loses
  a known cause is refused unless someone accepts the loss with a reason.
- **Equipment classes (§5.5).** Equipment with no type of its own is *Other Equipment* with a
  class from a vocabulary the catalogue owns. A monthly report shows the classes and the
  `Unclassified` share with its alert. Promotion reviews open at the §5.5 thresholds, and a
  promotion creates a type and retypes the objects in place. *Equipment classes*; served by
  `/v1/catalogue/equipment-classes`.
- **Review queues (§18.2).** Every open review item has an age in working days against its
  queue's targets. Overdue items go to the backup steward, then to the governance group
  (`ARGUS_GOVERNANCE`), once per level. The notification never names the record. The review
  queue page shows each queue's size, age distribution and escalations.
  Before a plan is finalized, a deep verification checks three things: every data invariant
  holds (I-MIG-4, also served at `/v1/ledger/invariants/report`); the relation registry's
  report got no worse (I-MIG-5); rebuilding from the ledger gives exactly the migrated state
  (I-MIG-6); and the root-cause walk still finds every cause of the teams' golden incidents,
  or a more precise one (I-MIG-7). The registry itself runs in warn mode (`/v1/ledger/registry/report`).
  *Migration to ARGUS → Legacy records*; served by `/v1/migration`.
- **Stable API and Jira retirement.** The API is versioned in its path, and a deprecated
  endpoint announces its sunset in headers at least 180 days ahead
  ([docs/api-policy.md](docs/api-policy.md)). Old Jira and Insight identifiers resolve one at a
  time or in batches (`/v1/lookup`). After retirement the Jira host redirects every old link to
  the lookup page. Jira itself is retired by one signed decision, once ARGUS has checked every
  readiness condition: domains archived, exports verified, retention decided, access reviewed,
  audit chain intact, workflows rehearsed, restore and performance evidence recent. That
  decision moves every domain to T5.
- **Operations.** Backups come with a checksummed manifest and a restore rehearsal that
  checks itself. A complete export loads into an empty instance. A probe checks the
  performance targets, and a volume generator runs them at 10× (50 000 records,
  20 000 tickets and 5 000 documents): all were met. See [docs/operations.md](docs/operations.md)
  for the results, the jobs to schedule and point-in-time recovery.
- **User guide (Help).** How to do things in ARGUS, step by step, for the people using it: signing in,
  workspaces and roles, equipment, imports, the review queue, tickets, documents, the graph, the beam
  model, Ask ARGUS, AI settings, export and import (with GitHub/GitLab, and from a local ARGUS to
  production) and administration. One set of Markdown files in `backend/app/help/guide/` is read by the
  web app's **Help** page, by Ask ARGUS (`search_help`, `read_help`, so it can walk someone through a
  task) and by MCP clients. Served by `/v1/help`. Keep it in step with the screens: when a page or
  button is renamed, rename it in the guide too (`tests/test_help_guide.py` lists the names it relies on).
- **Ask ARGUS.** A chat that answers from the workspace's own records, in any language, showing every
  lookup as it runs and writing the answer as it arrives; a follow-up continues the conversation, which
  is kept for its author, and every key an answer cites opens its record. The model works through
  read-only lookups (the same ones the hub's MCP server at `/mcp` offers to external assistants): exact
  ones for what exists (equipment by type and subtype, counts per type, the type tree, the graph, impact
  and root cause) and `search_knowledge` for what is written. That is retrieval-augmented: procedures,
  tickets and their comments, comments on equipment and the text of attached files (datasheets and
  manuals, page by page) are indexed with the workspace's embedding model in Postgres (pgvector) and
  searched by meaning and by words together, only ever returning what the person asking may read.
  Build or update the index on *Workspace → AI* (only what changed is embedded again), or
  `python -m app.services.knowledge_index <workspace|all>`, e.g. nightly. Served by `/v1/ai/chat`
  (server-sent events), `/v1/ai/conversations` and `/v1/ai/knowledge`.
  Asked to, it can also **propose changes**: create a record, change one, relate two records or remove
  a relation. A proposal changes nothing. It is checked when made (the type, the record, the type's
  attributes, the relation registry) and shown under the answer, and a record proposed in the same
  answer is referred to as `new:N` until it exists. The person applies or discards each one; applying
  runs it through the same code as the forms, with their permissions and in their name in the ledger.
  Only people who could make the change by hand are offered this, and the MCP tools stay read-only.
  Served by `/v1/ai/conversations/{id}/actions` (`/apply`, `/discard`).
- **My account and API tokens.** *My account* shows the account, the sign-in, groups and what each
  workspace's roles allow. **Personal access tokens** call the API as their owner, with chosen scopes
  and expiry. **Robot tokens** belong to a workspace, for machines such as a facility's daily-logbook
  uploader. The mobile app signs in with OIDC and PKCE as `argus-mobile` (see `docs/operations.md`).
- **AI settings.** *Administration → AI* sets the endpoint and models for the whole installation; every
  workspace without settings of its own uses them, and a workspace can switch to its own and back. A
  **re-ranker model** orders the passages Ask ARGUS's written-knowledge search finds by relevance (the
  endpoint's `/rerank`). *Workspace → AI* holds a workspace's own endpoint, its models and an **output-token limit**:
  empty (the default) means no limit, a number caps every reply, for a gateway that bills or
  throttles by token. Reasoning models (Qwen, DeepSeek…) are asked not to think before a structured
  answer such as a form suggestion, where thinking only spends the budget; a reply cut off before
  any answer is reported as such rather than as an empty answer.
- **Beam model.** A simulator-independent, directed beam-transport network linked to the facility:
  * Structure:
    * beam systems and any number of beams (particle or photon);
    * paths of placements (open or closed; a component may be on several), joined by explicit branch,
      merge and continue connections, with `s` a coordinate, never the topology.
  * Components:
    * definitions and instances;
    * components of every family (magnets, RF, diagnostics, vacuum, interception, material, optics,
      sources, supports) described by capabilities;
    * beam boundaries of any shape from any component (limiting-aperture queries);
    * materials, semantic states, measurement models;
    * alignment and supports;
    * the simulator's own data with per-value provenance.
  * Datasets: optics, survey, fields along a path.
  * Validity: completeness levels from TOPOLOGY to INTEGRATED.
  * Sources: the canonical `argus.beam-model/2` JSON ([format](docs/beam-model-format.md); v1 still read), or
    MAD-X, TFS, Elegant, Bmad, Xsuite and Accelerator Toolbox files through converters.
  * Asset synchronization matches components to physical assets on names, aliases, conventions, type,
    beamline, position, geometry, order and neighbours. Proposals carry confidence and evidence; people
    confirm them; confirmed bindings survive later syncs
    ([docs/beam-asset-sync.md](docs/beam-asset-sync.md)).
  * See [docs/beam-model.md](docs/beam-model.md).
  * Served by `/v1/beam-systems`, `/v1/beam-paths`, `/v1/beam-elements`, `/v1/diagnostics`,
    `/v1/observables`, `/v1/model-datasets`, `/v1/beam-models/{id}/…` and `/v1/beam-model/import`.
- **Portable archives (integration-tested slice; not production-approved).** A workspace or the whole
  instance exported at one ledger watermark (a hashed vector) as signed, immutable chunks with a
  manifest and JSON Schemas. People travel under an identity profile, and every attachment and source
  content is inspected for secrets before anything is stored. Restricted classes go only encrypted, to
  approved destinations. Bulk chunks and attachments are content-addressed artifacts; a Git portability
  repository holds the signed tag, manifest and review files. Imports are verified in quarantine,
  loaded and reconciled in an isolated staging database, and promoted in one transaction with a
  verifiable origin chain; audit days already sealed never change. See
  [docs/export-import-design.md](docs/export-import-design.md); served by `/v1/portability/…`,
  `python -m app.portability` and Administration → Portability in the web app. Administrators register
  GitHub, GitLab or other Git repositories there (*Set-up*): ARGUS makes the SSH deploy key and shows only
  its public half, pins the server's host keys once confirmed, keeps tokens encrypted, tests read and
  write access, manages artifact stores, the signing key and trusted keys, and lets what was registered be
  changed. Setting up from the web app is switched off with `ARGUS_PORTABILITY_UI_CONFIG=off`, when only
  the deployment's settings apply. An export can also keep its data in the repository itself, committed
  with the archive, so an import needs nothing but the repository.
- **Type catalogue.** Every object type a workspace can use, on one page: where it sits in the
  tree, what it is, its attributes (own and inherited), the names imports know it by, what its
  references mean in the graph, and how many records it has. The seeded types, ticket types and
  document types come with default icons (Tabler, plus drawn ones for magnets, quadrupoles,
  vacuum crosses and valves); shared types get shared icons. *Assets → Type catalogue*; served by
  `/v1/catalogue/types`.
- **Mapping imported records.** Records imported as they were in Insight are mapped onto a
  workspace's types with a plan per source type, from rules and, where an AI endpoint is checked,
  the AI: target type, field mapping, fixed values, companion records (a GigE camera's Ethernet
  port with its MAC and IP) and links, made once both ends are mapped. Hardware models map onto a
  catalogue's Product Models and vendors the same way. Attachments, avatars, history, comments
  and tickets come along, and nothing is shared with other workspaces unless asked.
  *Assets → Map imported records*; served by `/v1/catalogue-mappings`.
- **Channels ↔ hardware.** Which unit a control channel drives is proposed from the naming
  convention (zone, function code, number) and the network address, and becomes an `acts on`
  link only once a person confirms it; an IOC then `drives` the hardware of its channels.
  *Assets → Channels ↔ hardware*; served by `/v1/ledger/control-bindings`.
- **Inferring the hardware chain from EPIK8s.** An EPIK8s import can, as options, make what the
  channels imply: the equipment and lattice elements they drive (rules), the controller each IOC
  talks to (IPCMini, TPG 366, Pollux…) powering them, and, in a site-wide IT workspace, the serial
  converters, servers and consoles the hostnames name with the ports the lines use. A unit the
  inventory already holds is linked by proposal instead of duplicated, and channels no rule
  recognises can be classified by the AI, as proposals in the review queue only.
- **Data integrity tools**: relink of unresolved references, and a report of missing
  references, dangling links and orphaned objects, with targeted cleanup actions.
- **IOC engineer.** Ask ARGUS and any MCP client can help build containerised EPICS IOCs with
  ibek: find the driver for a device and its git source (from `install.yml`), read an entity
  model's parameters or a template's devtypes, render a beamline IOC entry exactly as the pod does
  (jnjrender) and check it as `ibek runtime generate` will (unknown or not-compiled types, missing
  or mistyped parameters), and draft the files a new driver needs. Answered from a catalogue of
  `infn-epics-ioc` and its submodules (`python -m app.ioc_engineer build`); the `ioc_*` MCP tools,
  read-only. [docs/ioc-engineer.md](docs/ioc-engineer.md).

## Design notes

- [API versions and deprecation](docs/api-policy.md) — what stays stable, how endpoints retire.
- [Operating ARGUS](docs/operations.md) — scheduled jobs, backups and point-in-time recovery,
  export and load, performance targets.
- [The asset model revision](docs/asset-model-revision.md) — positions and installations, the fact
  ledger, the relation registry, identity reconciliation, and ARGUS as the system of record that
  replaces Jira/Insight domain by domain. The implementation follows its plan (§13); the unified
  hub and the P0 import fixes are the first increment; the S1 vertical slice (fact ledger,
  authority policy, installations, review queue, Access Points, port mapping, ticket
  attribution, rule versions; acceptance tests A1–A32) is the second; the transition and
  readiness gates (A33–A41: cutover, identity, restrictions, lookup, reconciliation) the third.
- [Object schema design for a large-scale accelerator](docs/asset-schema-design.md) — the
  type catalogue (146 types over four planes), the relation vocabulary, composite elements such
  as a screen station, and how a beamline's EPIK8s control configuration and a EuPRAXIA-style
  product breakdown both come in as equipment rather than as files.
- [The beam model](docs/beam-model.md) — physics positions, topology, diagnostics, observables and model
  datasets, linked to equipment, controls and documentation without becoming a simulator or a telemetry store.
- [Export, import and the Git portability project](docs/export-import-design.md) — the escape
  hatch: signed `argus-archive/1` checkpoints at a ledger watermark, selective packages with an
  explicit dependency closure, a Git repository of immutable chunks and signed tags, quarantined
  verification, staged idempotent import, and reconciliation; with the status of each part.
- [The beam model format](docs/beam-model-format.md) — `argus.beam-model/2` (`*.beam.json`): the object model,
  topology, component and capability vocabularies, boundaries, materials, states, diagnostics, alignment,
  datasets, bindings, validation levels, the converters (MAD-X, TFS, Elegant, Bmad, Xsuite, AT), v1 compatibility.
- [Beamline asset synchronization](docs/beam-asset-sync.md) — matching model components to physical assets:
  evidence, confidence, statuses, incremental sync, the API and the review view.
- [The knowledge graph for root-cause analysis](docs/knowledge-graph-design.md) — what each
  relation means for a failure (which way it travels, and whether the dependent loses its readout,
  its function, a permit or part of itself), impact and root-cause analysis over it
  (`GET /v1/graph/impact`, `POST /v1/graph/root-cause`, `GET /v1/graph/blast-radius`, and the
  `impact_analysis`, `root_cause_analysis` and `single_points_of_failure` MCP tools), what the
  configurations give, and what the graph cannot yet do.
- [The element panorama](docs/element-panorama.md) and [the IT model](docs/it-model-design.md) —
  what the utility matrices say next to the control configurations, and where switches, hosts and
  serial converters live.
- [A local Keycloak for testing multi-workspace users](docs/oidc-dev-setup.md) — how one person
  ends up with different rights in different workspaces (`RoleBinding`, not a PAT, which can only
  ever be one workspace), the dev-only identity provider that proves it end to end, six test users
  covering the permission model, and what's simulated about a future GODiVA-backed sign-in versus
  what isn't.

## Development

### Everything at once, with Docker Compose

The quickest way to a working hub on your own machine: database, API, web UI and a local
Keycloak, with migrations applied on start. **Nothing else to run**: the web UI is built and
served by the `web` container, so there is no `npm install` or `npm run dev` in this setup.

| Service    | Address                   | What it is                                              |
|------------|---------------------------|---------------------------------------------------------|
| `web`      | <http://localhost:5173>   | The web UI, a production build with *INFN login* enabled. |
| `api`      | <http://localhost:8080>   | The REST API (plain `http`, no TLS).                    |
| `keycloak` | <http://localhost:8081>   | Dev identity provider, realm `argus-dev` (console: `admin` / `admin`). |
| `db`       | internal only             | PostgreSQL 16.                                          |

```bash
docker compose up -d --build --wait
tools/argus-admin dev-setup        # test workspaces and the six test users, with their roles
```

Run `dev-setup` before anyone signs in. A test user who signs in first gets a plain account:
`admin.test` then isn't an admin, and sees *"You don't have access to any workspace yet"*.
Running `dev-setup` again fixes it, and it's safe to repeat. To throw everything away and begin
again, see [Starting over with no data](#starting-over-with-no-data).

Open <http://localhost:5173> and sign in one of two ways:

- **INFN login** with a test user from the local Keycloak. The admin is `admin.test`; the others
  are `owner.test`, `contributor.test`, `viewer.test`, `curator.test` and `outsider.test`. Every
  password is `argus-dev`. What each one can do is in
  [docs/oidc-dev-setup.md](docs/oidc-dev-setup.md) §4.
- **An API token**: `tools/argus-admin workspace token sparc` prints one **once**. Give it with
  the API address `http://localhost:8080`.

#### Workspaces, people and roles: `tools/argus-admin`

One command for the usual administration, run from the repository root against the running
stack. Every command is safe to repeat, and a mistake says how to fix it.

```bash
tools/argus-admin workspace list
tools/argus-admin workspace create lnf-euaps --name "EuAPS"      # with the defaults the web UI gives one
tools/argus-admin workspace token lnf-euaps                        # API token for scripts
tools/argus-admin user add mario.rossi@lnf.infn.it --name "Mario Rossi" --password s3cret
tools/argus-admin user admin mario.rossi@lnf.infn.it on
tools/argus-admin role list                                        # viewer, reporter, agent, … owner
tools/argus-admin grant mario.rossi@lnf.infn.it contributor lnf-euaps
tools/argus-admin revoke mario.rossi@lnf.infn.it contributor lnf-euaps
tools/argus-admin access mario.rossi@lnf.infn.it                   # what they hold, and where
tools/argus-admin user list
```

A person is known by email, and can be added before they ever sign in: their first sign-in with
that email lands on the same account, roles included. `--password` also creates their login in
the local Keycloak, for development only. With INFN's own identity provider, people already have
a login there, so leave it out. `workspace create` on an existing workspace adds any defaults it
is missing, such as those skipped by the older `create_token.py`.

#### Starting over with no data

```bash
docker compose down -v                     # removes the containers and the volumes: database and attachments
docker compose up -d --build --wait        # a fresh, empty hub, with migrations applied
tools/argus-admin dev-setup                # the five test workspaces and the six test users
docker compose exec api python scripts/seed_asset_types.py all sparc   # optional: the object types
```

Then sign in with *INFN login* as `admin.test` / `argus-dev`.

- **This cannot be undone.** Every record, ticket, document, attachment, API token and account in
  the hub is deleted. Export anything you want to keep first (see
  [docs/operations.md](docs/operations.md)).
- **Keep `--build`.** The containers are recreated from their images, so the images must hold
  the current code, including the script behind `tools/argus-admin`.
- **Run `dev-setup` before anyone signs in.** Otherwise the first sign-in makes a plain account
  with no workspaces. Running `dev-setup` again repairs it.
- **Keycloak starts fresh as well.** It keeps nothing in a volume: each new container re-imports
  `keycloak/realm-argus-dev.json`, with the six test users and nothing else. Logins added with
  `tools/argus-admin user add --password` are gone; add them again.
- **Workspaces start empty.** `dev-setup` creates `sparc`, `euaps`, `eli`, `btf` and
  `accelerator-infn` with their defaults, but no object types. The last command above loads them
  into `sparc`; the notes below cover several beamlines sharing one catalogue.

A few notes:

- `TOKEN_PEPPER=dev-only` is a secret mixed into token hashes, **not** a token. Use the one the
  script prints.
- After changing web app code, rebuild the image: `docker compose up -d --build web`.
- Don't also run `npm run dev` from `webapp/`: it binds `localhost:5173` too, and the browser
  gets the dev server instead of the container. That dev server has no *INFN login* button unless
  `webapp/.env.development` exists (see [Running the pieces by hand](#running-the-pieces-by-hand)).
- Something else already on 8080 or 5173? Move the published ports:
  `API_PORT=18080 WEB_PORT=15173 docker compose up -d --build --wait`. INFN login then stops
  working, because the Keycloak client only accepts redirects to `http://localhost:5173`. Use a
  token, or add the new address to `redirectUris` and `webOrigins` in
  `keycloak/realm-argus-dev.json` and recreate the `keycloak` container.
- Load the accelerator object types. In a hub with one workspace, `all` puts everything in it:
  `docker compose exec api python scripts/seed_asset_types.py all sparc`.
  With several beamlines, the shared types go in one catalogue workspace, once, and each
  beamline gets only its own, hanging from them:
  `... seed_asset_types.py global catalogue`, then
  `... seed_asset_types.py beamline sparc --catalogue catalogue`.
  Each workspace has to exist first (`tools/argus-admin workspace create <id>` creates it), and
  `--dry-run` shows what would happen without writing.
- Read a beamline's control configuration into a workspace, as objects of those types:
  `docker compose cp ../epik8-sparc/deploy/values.yaml api:/tmp/sparc.yaml`, then
  `docker compose exec api python scripts/import_epik8s.py sparc /tmp/sparc.yaml`
  (`--dry-run` reads it in full and keeps nothing). Add `--infer-elements` to also make what the
  channels drive, which the file never lists: the ion pumps, magnets and their supplies, cameras,
  BPM electronics, LLRF and modulator units, motor axes, screens (a flag and the camera its name
  pairs it with, or, as at ELI, the camera and motor axis named after their station: `SCN01:CAM01`
  and `SCN01:MOT01` make Screen Station `SCN01`) and mirrors. They are inferences, marked `inferred`, and a person's later edits
  survive a re-read. The catalogue gained a `Mirror` type for this: run
  `scripts/seed_asset_types.py beamline <workspace> --catalogue <catalogue>` again on a workspace
  seeded before.
  Each Access Point also says what kind of endpoint it is, and each device on a port of a serial
  converter is on a Serial Line. Add `--it-workspace it-infrastructure` (a workspace made with
  `tools/argus-admin workspace create`) to make the converters, servers and consoles the hostnames name, once, in that
  site-wide workspace, flagged global; each beamline's Access Point is `implemented by` them,
  and each port of a converter a line uses is an Equipment Port there (TCP 4003 → P3). With
  `--infer-elements`, `--infer-controllers` also makes the controller each IOC talks to (a Vacuum
  or Motion Controller that `powers` what its channels drive), and `--link-inventory` links a
  channel to the unit the inventory already holds, by tag or address, as a proposal under
  *Channels ↔ hardware*, instead of inferring a twin. The web import (*Imports → New → EPIK8s*)
  has the same options, plus asking the workspace's AI about channels no rule recognises; its
  answers are proposals in the review queue, kept per configuration file. The web import seeds the
  catalogue's types first, as the script does: a workspace nobody seeded hangs from the only global
  catalogue (it asks which when there are several), and a catalogue seeded before a newer shared
  type is brought up to date. A values file that names no `beamline:`, an overlay such as
  `values-linac.yaml`, takes the beamline and its templates' defaults from the `values.yaml` beside
  it and imports only its own IOCs, under its own Control Configuration.
- State lives in two named volumes and survives `docker compose down`;
  `docker compose down -v` wipes it (see [Starting over with no data](#starting-over-with-no-data)).

The defaults in `docker-compose.yml` are public and meant for one machine. Never reuse them
anywhere that holds real data.

### Running the pieces by hand

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/app
export TOKEN_PEPPER=dev-only
alembic upgrade head
python scripts/create_token.py dev "Local development" local   # prints an API token once
uvicorn app.main:app --reload --port 8080
```

This needs a reachable PostgreSQL at `DATABASE_URL`; `GET /health` answers 500 when it is not.
Run `create_token.py` from `backend/` and under the same `TOKEN_PEPPER` the server uses, or
the token it prints will not be accepted.

The tests use the same environment plus `IMPORT_SECRETS_KEY` (any Fernet key): `pytest tests`.
They never write to the database at `DATABASE_URL`: `tests/conftest.py` points them at a sibling
one (`app` → `app_test`, or `TEST_DATABASE_URL` when set), creating and migrating it on first
use, so the workspaces and shared types they make never show up in the hub. In Docker:
`docker compose cp backend/requirements-dev.txt api:/app/`, then
`docker compose exec api sh -c "pip install -r requirements-dev.txt && pytest tests"`.
Two drawing tests also need the `dwg2dxf` converter on `PATH`.

Web app, with hot reload. Stop the compose `web` service first
(`docker compose stop web`), since both use port 5173:

```bash
cd webapp
npm install
npm run dev
```

The sign-in screen offers an API token or a Google sign-in. For the *INFN login* button against
the compose Keycloak, create an untracked `webapp/.env.development` and restart `npm run dev`:

```
VITE_OIDC_AUTHORITY=http://localhost:8081/realms/argus-dev
VITE_OIDC_CLIENT_ID=argus-webapp
VITE_OIDC_LABEL=INFN login
VITE_API_BASE_URL=http://localhost:8080
```

### Environment variables (backend)

| Variable              | Purpose                                                        |
|-----------------------|----------------------------------------------------------------|
| `DATABASE_URL`        | PostgreSQL connection string.                                   |
| `TOKEN_PEPPER`        | Pepper for hashing API tokens (required).                       |
| `IMPORT_SECRETS_KEY`  | Key used to encrypt stored import credentials at rest.          |
| `ATTACHMENTS_DIR`     | Where uploaded files are stored (defaults to `/data/attachments`). |
| `OIDC_ISSUER` / `OIDC_JWKS_URI` / `OIDC_AUDIENCE` | OIDC token verification.            |
| `OIDC_EXTRA_PROVIDERS` | More trusted OIDC providers, as a JSON list of `{issuer, jwks_uri, audience}` (e.g. Firebase beside INFN's IdP). |
| (worker) | `python -m app.ledger derive-worker` runs queued derives when `LEDGER_USER_EDIT_DERIVE=manual`; `python -m app.ledger backfill-checksums` records SHA-256 for older attachments. |
| `LEDGER_USER_EDIT_DERIVE` | How derived links follow a user's edit: `background` (default), `inline`, or `manual` (left for a worker). |
| `ARGUS_IOC_CATALOG` | An IOC catalogue (`.json` or `.json.gz`) to answer the `ioc_*` tools from instead of the bundled snapshot (docs/ioc-engineer.md). |

## Deployment

See [`k8s/README.md`](k8s/README.md). Production is the Helm chart in `charts/argus-knowledge-hub`,
deployed by Argo CD: Postgres with pgvector, the API, the web app and a temporary Keycloak, as
docker-compose runs them. A version tag is a release: `git tag v1.34.0 && git push origin v1.34.0`
runs the tests, pushes both images and sets the version in the chart's `values-production.yaml`,
which Argo CD rolls out (`.github/workflows/release.yml`, `k8s/argocd/application.yaml`). By hand, the
images are still built with `backend/deploy.sh <version>` and `webapp/deploy.sh <version>`.

## License

ARGUS Knowledge Hub (the API, the web application and the ARGUS Field mobile application) is
licensed under the [European Union Public Licence v. 1.2](LICENSE) (EUPL-1.2).

Author: Andrea Michelotti — [andrea.michelotti@infn.it](mailto:andrea.michelotti@infn.it)
