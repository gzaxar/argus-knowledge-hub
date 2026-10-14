# Domain packages: capabilities, collisions and design

How ARGUS's template packages (docs/packages.md) were extended to seven more domains and to GLPI
(docs/glpi.md): what existed, where names collided, how each requirement maps onto the implementation, and
what only a domain owner can decide. The repository has no `AGENTS.md`; the design documents in `docs/` were
the reference, checked against the code (§1).

**None of these packages establishes regulatory compliance.** The safety, radiation protection, access
control, contract and technology-transfer definitions and workflows are a structure to start from; §7 lists
what the people responsible for each domain must approve before relying on them.

## 1. What existed, and where the documents and the code disagreed

| Capability | Where | Before this work |
|---|---|---|
| Packages: format, validator, installer, version record, previews, upgrades | `app/packages/` | object types, enumerations, ticket and document kinds (no fields of their own), equipment classes; the core's workflow only |
| Record and field visibility | `services/visibility.py` | five fixed restricted classes |
| Attribute validation on save | `services/attribute_validation.py` | required, cardinality, regex, enumeration, uniqueness, reference type |
| Workflows | `services/workflows.py` | per workspace, bound to ticket types; transitions could require an assignee, resolution or comment |
| Role templates | `services/access_review.py` | eight fixed templates |
| Relation semantics | `services/causal_model.py`, `ledger/registry.py` | verbs of the model and of extensions |
| Sources and identities | `ledger/` | streams, parsers, authority policy, identity bindings, conflicts |
| Import prerequisites | `packages/requirements.py` | EPIK8s and PBS declared theirs; the locations import and the Insight and Git imports did not say |

Disagreements found and resolved:

- `docs/packages.md` called `core-facility` domain neutral, but its *Operational impact* offered *Beam down*,
  *Beam degraded*, *No beam impact*, and core-objects' *Criticality* *Beam-critical* and *Degrades beam*.
  → core-facility 2.0 and core-objects 2.0 are neutral; the accelerator package adds the beam options back as
  an **extension**, with the same option ids, so no accelerator workspace loses anything (§5).
- `docs/roles.md` lists the restricted classes as closed; domain packages need their own. → packages declare
  restricted classes; the set is ARGUS's plus the packages' (`visibility.restricted_classes()`).
- Startup recorded a package as present when a workspace had **one** of its types. A type moving to a new
  package (Radiation Monitor to safety) would have marked every accelerator workspace as having the whole new
  package. → detection needs all of a package's types (in the workspace's scope), and an upgrade fills in the
  types a merely detected package never received (this also repairs workspaces detected in 1.35.24).

## 2. Naming collisions and reuse

| Wanted by | Name | Existing | Decision |
|---|---|---|---|
| Access control | Access Point | accelerator: an EPICS control endpoint | **Door**, **Badge Reader**, **Access Controller**, **Access Zone**; never "Access Point" |
| Safety | Radiation Monitor, Interlock Unit | accelerator | **moved** to `safety`, unchanged |
| Safety | radiation area classification | core-objects' Area has `radiation_classification` and Location `access_rule` | **Radiation Area** and **Fire Zone** are kinds of Area and reuse both |
| Vacuum, cryogenics | Vacuum Pump (and Ion, Turbo, Primary, NEG), Gauge, Valve, Chamber, Controller, Component; Cryogenic Device | accelerator | **moved** to `vacuum-cryo`; *Vacuum Sector* (a functional element) stays |
| Optics | Laser System, Optical Assembly | accelerator | **moved** to `optics-alignment`; *Mirror*, *Lens*, *Beam Splitter* are beam-line positions and stay; the physical units are *Optical Mirror*, *Optical Lens* |
| Environmental | a sensor | hvac: HVAC Sensor (a control input) | **Environmental Sensor** (a monitoring instrument, under Instrument) |
| Admin, TT, GLPI | Organization, Contract | none (Vendor is a supplier of products) | in **core-records**; TT's *License Agreement* and *Confidentiality Agreement*, admin's *Grant Agreement*, IT's *Software License* are Contracts |
| Admin | Procurement Record | accelerator (a beamline's cost line) | stays; *Purchase Order* is the administrative record |
| TT | Project | accelerator's Work Package | **Valorization Project** |
| GLPI | Computer, network equipment | Server, Workstation, Switch… | Computing Node and Network Device became **concrete** for what GLPI does not classify further |

Moved types keep their name, uid, attributes and option ids; an upgrade reports them as *moved* (no decision).
Tests: `test_domain_catalogue.py::test_no_two_packages_define_the_same_type_kind_verb_role_or_class`,
`…::test_no_type_redefines_a_field_it_inherits` (the two redefinitions that predate 1.35.26 are allowed, by
computing them from the 1.35.25 packages).

## 3. The packages

| Package | Version | Owner (to be adopted by) | Depends on | Provides |
|---|---|---|---|---|
| core-facility | 2.0.0 | INFN ARGUS | — | tickets, documents |
| core-objects | 2.0.0 | INFN ARGUS | core-facility | object-catalogue |
| core-records | 1.0.0 | INFN ARGUS | core-facility | records |
| it | 1.1.0 | INFN ARGUS | core-objects, core-records | it-catalogue |
| safety | 1.0.0 | the site's safety service | core-objects | safety-catalogue |
| vacuum-cryo | 1.0.0 | vacuum and cryogenics groups | core-objects | vacuum-catalogue |
| civil-access | 1.0.0 | technical services | core-objects | building-catalogue, access-control |
| optics-alignment | 1.0.0 | laser and survey groups | core-objects | optics-catalogue |
| environmental | 1.0.0 | environmental service | core-objects | monitoring-catalogue |
| administration | 1.0.0 | administration | core-records | administration |
| tech-transfer | 1.0.0 | technology transfer office | core-records | technology-transfer |
| accelerator | 2.1.0 | INFN ARGUS | core-objects, it, safety, vacuum-cryo, optics-alignment | accelerator-catalogue |
| electrical, hydraulic, hvac | 1.1.0 | INFN ARGUS | core-objects | … |

Each domain package defines: types with stable field keys, units and controlled values; code validators
where a pattern is not enough; typed relations with their causal meaning; ticket kinds with their own fields
and the workflows that govern them; document kinds; role templates; restricted classes where needed; the
importers it supports; representative queries with fixtures and expected results.

## 4. Package mechanisms added

| Mechanism | In a package | Implemented by |
|---|---|---|
| Extensions | `extends: [{area, type, attributes, options}]` on a type a dependency defines | `install.apply_extensions`; upgrades diff them; an option a package stops defining because an installed package now extends it is *moved*, not removed (`upgrade._kept_by_extensions`) |
| Kind fields | `attributes` on a ticket or document kind | `install._kind_fields`; diffed in upgrades |
| Package workflows | `workflows: [{…, applies_to: [kinds]}]`; a transition may `require: [approver]` | `install.add_workflows` (bound to kinds without one; an edited copy is never replaced); `workflows.transition(may_approve=…)` |
| Typed relations | `relation_types: [{id, verb, from, to, layer, flows, carries}]` | `packages/relations.py`: causal semantics, ledger registry endpoints, refused between wrong types (`POST /v1/relations`) |
| Role templates | `roles: [...]` | `access_review.package_templates` — offered for the packages a workspace has; never granted |
| Restricted classes | `restricted_classes: [...]`; `restricted: <class>` on a field | `visibility.restricted_classes()`, field hiding everywhere records are read |
| Code validators | `validator: <id>` on a field | `packages/validators.py` (`it.mac_address`, `admin.cig`, `admin.cup`, `tt.patent_number`, `tt.doi`, `tt.orcid`, `optics.wavelength_nm`, `core.not_after_today`…), enforced on save |
| Import requirements | `imports: [{importer}]` | `packages/importers.py`: every importer's prerequisites, checked by the package validator and by the importer |
| Representative queries | `queries: [{id, title, entity, jql \| from+relation, fixture, expect}]` | `packages/queries.py`; every one runs in `test_domain_catalogue.py` |

Packages stay declarative: anything that computes is code referenced by a stable id the validator checks.

## 5. Compatibility

- A workspace on 1.35.25's packages upgrades with **no decision** when it has the accelerator package: moved
  types are *moved*, the beam options are *moved* to the accelerator's extension, the new types are added,
  every record keeps its values (`test_an_accelerator_workspace_of_1_35_25_upgrades_with_nothing_lost`).
- A workspace **without** the accelerator package that had the beam options (it, electrical… on 1.35.25) is
  asked, per option, to keep or remove them (`…decides_about_the_beam_options_it_had`).
- The parity test (`test_packages.py`) still compares seeding with the record made before packages existed;
  it now lists exactly what 1.35.26 adds and requires everything else identical.
- Existing ids, field keys, option ids, relations and data are untouched.

## 6. Workspace selection and navigation

- `POST /v1/packages/preview` (administrators): the new workspace's installation, tried in a scratch workspace
  and rolled back — each package with exact version and checksum, and what it creates. Shown in the *New
  workspace* form.
- New workspaces are private and hold no records. Only IT: core-facility, core-objects, core-records, it. Only
  technology transfer: core-facility, core-records, tech-transfer — no equipment, no map, no beam model.
- `GET /v1/workspaces/{id}/capabilities`: what to show. The web sidebar, the *New* menu and the app's drawer
  hide what a workspace cannot use (equipment pages and the map without an object catalogue; the beam model
  and control bindings without the accelerator package).

## 7. Decisions for domain owners

Until approved, these are proposals encoded as a starting structure.

**Safety, fire protection, radiation protection** (safety service, radiation protection expert)
- Inspection intervals, the result scale, and whether *Pass with remarks* exists.
- Fire classes and extinguisher agents for the site's country; whether fire zones follow the fire safety plan.
- Radiation area classes (the core's *Supervised / Controlled / Prohibited*), dose-rate limits, who may see
  source storage details (`source_security`), whether dosimeter assignment should be recorded here at all
  (doses are deliberately not).
- The permit-to-work workflow (states, who approves, suspension) and the incident workflow, and who sees
  incident investigations (the built-in `safety_investigation` class).
- Moving Interlock Unit (PSS, MPS…) under safety rather than machine protection.

**Vacuum, cryogenics, gas** (vacuum and cryogenics groups, pressure-equipment responsible)
- Leak-rate acceptance values, bake-out steps, gas and cryogen lists.
- Pressure-equipment categories and inspection periods; relief-device test periods.

**Civil works, buildings, access control** (facility manager, security officer)
- Security levels and the access-request workflow (who approves, who grants on the access system, expiry).
- Whether personal data of access requests (`for_person`) should be kept in ARGUS, and for how long.
- Which building systems carry statutory inspections, and the certificate kinds.

**Optics, lasers, alignment** (laser safety officer, survey group)
- Laser classes allowed per area, the laser work authorisation workflow, required eyewear wording.
- The survey network's frame and the tolerance that makes a survey a finding.

**Environmental and monitoring networks** (environmental officer)
- The measured quantities and units, alert and alarm thresholds, which exceedances must be notified and to whom
  (the workflow's *Notify* step), sampling frequencies.

**Administrative and contract management** (administration)
- The procurement procedures listed and the approval chain (budget check, approval); whether CIG and CUP apply.
- Which amounts are `costs` and which terms `commercial_terms`; whether Vendor (core-objects) should become a
  kind of Organization.

**Technology transfer and research valorization** (technology transfer office, IP committee)
- The disclosure decision options and the evaluation workflow; who sits on the committee.
- Which content is `unpublished_invention`, and when a record stops being restricted (publication, filing).
- Annuity decisions (thresholds, who approves), licence kinds, spin-off stages.

**IT** (IT service): the GLPI mapping choices in docs/glpi.md (computer and network type classification,
which item types to import, the authority policy per connection).

## 8. Left for a later release

- Reading GLPI 11 through its high-level API; writing back to GLPI; the GLPI item types and ITIL details listed
  in docs/glpi.md.
- Import formats for the new domains (e.g. a fire-equipment register spreadsheet, a monitoring network's
  station list, a patent office export) beyond the locations import they all support.
- Time series (environmental measurements, dose records) — kept in the systems that record them.
- A package's own map symbols per layer, and per-domain dashboards.
- Field-level approval workflows (approving a change to a single safety-relevant field).
