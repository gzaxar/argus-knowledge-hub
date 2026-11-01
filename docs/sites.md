# Sites: a laboratory's places, shared with the facilities it hosts

Status: **revised proposal, for approval** (2026-11-01).

## The need

LNF is a laboratory that hosts several facilities and accelerators (SPARC, BTF, DAΦNE, ELI…), each with its own
workspace. The places — buildings, halls, floors, rooms, their floor plans and where those sit on the map — are
LNF's: drawn once, kept by LNF's people. The facilities need them: to see the buildings and plans on their map,
and to place their own equipment in a room and on a plan. A facility's equipment stays the facility's: owned by
it, edited there, seen only by those who may read it.

## What the code does today (read before revising)

| Area | Today | Consequence for sites |
|---|---|---|
| Asset visibility | `visibility.visible_assets_clause` / `asset_visible_in`: own workspace, or `is_global`; restricted classes on top. Used by 22 modules (lists, search, map, graph, hub, MCP, Ask). Hand-rolled in three places: `attribute_validation._is_reference_visible`, `routers/field.py` (twice). | Site visibility goes in the central functions and those three places — nowhere else. |
| Editing | `_get_owned_asset`: only the owning workspace edits a record. | Unchanged: only LNF edits LNF's places. |
| Floors, plans, plan images | `routers/indoor.py` `_level` / `_plan`: `workspace_id ==` the caller's. | Must read site-shared floors and plans; edit stays owner-only. |
| Placing a record inside | `indoor.place`: place, floor and plan must be in the record's own workspace. | Must accept a site-shared place, floor and plan. |
| What a plan shows | `get_plan`: every record placed on it, filtered only by restricted class (`_permitted` ignores the record's workspace). | With several workspaces on one plan this would leak BTF's equipment to SPARC: filter by workspace permission too. |
| Map plans | `/map/plans`: plans of the workspaces asked for. | Add the site-shared plans. |
| Transfer | Move keeps uids (`workspace_id` reassigned); copy mints new ones. Floors, plans and placements are not carried. Moving out of the catalogue is refused (system catalogue C1). | Carry indoors; allow moving a record that is not a Vendor or Product Model out of the catalogue. |
| Edificio 2 | An Area in the catalogue, `is_global` (like every catalogue record): every workspace sees it. | The migration must say what stops resolving if it is no longer global. |

## The rules

### 1. Roles and the site relationship

- `workspaces.role` gains `site` (next to `catalogue`). `workspaces.site_id` names the one site a facility
  workspace is at.
- Validated: the site exists and has role `site`; a site is not itself at a site, nor is it the catalogue; the
  catalogue is at no site; a workspace is not at itself. With one level and these checks a cycle cannot form,
  and they are checked again whenever a role or `site_id` changes (a workspace with facilities cannot stop
  being a site until they are moved).
- Set by an administrator (Administration › Workspaces), or when a workspace is created.

### 2. Site-scoped place visibility

A record of a site is **site-shared** when it is a *place* — its type is Location or below it (Area, Building,
Room, Rack, Storage Location…) — and it is not withheld (rule 3). A site-shared record is visible from the site's
facilities, and only from them; it is distinct from `is_global`, which shares with every workspace.

- Stored as `assets.site_shared` (indexed), kept by one function (`sites.refresh`) when a place is created or
  retyped in a site, placed inside another or removed from it, withheld or released, moved by a transfer, or
  when a workspace's role or site changes. Reading it costs nothing more than `is_global` does.
- `visible_assets_clause(W)` and `asset_visible_in(a, W)` become: own workspace, or global, or site-shared by
  the site W is at; restricted classes apply as before. So lists, search, the map, the graph, the room selector
  (a search) and references see a site's places from its facilities — and nothing else of the site.
- Reference validation (`_is_reference_visible`) and the mobile routes (`field.py`) use the same rule.
- A floor and a plan are visible where their place is visible; a plan image the same.

### 3. Not shared with the facilities

- `assets.site_withheld` on a place withholds it **and everything inside it** (its rooms, their rooms, by the
  indoor *it is in* chain) and their floors and plans.
- Withholding is previewed: the places it would withhold, and every facility record placed in them, on their
  floors or on their plans, by workspace.
- **Placements when sharing is withdrawn** (a place withheld, a facility leaving the site, a workspace ceasing
  to be a site): a facility record's placement in a place that is no longer shared with it, or on a floor or
  plan of one, ends — state `withdrawn`, `valid_until` now, a line in the record's history ("no longer placed in
  Hall 3: LNF stopped sharing it"). The record keeps the map position the plan gave it (as its last known
  position, source `plan`); it is not moved or deleted. Releasing the place again does not restore placements:
  the history keeps them, and they are placed again.

### 4. Placing facility equipment on site places

- A facility record may be placed in a room shared with its workspace, on that room's floors, and on its plans
  (or those of a place it is in). The placement belongs to the record's workspace; the place, floor and plan
  stay the site's.
- Only site editors change places, floors, plans and their position on the map (owner-only, as today).
- **What a plan, a place's contents and a record's containers show** is filtered per record: a record placed
  there is shown when the viewer could see it — it is visible in the viewer's current workspace (own, global,
  site-shared), or the viewer may read the record's workspace — and the viewer's restricted-class grants for
  that workspace allow it. SPARC's people do not see BTF's equipment on a shared LNF plan unless they may read
  BTF. API tokens see only what their own workspace can.

### 5. Transfers carry indoors; Edificio 2 moves with a report

- A transfer of a place carries its floors, its plans — their files and source files (copied for a copy, kept
  for a move), control points, fit and residual — and the indoor placements of the records it transfers.
- A placement is **eligible** when its place, floor and plan are visible to its record's workspace after the
  transfer (the same workspace, or site-shared to it). An ineligible one is not carried: it ends as `withdrawn`,
  and the report names it.
- `POST /v1/transfers/preview` gives the reconciliation report before anything changes: the records, floors,
  plans (files present, fit kept) and placements that would go; and every reference to the records moving —
  relations, reference attributes, placements of other records in them, labels — each with whether it still
  resolves afterwards from the referencing record's workspace, and why not.
- **Edificio 2 moves, keeping its uid** (a move, not a copy then a delete): every reference to it stays valid by
  construction, and nothing has to be deleted. Moving records that are not Vendors or Product Models out of the
  catalogue is allowed; Vendors and Product Models stay protected. The report also says that Edificio 2 is
  global, which workspaces reference it from outside LNF and its facilities, and so whether it can stop being
  global and rely on the site. It is not moved until the report has been reviewed.

## Stages

**S1 — Sites and site-scoped visibility.** Migration (`workspaces.site_id`, role `site`, `assets.site_shared`,
`assets.site_withheld`); validation; `sites.refresh`; the central visibility functions, reference validation
and mobile routes; administrators' API for roles and sites. Tests: SPARC and BTF see LNF's places and not each
other's equipment; a site's other records stay private; validation refuses a cycle, a site at a site, the
catalogue as a site.

**S2 — Indoors across workspaces.** Floors, plans and images readable where their place is; placing facility
records on site places; plan contents, place contents and containers filtered per record; map plans; withholding
with its preview and the withdrawal of placements. Tests: SPARC and BTF on one LNF plan, each seeing only its own
equipment (and LNF's if it may); a withheld building and its rooms and plans; placements ended on withdrawal.

*As built (S1, S2).* `services/sites.py` (`set_role`, `set_site`, `refresh`, `withdraw_placements`,
`affected_by_withdrawal`, `inside`, a flush guard for records created, retyped or moved into a site);
`visibility.reachable_in` / `site_clause` in the central rule, reference validation and `routers/field.py`;
`/v1/admin/sites` (list, role, site — leaving a site previews the placements that end unless `confirm`).
Indoors: `_level` / `_plan` read where the place is seen and change only in its workspace; `indoor.place`
accepts a place, floor and plan the record's workspace reaches; `_viewer` filters a plan's records, a place's
contents and a record's containers per record (reachable from the viewer's workspace with its grants, or in the
record's own workspace if the person may read it, with that workspace's grants); `/map/plans` lists the plans of
every place seen; `GET/PUT /v1/assets/{uid}/site-sharing` withholds a place and what is inside it (preview
unless `confirm`) or shares it again. Tests: tests/test_sites.py.

**S3 — Transfers carry indoors, with a preview.** Floors, plans, files, fits, eligible placements; the
reconciliation report; records that are not Vendors or Product Models may move out of the catalogue. Tests:
transfer integrity (files, fits, placements; copy and move), the report on a place referenced from elsewhere.

**S4 — Web and documentation.** Administration › Workspaces (role and site), a place's *Not shared with the
facilities* with its preview, room and plan choosers listing the site's places, the transfer preview report;
the administrator setup and the user workflow in the guide.

**S5 — Production (after review).** Nothing in production changes before this stage, and then only on approval:
make LNF a site and set its facilities; run the Edificio 2 transfer preview, review the report; then move it.

## Not in this proposal

- Sharing a place with an arbitrary list of workspaces (a site covers the case).
- A deeper hierarchy of workspaces, or a workspace at several sites.
- Facilities editing a site's places or plans.
