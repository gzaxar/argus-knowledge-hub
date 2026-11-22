# ARGUS field application (Flutter)

*A mobile client for the work done next to the equipment. It is built on the same API, permissions,
ledger, policies and registry as the web application, and it does not replace the web application.*

Status:
- **M0** server foundations: built, except the push relay.
- **M1**, the read-only client: built.
- **M2**, capture and tickets: built, except push.
- **M3**, replacement and review: built.
- **M4**, offline: built.

See §15. The client is in `mobile/`.
[`asset-model-revision.md`](asset-model-revision.md) §24 is normative. It
states the rules this client must keep: trust boundaries, pending commands, conflict handling,
invariants I-MOB-1…8 and acceptance tests A57–A72. Where this document and §24 disagree, §24
wins. This document is the product and engineering design for the client.

---

## 0. The decision

ARGUS gets a **Flutter field application** for Android and iOS. It is an API-driven client for
these workflows near equipment:

- asset capture, lookup and inspections;
- guided maintenance and equipment swaps;
- AI-assisted intake;
- ticket handling.

**Web-first.** Governance, bulk operations, document control, advanced reconciliation and graph
administration stay in the **web application**.

**Not a replacement.** The web frontend is not replaced in the first phase, and the two clients
are not held to feature parity. Each is designed for where it is used:
- the field client is used standing at a rack, with gloves and a patchy network;
- the web application is used at a desk, with a large screen and a keyboard.

**Principles that do not change:**

- ARGUS is the system of record for assets, documents, tickets, Positions, Installations and
  their relationships. Jira and Insight are migration sources and temporary archives.
- Both clients use one API. That covers:
  - permissions;
  - the fact ledger and its decisions;
  - authority policies and the relation registry;
  - the projections.
- The field client never connects to the database and never writes a projection table.
- AI-generated facts are reviewable proposals (revision §23).
- **Offline work is a pending command, not a fact.** Nothing done offline is true in ARGUS until
  the server has accepted it through the ordinary ledger path.

---

## 1. Who does what: field client and web application

| Workflow | Field client | Web application | Note |
|---|---|---|---|
| Sign in (OIDC) and choose a workspace | ● | ● | same identity provider and roles |
| Scan a QR code or barcode | ● | ○ (existing `LabelScanner`, webcam) | the camera is the field client's main input |
| Search by key, inventory number, serial, hostname, Position, ticket | ● (focused) | ● (full search, facets) | both use `/v1/lookup` and search |
| Photograph and register Equipment | ● | ● | guided entry and AI Intake on both |
| AI extraction from nameplates and labels | ● | ● | server-side (revision §23). The phone only captures and pre-checks |
| View Equipment, Position, Product Model, Location, current Installation | ● | ● | field view: compact, what matters at the rack |
| Inspections and checklists | ● | ○ (review of results) | checklists are documents with steps |
| Propose or confirm an Installation | ● | ● | confirmation needs the owner's rights (revision §4.1) |
| Guided equipment replacement | ● | ○ | §8 |
| Record location or condition change | ● | ● | |
| Create an incident ticket with photos and occurrence time | ● | ● | |
| Update assigned tickets, comment, allowed transitions | ● | ● | the server workflow decides the transitions |
| View approved procedures and controlled documents | ● | ● | offline copies only when explicitly authorized |
| Notifications: assignments, reviews, sync conflicts | ● (push) | ● (in-app, e-mail) | content-free push (§11) |
| Review assigned proposals and conflicts | ● (assigned, one at a time) | ● (all queues) | |
| Offline drafts | ● | — | §5 |
| Deep links to assets, documents, tickets, reviews | ● | ● | §7 |
| Bulk imports and migration control | — | ● | |
| Catalogue and schema administration | — | ● | |
| Authority policy and relation registry | — | ● | |
| Identity reconciliation, large duplicate queues | — | ● | a single assigned duplicate may be dismissed on mobile |
| Document authoring, comparison, approval, retention | — | ● | the field client may attach photos or notes as proposed inputs |
| Bulk ticket operations, large tables, dashboards, reports | — | ● | |
| Ask questions of the records, typed or spoken | ● (voice in and out, hands-free) | ● (Ask ARGUS, proposed changes) | the same conversations; changes are applied on the web |
| Advanced knowledge-graph exploration | — | ● | the field client shows a short impact summary (`knowledge-graph-design.md` §3.2) |
| Workspaces, roles, groups, access reviews | — | ● | |
| AI model and prompt governance | — | ● | revision §23.12 |
| Migration reconciliation reports | — | ● | |

● primary · ○ secondary · — not offered

---

## 2. Architecture

### 2.1 One backend, two clients

```text
 ┌──────────────────────┐       ┌──────────────────────┐
 │ Web application      │       │ Flutter field client │
 │ React · TypeScript   │       │ Android · iOS        │
 │ generated TS client  │       │ generated Dart client│
 └──────────┬───────────┘       └──────────┬───────────┘
            │   HTTPS, OIDC bearer tokens,  │   + Idempotency-Key, If-Match,
            │   X-Workspace-Id              │     X-ARGUS-Client, pending-command replay
            └──────────────┬────────────────┘
                           ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ ARGUS API  (/v1, versioned OpenAPI contract, docs/api-policy.md)        │
 │  ├── authentication (OIDC) and authorization (roles, restricted grants) │
 │  ├── commands: validation, idempotency, version preconditions           │
 │  ├── fact ledger and decisions (claims, confirm, supersede, reject)     │
 │  ├── authority policy · relation registry · identity resolution         │
 │  ├── current-state projection · derive · reconcile                      │
 │  ├── AI Intake (revision §23): guide, assist, proposals, profiles       │
 │  ├── media: attachment upload, hashing, scanning                        │
 │  └── notifications (in-app, e-mail, push relay) and sync status         │
 └───────────────────────────────┬─────────────────────────────────────────┘
                                 ▼
                     PostgreSQL (ledger, projections)
                  — never reachable from either client —
```

### 2.2 Trust boundaries

| Boundary | What crosses | What must hold |
|---|---|---|
| person → device | taps, photos, scans, typed text | QR payloads, labels, photos and typed text are **untrusted input** (revision §23.10) |
| device storage | the cache, pending commands, attachments, tokens | encrypted at rest. Tokens are in the platform keystore (Keychain, Android Keystore). Everything is wiped on logout, revocation or expiry (§6) |
| device → API | HTTPS requests with a bearer token | TLS with the institution's trust configuration. The server checks the token, the workspace and the permission on **every** call. The client is never trusted to have checked |
| API → ledger | commands become claims and decisions | the same code path as the web: policies, registry, invariants, projection (revision §7) |
| API → model provider | AI Intake only, from the server | the device holds no provider key and no protected prompt (revision §23.10) |
| API → push provider | a content-free notification | no record names, values or restricted details (§11) |

**The field client holds no rules.**
- **Only on the server:** authority, relation, identity and port-safety rules are not in the client
  code. They exist once, on the server.
- **In the client, for usability only:** a required field, a date format, a photo that is too dark.
  None of this decides validity.

---

## 3. The API contract

### 3.1 What exists and what the field client needs

| Need | Exists today | Change required |
|---|---|---|
| Versioned API, additive changes, deprecation headers | yes: `/v1`, `X-ARGUS-API-Version`, `Deprecation`/`Sunset`, 410 after sunset (`docs/api-policy.md`) | none |
| OpenAPI contract | **built:** `backend/openapi/openapi.json` and the field subset `field-client.json`, committed; a test fails when they drift from the API | publish it per release |
| Generated clients | **built for Dart** (`mobile/packages/argus_api`, OpenAPI Generator `dart`); the web client is still hand-written | the TypeScript client; the web client migrates to it feature by feature |
| Identifier lookup | yes: `GET /v1/lookup/{identifier}`, `POST /v1/lookup/batch`, following merges, restriction-aware | **built:** the universal-link resolver `GET /v1/links/resolve` for the paths in §7, with label values (serial, inventory number, MAC) and `ambiguous` candidates |
| Idempotency | **built:** `Idempotency-Key` on any mutating call (§3.2) | none |
| Version preconditions | **built:** assets (latest ledger event), tickets (`version` with per-field versions) and documents (revision and state) return an `ETag`; asset edits, ticket edits and transitions take `If-Match` (§3.3) | — |
| One error shape | **built:** every error keeps `detail` and adds a top-level `problem` (§3.4) | none |
| Atomic replacement | **built:** `POST /v1/installations/replace` with a dry run, and the lower-level `swap`. It checks the outgoing unit, the incoming identity, I-INS-1, compatibility and duplicates, and reports the consequences (§8). It applies in one batch, or becomes a `replacement_proposal` for an approver | the push relay for the approver (U21) |
| AI Intake | yes: `/v1/intake/guide`, `/assist`, `/assist/{kind}/file`, `/propose/asset/{uid}`, `/proposals/{claim_id}` | none beyond idempotency. Mobile uploads use the same endpoints |
| Media upload | **built:** resumable `/v1/uploads`, with a client SHA-256 verified by the server, limits per type, EXIF GPS removal, and attachment to a ticket or asset (§5.5) | the U23 values |
| Notifications | in-app rows and e-mail (`app.services.notify`) | device registration and a **push relay** that sends content-free notifications (§11) |
| Minimum client version | **built:** `X-ARGUS-Client: flutter/<version>/<platform>`; **426** `client_too_old` with the minimum (`ARGUS_MIN_FLUTTER_VERSION`) | none |
| Session revocation | **built:** the device registry (`/v1/devices`: register, list, revoke); a revoked `X-ARGUS-Device` answers 401 `revoked` and the app wipes | invalidating the refresh token at the identity provider |

### 3.2 Idempotency

- **Keys:** every mutating request carries `Idempotency-Key: <uuid v7>`. The key is generated
  once, when the command is created, and reused on every retry.
- **Storage:** the server keeps `(workspace, principal, key) → (request hash, status, response)`
  for at least the offline-retention period (§5.6), plus 7 days.
- **Replays:** a replay with the same key and the same request hash returns the stored response
  and writes nothing. The same key with a different request is refused with **422
  `idempotency_mismatch`**.
- **Coverage:** keys apply to ledger batches, ticket and comment creation, uploads and AI Intake
  outcome recording. A retry after a lost response therefore never creates a second ticket, a
  second Installation or a second decision (I-MOB-2).

### 3.3 Record versions and preconditions

- **Version:** every record read by the field client comes with its **version**:
  - for a ledger-projected record (Equipment, Position, Installation), the highest ledger
    sequence number that touched it;
  - for a ticket, its `version` column;
  - for a document, its current revision uid and state.
- **Precondition:** a command carries the version the person saw. The server compares it with
  the current version:
  - **equal:** the command is applied, subject to the ordinary validation;
  - **different, and the change does not touch what the command changes:** it is applied. An
    example is a new comment on the ticket whose state the command changes. The rule is declared
    per command kind (§5.4);
  - **different, and it does:** **409 `stale`**, with the current state. For the protected kinds
    of §5.4 this becomes a reviewable conflict, never an overwrite.

### 3.4 One error shape

```json
{
  "error": "a person-readable sentence",
  "code": "stale | forbidden | invalid | invariant | conflict | not_found | too_large | client_too_old | idempotency_mismatch",
  "invariant": "I-INS-1",
  "field": "attributes.serial",
  "current": { "version": "...", "value": "..." },
  "review_item": "uid of the review item opened, when the server turned the command into one"
}
```

Both generated clients map these codes to typed errors. The field client decides from `code`
whether to retry, show the conflict or drop the command. It never parses the English text.

---

## 4. The Flutter application

### 4.1 Layers

```text
 Views (widgets)                     what the person sees; no logic beyond layout
   ↓
 View models                         screen state, input handling, loading and error states
   ↓
 Domain use cases                    "register equipment", "replace unit", "report incident"…
   ↓
 Repositories                        one per aggregate: assets, positions, installations,
   ├── local data source              tickets, documents, reviews, commands, media
   │     encrypted database, encrypted media cache, secure token store
   └── remote data source
         generated Dart client of the ARGUS OpenAPI contract
```

**Three kinds of model, kept apart:**

- **transfer objects**, generated from the OpenAPI contract and changing only with it;
- **domain models**, which are what the use cases and view models see;
- **persistence records**, the rows of the local database, with their own migrations.

Mappers convert between them at the repository boundary. An API change therefore does not
ripple into screens, and a change to the local schema does not ripple into the API.

### 4.2 Feature modules

| Module | Contents |
|---|---|
| `auth` | OIDC with PKCE, token refresh, logout and wipe, revocation handling |
| `context` | workspace selection, role and grant context, environment (development, staging, production) |
| `search_scan` | camera scanner (QR, Code 128, DataMatrix), search, lookup of external keys |
| `records` | Equipment, Position, Product Model and Location views, current Installation, history summary |
| `capture` | photos, on-device checks, AI Intake flows (revision §23.5, §23.11; §4.4 below) |
| `installations` | proposing and confirming an Installation, guided replacement (§8), port confirmation |
| `tickets` | incident reporting, assigned tickets, comments, transitions, similar tickets |
| `documents` | reading procedures and checklists, offline copies, freshness warnings |
| `review` | assigned proposals and conflicts, one item at a time, with evidence |
| `notifications` | push registration, the in-app inbox, routing into deep links |
| `ask` | questions answered from the records (`/v1/ai/chat`, streamed), earlier conversations, speech in and out |
| `sync` | the pending-command queue, upload of attachments, conflict presentation |
| `settings_diagnostics` | settings, cache state, diagnostics screen and export (§13) |

### 4.3 Technical choices

M1 confirmed the first six rows; the others are still candidates.

| Concern | Choice or candidate | Why |
|---|---|---|
| State and dependencies | Riverpod 3 (chosen), go_router for navigation | testable view models, no global singletons |
| API client | OpenAPI Generator `dart` (chosen; `dart-dio` would need build_runner) | generated from the committed contract |
| Local database | Drift on SQLite with SQLCipher | typed queries and migrations, encrypted at rest |
| Secure storage | `flutter_secure_storage` (Keychain, Keystore) | tokens and the database key |
| OIDC | `flutter_appauth` (AppAuth) | Authorization Code with PKCE, system browser, no embedded web view |
| Scanning | `mobile_scanner` | on-device QR and barcode decoding |
| On-device OCR (optional) | ML Kit text recognition, on-device model | a quick reading for the quality check. It is never the authoritative extraction |
| Background sync | WorkManager (Android), BGTaskScheduler (iOS) | platform-scheduled retries |
| Push | FCM / APNs through a server relay, or the MDM's channel | stakeholder decision U21 |
| Speech (chosen) | `speech_to_text` and `flutter_tts`: the platform's recogniser and voice | no audio leaves the app, only the words recognised. Server-side speech (the AI settings' speech models) is the option for one voice across devices |

Each package's licence, maintenance and data behaviour is reviewed before adoption. A package
that sends data to a third party (analytics, cloud OCR) is excluded.

---

## 5. Offline work and synchronization

### 5.1 What is cached

Only what the person needs, for as long as the retention allows (§5.6):

- **assigned and recent records:**
  - the Equipment and Positions the person is assigned to, and those they opened recently;
  - their current Installations;
- **assigned work:**
  - the person's assigned tickets;
  - their review items;
- **documents:** controlled documents explicitly marked for offline use, and only their approved
  revision;
- **the person's own work:** their drafts, pending commands and attachments.

**Never cached:**
- search indexes of the whole workspace;
- restricted records the person may not read;
- restricted fields;
- other people's drafts;
- the AI model's context.

Restricted content the person *may* read is cached only if the restricted class allows offline
copies (U22).

### 5.2 Drafts and pending commands

A **draft** is unfinished work that lives only on the device. A **pending command** is a finished
request waiting for the server. Every offline mutation becomes a pending command. It is stored
encrypted and holds:

| Field | Meaning |
|---|---|
| `idempotency_key` | uuid v7, created once, used on every retry (§3.2) |
| `user`, `device_id` | who asked, from which registered device |
| `workspace` | where it applies |
| `kind` | e.g. `ticket.create`, `ticket.comment`, `ticket.transition`, `asset.propose`, `asset.update_location`, `asset.update_condition`, `installation.propose`, `installation.confirm`, `replacement.submit`, `inspection.submit`, `review.decide`, `intake.outcome` |
| `target` | the record uid, or a client-generated uid for a record created offline |
| `seen_version` | the version the person saw (§3.3) |
| `payload` | the request, as the API expects it |
| `attachments` | local ids, SHA-256 hashes, sizes, MIME types |
| `depends_on` | commands that must succeed first, such as a comment that needs its ticket |
| `created_at` | device time, and the device's offset from the last known server time |
| `status` | `draft` → `queued` → `uploading` → `sent` → `accepted` / `rejected` / `conflict` / `expired` |
| `attempts`, `last_error` | retry count and the last problem shape (§3.4) |

A pending command is shown as **pending** everywhere it appears. A ticket created offline is
labelled "not yet in ARGUS", and so is a replacement recorded offline. No other person sees it
until the server accepts it.

### 5.3 The synchronization algorithm

For each command, in dependency order and then in creation order:

1. **Authenticate.** Refresh the token. If the session is revoked or expired beyond refresh, stop
   and ask the person to sign in. The queue stays.
2. **Authorize.** The server checks the current permission for the command's workspace and
   target. A permission lost while offline turns the command into `rejected` with
   `code: forbidden`. The draft is kept for the person to copy or discard.
3. **Upload attachments.** Upload resumably with their hashes. The server verifies each hash and
   size and returns attachment ids. A mismatch fails that attachment only, and it is retried.
4. **Check the version.** The command carries `seen_version`, and the server applies §3.3 and §5.4.
5. **Apply through the ledger.** The server applies the command in the same code path as a web
   request: policies, registry, invariants and projection.
6. **Answer** with one of:
   - `accepted`, with the new record state;
   - `rejected`, with the problem shape;
   - `conflict`, with a review item the server opened for the owner.
7. **Retry safely.** A lost answer is retried with the same idempotency key, so the server
   returns the stored answer and writes nothing again (I-MOB-2). Retries use exponential backoff
   with jitter, and stop at a set number of attempts after which the person is asked to act.
8. **Keep the draft until confirmed.** The local draft and its attachments are deleted only after
   `accepted`, or when the person discards a `rejected` or `conflict` command.

### 5.4 Conflicts: never last-write-wins for what matters

| Command kind | On a changed version |
|---|---|
| comment, photo added to a ticket | applied: additive |
| location or condition change on Equipment (non-protected) | applied if the same field did not change since `seen_version`; else **conflict** shown to the person with both values |
| ticket fields (description, severity proposal) | applied if the same field did not change; else conflict |
| **Installation proposal or confirmation, equipment replacement** | **reviewable conflict**, never applied over a change |
| **identity merge, retirement** | never offered offline |
| **Position or Access Point assignment** | **reviewable conflict** |
| **safety, interlock or protected predicates** (`serial`, `inventory_number`, `ip`, `mac`, `fqdn`, `acts on`, `safety_class`) | **reviewable conflict**. Confirmation by the protected-predicate owner (revision §7.7, D14) |
| **critical port maps** | **reviewable conflict**, and swap-time confirmation rules (revision §9.3) |
| **controlled-document approval** | never offered on mobile (web-first) |
| **ticket closure, confirmed root cause** | never applied offline. A closure recorded offline arrives as a **proposed** transition that needs the person to confirm it online |

**Offline replacements.** An offline replacement or Installation always arrives as a
*proposal*. The server confirms it only when all of these hold:
- the Position's current Installation is still the one the person saw;
- the person holds the owner's rights;
- no protected port needs confirmation.

Otherwise the server opens a review item with the evidence the person captured.

### 5.5 Attachments

- **Hashing:** photos, video and files are hashed (SHA-256) on the device, stored encrypted and
  uploaded resumably.
- **Server checks:** the server recomputes the hash, enforces size and type limits (U23), and
  strips location metadata from images unless the workflow asks for it (EXIF GPS is removed by
  default).
- **Limits:** media over the limit is refused before upload, with the limit named.

### 5.6 Retention and expiry

- **Cached records:** kept for **N days** after the last successful sync (U22, proposed 7). After
  that they are hidden and then deleted.
- **Pending commands:** older than the retention become `expired`. The person is told and can
  resubmit the work, which re-checks every version.
- **Wipe:** logout, revocation, a changed user or an MDM wipe deletes the cache, drafts, pending
  commands, media and tokens. Pending work is not silently lost: before a voluntary logout, the
  person is shown what would be lost.

---

## 6. Authentication and security

- **OIDC:** Authorization Code with **PKCE**, through the system browser (AppAuth). There is no
  embedded web view and no password in the app. The issuer is the one the web uses (revision
  §19 item 1; `docs/oidc-dev-setup.md`).
  - Google accounts come through the same issuer: Keycloak brokers Google (`keycloak.google` in the
    chart), so the app and the API see only Keycloak tokens.
  - Signing in with Google directly (`OIDC_ISSUER=https://accounts.google.com`) is supported for
    an installation without Keycloak: the app then sends Google's ID token, which the API trusts
    as an extra provider (`docs/operations.md`).
  - On Android, `MainActivity` has no `taskAffinity=""` (the Flutter template's default): with it,
    the redirect arrives in another task and AppAuth drops it ("No stored state").
- **Tokens:**
  - access tokens are short-lived (proposed 10 minutes) and refresh tokens are rotated;
  - both are stored only in the platform keystore;
  - the database key is also in the keystore, bound to the device, and optionally to biometrics
    under MDM policy.
- **Servers:** the build's default (`ARGUS_API_BASE`) can be replaced by another server in Settings or on the
  sign-in screen; a production build accepts only HTTPS servers in `ARGUS_API_DOMAIN` (by default the
  default server's domain), since the sign-in token is sent there.
  - The session records its server (`apiBase`); saved copies are keyed by server, workspace and person.
  - A sign-in tries the chosen server, the last that answered, then the default; only silence moves on — a
    refusal ends the attempt.
  - If none answers and the phone remembers the last workspace (`argus.backend.*`, addresses only, kept
    across sign-outs), the person may continue offline: the session is unconfirmed until whoami and the
    device registration succeed on the first answer.
  - A token renewal that gets no answer from the identity provider keeps the session; only a refusal
    (`invalid_grant`…) signs out. A 401 while the renewal is unreachable asks for a sign-in in place,
    keeping the person's data, rather than wiping.
- **Revocation:** each device registers (`/v1/devices`) with its public installation id.
  - Revoking a device, or a person's sessions, invalidates the refresh token.
  - The device learns of it on the next call (401 `revoked`) and wipes.
  - An MDM wipe also removes the app's data.
- **Least data:** only what §5.1 allows is cached, and record- and field-level restrictions are
  applied by the server before anything reaches the device (I-ACL-1). A restricted field the
  person may not read never enters the cache.
- **Nothing sensitive leaves the device:** no restricted data in notifications (§11), and no
  secrets, tokens, record values or free text in logs, analytics or crash reports. Crash reports
  are scrubbed on the device before sending.
- **Endpoints and certificates:** the environment (development, staging, production) and its API
  base URL are set by build flavour or MDM managed configuration, never typed by the user. The
  environments use separate OIDC clients and separate stores. The institution's internal CA is
  trusted through the platform or MDM trust store. Certificate pinning is optional (U24),
  because it complicates CA rotation.
- **Managed devices:** the app honours MDM configuration. That covers:
  - the environment;
  - the minimum OS version;
  - disabling screenshots of restricted screens;
  - disabling offline copies;
  - the offline-retention period.
- **Untrusted input:** QR payloads, barcodes, scanned labels, photos, documents and ticket
  comments are data.
  - A QR payload is resolved through `/v1/lookup` and never opened as an arbitrary URL.
  - Only ARGUS link patterns (§7) are followed.
  - Nothing scanned can grant permissions, change prompts, invoke tools or bypass validation
    (revision §23.10).
- **Permissions apply to all reads the client triggers:** search, AI Intake, retrieval,
  document previews and graph summaries run under the requesting person's permissions on the
  server, which are the same checks as the web (A48–A51).

---

## 7. Deep links and QR identifiers

### 7.1 Stable universal links

| Path | Opens |
|---|---|
| `/asset/<uid>` | an Equipment or any object record |
| `/position/<uid>` | a Position (an object record of an installable functional type) |
| `/installation/<uid>` | an Installation, with its Position and Equipment |
| `/document/<uid>` | a document, at its current approved revision |
| `/ticket/<key>` | a ticket. `key` is the ARGUS uid, or a migrated Jira key resolved by `/v1/lookup` |
| `/review/<uid>` | a review item: a proposal (claim id) or a conflict (conflict id) |
| `/lookup/<external-key>` | anything an external identifier became: an Insight object key or id, a Jira key, a label value (A40) |

- **One host:** the paths live on the ARGUS web host. The web application answers them by
  redirecting to its own routes (`/assets/…`, `/tickets/…`, `/documents/…`, `/review`), and it
  keeps the existing `/lookup/*` page.
- **Mobile:** Android App Links and iOS Universal Links declare the same host and paths, so the
  field client opens them directly where it is installed.
- **Everywhere else:** the same links are used in e-mail, in notifications, and by the redirects
  of the retired Jira host (revision §19 item 11).
- **Access:** opening a link needs authentication and **current** authorization. A link to a
  record the person cannot read shows "not found", as the API does. It never says the record is
  restricted.

### 7.2 What a QR label encodes

A new label encodes a **stable ARGUS lookup URL**, `https://<argus-host>/lookup/<opaque-id>`,
where the opaque id is the record's uid or a label id bound to it. It never encodes a mutable
name, a serial number or a physical location. A label moved between units is re-bound in ARGUS,
and the printed code is not reissued.

**Labels already printed** encode the label value: a key, a serial or an inventory number
(`LabelCode`). The field client resolves them through `/v1/lookup/{value}` exactly as it
resolves a URL. It never assumes that a scanned serial identifies a unit: several matches are
shown as candidates.

**Codes that are web links elsewhere** (a manufacturer's QR code, registered as a label from the
web's scanner) are label values too. Only an https link on the ARGUS host is followed as a path;
any other http(s) link is looked up among the labels and **never opened**. When no record carries
it, the app says which host it points to and offers to register the unit. Other schemes
(`javascript:`, `tel:`, `intent:`, `data:`…) are refused (`lib/core/link_parser.dart`).

---

## 8. Guided equipment replacement

The flow drives `POST /v1/installations/swap` (revision §8.4), extended as §3.1 describes. Each
step shows what the server knows, and the person confirms it.

1. **Scan the Position.** The person scans the Position's label or the rack slot, or searches.
   The app resolves it; a channel name resolves to a Position, never to Equipment.
2. **Show what is there.** The app shows the current Installation (unit, since when, how certain),
   the open tickets on the Position and on the unit, and the procedure linked to the Position's
   class, if any.
3. **Scan the outgoing unit.** If it is not the installed one, the app says so, and the
   discrepancy becomes evidence and a review item. It is never silently corrected.
4. **Removal details:** the time (a temporal value with precision, revision §8.2), the reason,
   the condition and a work reference (a ticket or work order).
5. **Scan the incoming unit.** Unknown to ARGUS: the app offers guided registration (revision
   §23.5, §23.11; AI nameplate capture, §4.4). A unit is never created from the Position or channel
   name (I-MOB-6).
6. **Server checks, before anything is submitted** (a dry-run call):
   - the unit's identity, duplicate candidates and ownership;
   - that it is not currently installed elsewhere (I-INS-1);
   - compatibility with the Position's class and expected Product Model;
   - retirement or merge state.
7. **Installation details:** the time and the evidence (photos of the installed unit and its
   label).
8. **Consequences:** the Access Points implemented through the Position, the Communication Paths
   and Bus Segments behind it, the linked documents and the open tickets. These come from the
   confirmed graph view, labelled as such.
9. **Protected ports:** where a segment has `safety_class ≠ none` or no unique compatible port
   match, the app asks for port confirmation, if the person has the specialist role. Otherwise it
   says who must confirm, and the replacement is submitted as a proposal (revision §9.3, D14).
10. **Submit one atomic command.** `replacement.submit` ends the old Installation and confirms
    the new one in one ledger batch, or proposes both when the person lacks the owner's rights.
    Offline, it is queued as a pending command and arrives as a proposal (§5.4).
11. **Status:** the app shows `pending` or `accepted`, then *deriving* until the derive stage has
    updated `implemented by` and `attached to` (revision §7.6, I-UX-1). Any port item left open is
    shown.

---

## 9. Tickets in the field

- **Position first.** The person scans or picks the **Position** that misbehaves, which is the
  canonical subject (revision §8.6).
  - Involved Equipment is derived from the Installation at the occurrence time, not typed.
  - The person may add a unit when they know it.
- **Occurrence time** is required for an operational incident (I-TKT-4). It is entered with the
  precision the person knows: an exact time, a day or a month.
- **Media:** photos, short video and files, uploaded as in §5.5.
- **Similar tickets** open on the same Position or unit are shown before submission.
- **AI assistance** (revision §23.7):
  - a spoken or typed report becomes a drafted title and description;
  - the type, severity and group are proposals;
  - impact is labelled as confirmed evidence, graph consequence, model inference or unresolved
    hypothesis;
  - causes stay hypotheses.
- **Updates:** the person comments, and moves the ticket only through the transitions the
  server's workflow allows for their role (revision §19 item 3). A transition with requirements
  asks for them.
- **Offline:** tickets, comments and media are drafted and queued (§5).
- **Never on mobile, and never by the model:**
  - confirming a root cause;
  - closing a safety-related ticket;
  - assigning blame;
  - retiring Equipment;
  - triggering a corrective action.
  A closure recorded offline arrives as a proposal (§5.4).

---

## 10. Documents in the field

The field client reads, and the web application authors.

- **Reading:** approved procedures, drawings, manuals and checklists, at the **current approved
  revision**. The app shows the version, the approval state, the review or expiry date and any
  supersession.
- **Offline copies:** only for documents marked for offline use and only if the person may read
  them.
  - A copy carries its revision id and is re-validated on every sync.
  - When it has been superseded or has expired, the app shows **"outdated: do not use"** and keeps
    it only until the new revision is downloaded.
- **Checklists** (documents with steps, revision §19 item 4) are run as **inspections**. Each step
  records a result, a note or a photo, and the result is submitted as `inspection.submit`, linked
  to the Position or unit.
- **Field input to documents:** photos and notes may be attached as **proposed inputs** for the
  document owner. They are not edits to the document.
- **Web-first:** authoring, comparison, approval and retention decisions stay in the web
  application. The app offers "open in ARGUS web" for them.

---

## 11. Notifications

| Event | Recipient |
|---|---|
| a ticket assigned | the assignee |
| a ticket escalated | the escalation targets (revision §19 item 3) |
| a proposal needs review | the steward of the owner domain (revision §18.2) |
| a synchronization conflict | the person whose command conflicted |
| a document superseded or expired | people holding an offline copy of it |
| an Installation or port confirmation required | the Position's owner or the specialist |
| a migration or reconciliation action assigned | the assignee |

- **Content-free push.** A push carries a notification id and a generic text, e.g. "You have a
  new assignment in ARGUS". It carries no record names, values, keys or restricted details.
- **Opening** a notification needs authentication and current authorization, and fetches the
  details from the API.
- **One source.** The in-app inbox, e-mail and push come from the same notification rows
  (`app.services.notify`). They already exclude people who may not see a record (I-ACL-1).

---

## 12. Platforms, distribution and device management

- **Targets:** Android and iOS in the first production release. Android-only is acceptable if the
  facility's field devices are all Android (U18). Web and desktop builds of the Flutter app are
  optional and must not delay the pilot.
- **Distribution:** institutional MDM, a private store (Managed Google Play, Apple Business
  Manager with custom apps) or an approved enterprise channel (U19). No public-store listing.
- **Minimum version:** the server answers **426 `client_too_old`** below the minimum version for
  security or API compatibility. The app then shows an update prompt and keeps drafts and
  pending commands until it is updated.
- **Device permissions,** each asked for when first needed:
  - camera, for scanning and photos;
  - photo library, only if importing existing photos;
  - notifications;
  - network;
  - local storage, which is app-private;
  - no location permission (location is a record in ARGUS, not the phone's GPS).

---

## 13. Observability, support and diagnostics

**Recorded,** without record values, free text, tokens or restricted data:

- the app version, build and platform; the API version; the environment;
- synchronization attempts, failures by `code`, and pending-command age;
- upload failures and retries; offline storage use;
- crash and performance metrics (start time, screen render, scan-to-result);
- AI Intake latency and result status (proposed, draft-only, failed);
- authorization failures (403, 401 `revoked`);
- the device registration and its last synchronization time (server side).

**The diagnostics screen** shows:
- the environment, the signed-in user and the workspace;
- the last successful sync and the pending commands, with their status;
- the cache size and age, and the app and API versions.

*Export diagnostics* produces a file with these values and the recent problem codes. It
contains no record data, and the person can review it before sharing it with support.

---

## 14. Testing

| Level | What |
|---|---|
| Contract | the generated Dart client is built from the committed OpenAPI contract in CI; a contract change without regeneration fails the build |
| Unit | use cases, mappers, the command queue state machine, retry and backoff |
| Widget | each screen, including error and offline states, at phone and small-tablet sizes |
| Integration | against a real ARGUS API on a test database (the backend's test fixtures). This covers sign-in, scanning a fixture QR, registering a unit, a replacement, an incident, and synchronization after a simulated outage |
| Synchronization | property tests: random interleavings of offline commands, lost responses and version changes never produce a duplicate write or an overwrite of a protected kind (A62–A65) |
| Security | revision §24 A66, A67, A69, A71 and A72, and the OIDC realm tests MOB-1…9 of `oidc-dev-setup.md` §6.2 |
| Device | a small matrix of real devices chosen with the facility (U18). Camera and scanning on real labels, in the real lighting of the halls |

---

## 15. First release (MVP) and phases

**MVP scope:**
1. OIDC login and workspace selection.
2. QR and barcode scanning.
3. Equipment and Position lookup.
4. Details and the current Installation.
5. AI-assisted nameplate capture.
6. Ticket creation with photos and occurrence time.
7. Guided replacement, as a proposal.
8. Assigned review items.
9. Offline drafts and synchronization.
10. Deep links.

**Not in the MVP:**
- web feature parity;
- schema administration and policy editing;
- bulk migration;
- graph editing;
- document authoring;
- unrestricted offline copies;
- automatic merge or retirement;
- any safety-critical autonomous action.

| Phase | Scope | Exit criterion |
|---|---|---|
| **M0 foundations (server)** | committed OpenAPI contract and generated clients; idempotency keys; record versions and preconditions; the problem shape; the device registry and revocation; the universal-link resolver and web redirects; resumable uploads; 426 minimum version | A57–A61 pass against the API; the web still passes its suite |
| **M1 read-only field client** | sign-in, workspace, scanning, lookup, details, current Installation, documents to read, diagnostics | A66 and A67 pass; a technician finds a unit by scanning in under 10 s (median) |
| **M2 capture and tickets** | guided registration with AI nameplate capture; incident tickets with media and occurrence time; comments and transitions; push | A69 and A70 pass; AI proposals are reviewable end to end |
| **M3 replacement and review** | the guided replacement (online), assigned review items | A68 passes; replacements appear correctly in the web and the graph |
| **M4 offline** | the pending-command queue, synchronization, conflicts, retention and wipe | A62–A65 and A71 pass; no duplicate writes in a week of pilot use |
| **M5 pilot** | SPARC vacuum equipment (U20), with its technicians | the pilot exit criteria (§16) are signed by the operational owner |


**Built so far.**

M0, in part:
- the committed contract and the field subset;
- the generated Dart client;
- the client header and 426;
- the device registry and revocation;
- the link resolver, with label values and ambiguous candidates;
- the web redirects for the link paths.

The rest of M0 is also built:
- the problem shape;
- idempotency keys;
- record versions with `If-Match`;
- stale commands on protected fields and stale replacements as review items;
- resumable uploads.

What is left of M0 is the push relay (U21).

M1, in `mobile/app`:
- sign-in (OIDC with PKCE, or a token in non-production builds) and device registration;
- the workspace choice;
- search, scanning, and typed labels checked by the label parser;
- Equipment and Positions with the current Installation and its history, open tickets and
  documents;
- tickets, and documents with their state shown first;
- universal links, which survive sign-in;
- diagnostics;
- the revoked and update screens.

Tests:
- 24 unit and widget tests run against responses recorded from a real API;
- the web build was checked in a browser against a local API.

Android and iOS builds, and the 10-second scan measure, still need a device.

M2, in `mobile/app` and on the server:
- **Incident reports**, from the record screen.
  - The report is Position-first: the scanned Position or unit is the subject.
  - The occurrence time is given as an exact time, a day or a month, and is required for an
    operational incident.
  - Photos go up through resumable uploads.
  - The open tickets on the record, and the guide's similar tickets, are shown before a new
    ticket is made.
  - An AI draft is built from the person's own words. Its proposals show confidence and
    evidence and are not used until taken. Hypotheses are labelled as unconfirmed.
  - The outcome is recorded against the intake run.
- **Ticket updates:**
  - comments, sent once with their own key; the server stamps the author;
  - photos;
  - the transitions the workflow allows, with their requirements and `If-Match`. A stale
    ticket is reloaded, never overwritten.
- **Guided registration:**
  - the nameplate photo is read by the server;
  - proposals are taken or corrected, and the guide's checks include duplicates;
  - the unit is created with the person's values and a server key, and the photo is attached as
    evidence;
  - an unknown scanned label offers registration, with the label as the serial;
  - nothing is created from a name (I-MOB-6).
- **Field limits on the server (A70):**
  - closing a safety ticket from the field client is recorded as a proposed transition (202),
    which a person confirms on the web;
  - root cause and corrective action are not edited from the field;
  - Equipment is not retired from the field.
- **Secrets (A69):**
  - a value that looks like a credential, read by the model from a photo, is dropped and
    counted, never stored;
  - text is still redacted before the model;
  - `test/no_secrets_test.dart` and `tool/check_build.sh` check that the app and a built bundle
    carry no provider credential, prompt or endpoint.
  - Redacting text *inside a photo* before the model needs on-device OCR, which is not built.
- **Notifications:** an in-app inbox with an unread badge. Push waits for U21.

M3, in `mobile/app` and on the server:
- **Guided replacement** (§8), from a Position:
  1. What is installed now.
  2. The outgoing unit: the recorded one, or a different unit scanned in place, which opens an
     `outgoing_discrepancy` review item.
  3. The time, reason, condition and work reference. The ticket gets a line saying what was
     replaced.
  4. The incoming unit: scanned, or registered from its nameplate when it is unknown.
  5. The server's dry run: identity, I-INS-1, compatibility and duplicates. The consequences
     come from the confirmed graph: Access Points, segments with their safety class, the segments
     the person cannot see (counted and still checked), documents and open tickets.
  6. Evidence photos, attached to the incoming unit.
- **The result:** the replacement is applied in one batch, or submitted as a proposal with its
  reasons. The reasons are a different outgoing unit, a port that needs a steward, or missing
  owner's rights. An approver confirms the proposal against the Position as it is then, or rejects
  it (A68).
- **Assigned review items**, one at a time: `GET /v1/ledger/review/mine` lists the items routed
  to the person, with the decisions the field client may take:
  - confirm or reject a proposed replacement;
  - resolve a discrepancy;
  - close a stale command;
  - confirm, correct or reject an AI proposal.

  Everything else says to decide it on the web.

Tests:
- 39 app tests;
- `tests/test_replacement.py`;
- a replacement driven in the web build against the live API.

M4, in `mobile/app` and on the server:
- **Pending commands** (§5.2, §5.3):
  - Every change goes through one queue: a report and its photos, a comment, a move, a
    replacement and its evidence, the intake outcome. The queue is kept encrypted in the platform
    keystore.
  - A command is sent at once when ARGUS answers. Otherwise it waits: in dependency order (the
    ticket before its comments and photos, A64), then in the order made.
  - Each command keeps its idempotency key (a lost answer is retried with the same key, A63), the
    version seen, and its capture time in server time (`X-ARGUS-Captured-At`).
  - A command ends `accepted`, `rejected` (a permission lost while offline is `forbidden` and is
    kept for the person, A62), `conflict` (with the review item) or `expired`. It expires on the
    device after the retention, and the server refuses a late one too (A65).
  - Retries back off with jitter and stop after 8 attempts.
- **Pending shown as pending:**
  - a ticket reported offline reads "Not yet in ARGUS", and only its author sees it;
  - unsent changes are listed on the ticket and in **Unsent changes**, where a refused change can
    be retried or discarded.
- **Saved copies** (§5.1):
  - A caching layer under the generated client keeps the reads of records and of the person's
    own work (assets, contexts, installations, tickets, documents, review items, notifications,
    and the assigned tickets, prefetched hourly), scoped to the person and workspace.
  - Searches, lookups by label, the assistant and uploads are never kept.
  - A record that becomes 404 or 403 leaves the device. A copy past the retention is not served.
  - Offline, the app says so in a banner across every screen.
- **Wipe** (§5.6, A71):
  - signing out or a revocation removes the session, the saved copies, the queue and its
    attachments;
  - the person is told which unsent changes were lost;
  - a voluntary sign-out with unsent work asks first.

Tests:
- 52 app tests, including A62–A65, A71 and the caching rules;
- server tests for A63 and A65;
- the offline round trip in the web build: a record read from its saved copy, a report kept
  offline, then sent when the browser came back online.

Not yet: attachments are kept base64 in the keystore, which suits photos but not long videos. A
Drift/SQLCipher store (§4.3) remains the option for larger volumes.

Ask, in `mobile/app/lib/features/ask` (after M4):
- questions answered from the workspace's records, streamed as server-sent events: the lookups
  as they run, then the answer; a cut-short or failed answer says so;
- follow-ups in the same conversation, and earlier conversations reopened (the web's too);
- the microphone dictates a question; an answer is read aloud on request, without its Markdown;
- hands-free: each answer read aloud, then the next question heard, until nothing is said;
- offered only when `/v1/ai/status` says the endpoint is usable, otherwise the reason is shown;
- never cached on the device. Proposals of changes stay on the web.

Tests: 6 app tests (streaming, follow-up, voice, hands-free, unavailable, refused), with a fake
voice in place of the platform's.

M2 tests:
- 35 app tests;
- the server tests for A69 and A70;
- the report and registration flows, driven in the web build against a live API with a
  stand-in model.


---

## 16. Measures and pilot exit

**Measured during the pilot,** against a baseline taken before it on the same tasks:

| Measure | Target (proposed, U25) |
|---|---|
| time to find an asset (scan or search to its page) | median < 10 s |
| time to register a unit (open to accepted) | median < 3 min, with AI capture |
| time to record a replacement | median < 5 min |
| AI extraction: accepted as is / corrected / rejected | tracked; correction rate falling over the pilot |
| duplicates prevented (guide or match warnings acted on) | tracked; no new duplicate of a unit registered on mobile |
| incident tickets with a valid occurrence time and a canonical subject | ≥ 95 % |
| offline synchronization success (accepted on first sync) | ≥ 98 %; zero duplicate writes |
| unresolved conflict age | median < 2 working days |
| crash-free sessions | ≥ 99.5 % |
| adoption among the pilot technicians | ≥ 80 % use it weekly by the end of the pilot |
| incomplete asset and ticket records (missing required data) | lower than the baseline |

**Pilot exit.** The operational owner (U20) signs that:
- the targets are met, or the gaps are accepted;
- no invariant (I-MOB, I-INS, I-ACL) was violated;
- the technicians' feedback has been addressed or scheduled.

Only then does the app extend to another domain.

---

## 17. Decisions for stakeholders

These are listed with the others in `asset-model-revision.md` §21 (U18–U25):

- **U18 Devices.** Which devices and OS versions, and are they all institution-owned? Android-only
  is possible if so.
- **U19 Distribution.** Which MDM or private store?
- **U20 Pilot owner.** Who owns the pilot and its sign-off, and who are the pilot technicians?
- **U21 Push.** FCM/APNs through a server relay, the MDM's channel, or in-app polling only? This
  includes where the relay runs and what the provider sees (only a device token and an opaque id).
- **U22 Offline retention.** How long cached data and pending commands may live on a device, and
  which restricted classes, if any, may be cached at all.
- **U23 Media limits.** Maximum photo and video size and duration, retention of field media, and
  whether EXIF is ever kept.
- **U24 Certificate pinning.** Pin the ARGUS endpoint, or rely on the managed trust store?
- **U25 Targets.** Sign-off of the pilot measures and targets in §16.
