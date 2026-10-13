# GLPI in the IT package

How ARGUS hosts what a GLPI installation holds, and GLPI's own schema, while keeping its own schema and ledger
rules. Code: `backend/app/integrations/glpi/` (`source`, `discovery`, `mapping`, `schema`, `importer`), the
API `backend/app/routers/glpi.py`, the web page *Administration › GLPI*. User help: topic *GLPI*.

## Principles

- **Interfaces, not the database.** ARGUS reads GLPI's legacy REST API (`apirest.php`), which GLPI 10 and 11
  both have. GLPI 11's high-level API (`api.php/v2`) is detected and recorded, not read: an installation that
  has turned the legacy API off is told so. Sessions are opened read-only and closed after each read.
- **Discover, never assume.** Every read starts from what this installation exposes to this token: version,
  entities, item types (and the ones the token cannot read, with GLPI's reason), custom asset definitions and
  fields (GLPI 11), the *fields* and *genericobject* plugins (GLPI 10), other plugins. The result is recorded
  on the connection (`params.discovery`).
- **ARGUS owns its schema.** Standard GLPI item types map onto ARGUS's IT, core-objects and core-records
  types. GLPI's own types and fields become workspace types and fields only through a reviewed proposal; a
  change in GLPI's schema waits for review again and changes nothing by itself.
- **Nothing is lost.** Fields ARGUS does not map are kept on the record as GLPI gave them (`glpi_unmapped`,
  JSON); every record keeps its GLPI link (`glpi_url`).
- **The ledger's rules hold.** Records enter as source claims bound to stable GLPI identities; a person's
  confirmed edit is never overwritten by a source; nothing is retired because the source went quiet.

## The flow

1. **Connection** (`POST /v1/glpi/connections`): address, user token, optional application token, TLS check,
   key prefix, whether to bring tickets and documents. Tokens are Fernet-encrypted (`services/crypto`) together
   and never returned. Recommended GLPI setup: a dedicated user whose profile has *read* only on the item types
   imported, in the entities imported; an API client restricted to ARGUS's address and given an application
   token.
2. **Discovery** (`POST …/discover`): the snapshot, its discovery report, a first entity mapping (the top
   entities the token sees, recursively, to the connection's workspace) and the schema proposal.
3. **Entity mapping** (`PUT …/entity-map`): `[{entity_id, workspace_id, recursive}]`. An entity maps to the
   nearest mapped ancestor that is recursive (or itself); unmapped entities are not imported (counted). The
   person setting it must be able to create records and tickets in each target workspace.
4. **Authority** (`PUT …/authority`): `records` and `tickets`, each `argus` (default) or `glpi` — below.
5. **Schema review** (`POST …/schema/approve` with the proposal's digest; needs *approve* on objects): creates the
   proposed workspace types (`<ws>:glpi-type:<system name>`, under IT Equipment) and fields (`glpi_<name>`,
   `glpi_<container>_<name>` for plugin fields), and records the mapping. A digest from an older proposal is
   refused.
6. **Preview** (`POST …/preview`): per workspace — records created / updated (which fields) / unchanged,
   conflicts with local edits and their outcome, local edits kept, retirement candidates, types missing,
   positions, tickets, documents; overall — custom types awaiting schema review, entities outside the map. The
   report carries the snapshot's digest; values of restricted fields are left out for viewers without the class.
7. **Import** (`POST …/run`, optionally `expect_digest`): if GLPI changed since the preview, 409 with the new
   plan. Recorded as an import job.
8. **Retirement decisions** (`GET/POST …/retirement-candidates`): `retire` or `keep`.

## Mapping

| GLPI | ARGUS | Notes |
|---|---|---|
| Computer | Server / Workstation / Computing Node | by the computer type's name (server, VM → Server; desktop, laptop, workstation → Workstation) |
| NetworkEquipment | Switch / Router / Firewall / Wireless Access Point / Network Device | by the network equipment type's name |
| Monitor, Printer, Peripheral, Phone | IT Peripheral | `peripheral_kind` |
| Rack | Rack (a place) | `number_units` → `rack_units` |
| Location | Location | `completename` as the name, parent → `part of`, `building` → `site`; latitude/longitude → the GIS rules (an approved location is never overwritten; a different one is an observation for review) |
| Supplier | Organization | company, website, ISO country when it is one |
| Software / SoftwareVersion | Software Product / Software Version | publisher, category; version → product reference |
| Item_SoftwareVersion | relation `has installed` | |
| SoftwareLicense | Software License (a Contract) | seats, expiry → `end_date`, the key → `license_key` (restricted class `license_keys`) |
| Contract, Contract_Item, Contract_Supplier | Contract, relation `governed by`, `counterparty` | `end_date` = begin + duration; renewal |
| NetworkPort, IPAddress | Equipment Port (`port of` its owner), the owner's `ip`/`mac` | other addresses kept unmapped |
| Ticket / Problem / Change | Incident or Service Request / Problem / Change (IT kinds) | statuses as below; urgency, impact, priority; links (`Item_Ticket`, `Item_Problem`, `Change_Item`) as ticket–record links |
| Document, Document_Item | attachments of the linked records and tickets | each once (`backend_id`), downloaded through the API |
| User, Group | references | a login matching exactly one ARGUS user (username or e-mail) / a group name matching exactly one group; otherwise kept unmapped |
| GLPI 11 custom assets, GLPI 10 genericobject types | approved workspace types | `custom_<field>` values by the approved mapping; dropdown ids → their labels |
| GLPI 10 fields-plugin values | approved workspace fields on the mapped type | |

Ticket statuses (`CommonITILObject`): new → `new`; assigned, planned, accepted, observed, evaluation, testing,
qualification → `in_progress`; waiting, approval → `pending`; solved → `resolved`; closed, refused, cancelled →
`closed`. Changes follow the IT change workflow (requested, assessed, approved, scheduled, implemented, closed,
refused). The GLPI status is kept as `argus_source_status`.

Keys are `<prefix>-<abbreviation>-<GLPI id>` (CMP, NET, MON, PRN, PER, PHN, RCK, LOC, ORG, SW, SWV, LIC, CTR;
a port is `<owner key>:<port name>`). Identities are `glpi:<host>:<itemtype>:<id>` — immutable, like Insight's.

## The ledger side

Per target workspace, two streams of kind `glpi`: `glpi:<host>@<ws>` (records, parser `glpi`, rule
`glpi.record/1`) and `glpi-refs:<host>@<ws>` (reference fields resolved to ARGUS ids once both ends exist,
parser `resolved`, rule `glpi.reference/1`). The policy is (re)activated when a stream is new to it.

- Importing identical content: the ledger skips the parse (`parse_skipped`), nothing changes.
- A changed field nobody edited in ARGUS: applied.
- A field a person edited and confirmed in ARGUS: the person's value holds against any source. If GLPI then
  changes it differently, the ledger opens a `source_vs_confirmed` review item, and the preview lists it.
- **authority `argus`** (default): GLPI is a contributory source. **authority `glpi`**: a policy rule makes this
  connection's streams authoritative (protected identity fields included, with the reason recorded), so GLPI
  wins over other sources such as Insight; a person's confirmed value still goes to review rather than being
  overwritten. For tickets (not in the ledger) the authority decides directly, three-way against the values
  last imported (`glpi_imported`).
- **Disappearance.** A record GLPI deletes, trashes or stops showing is carried forward in the stream (so the
  ledger does not retire it) and a `retirement_candidate` review item is opened (non-blocking; closed again if
  GLPI lists it again). `retire` retires the record (history kept) and stops stating it; `keep` confirms its
  existence as a person and stops stating it.

## Version differences handled

| | GLPI 10 | GLPI 11 |
|---|---|---|
| Custom asset types | plugin *genericobject* (`PluginGenericobjectType`, items of `PluginGenericobject<Name>`) | asset definitions (`Glpi\Asset\AssetDefinition`, items of `Glpi\CustomAsset\<System name>Asset`) |
| Custom fields | plugin *fields*: containers (`PluginFieldsContainer`), fields (`PluginFieldsField`), values read from the plugin's per-container item type (both of its naming forms are tried; one not readable is reported) | `Glpi\Asset\CustomFieldDefinition`, values as `custom_<system name>` on the items |
| Field types | text, textarea, richtext, number, url, date, datetime, yesno, dropdown, `dropdown-<Itemtype>` (names); `glpi_item` not supported; headers skipped | String, Text, Number, Date, DateTime, URL, Boolean, Dropdown; others (e.g. Signature) not supported |
| High-level API | — | detected (`api.php/v2/status`), not read |

## Tests

`backend/tests/test_glpi.py`, on fixtures `backend/tests/fixtures/glpi/glpi10.json` and `glpi11.json`:
discovery per version; entity mapping; schema proposals (reuse, create, unsupported) applied only once
approved; a changed source schema waiting for review; plugin fields on the workspace's type, never the
package's; the standard mapping scoped by entity (both versions); idempotent re-import; local edits under both
authorities; retirement candidates and decisions; prerequisites; restricted licence keys; the live client
against a fake of the REST API (sessions, headers, paging by `Content-Range`, missing rights, documents); the
API end to end (secrets never returned, stale approvals and stale runs refused).

## Not in this release

- Reading through the high-level API (GLPI 11 with the legacy API off).
- Writing back to GLPI.
- Item types beyond those above (enclosures, PDUs, cables, certificates, appliances, databases, domains),
  ITIL followups, tasks, solutions and validations, contract costs, infocoms (financial data), the
  `Ticket_User` actors beyond the main user.
- Scheduled, incremental reads by `date_mod` (each read is complete; repeating it is idempotent).
