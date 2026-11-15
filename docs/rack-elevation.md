# Rack elevations

What is mounted in a rack, and where. Before this, a unit's place in its rack was a line of text on its indoor
placement ("rack unit 34"): nothing could check that two units did not share a unit, and nothing could draw it.

## The model

A **mounting** (`rack_mountings`) says that something sits in a rack:

| field | meaning |
|---|---|
| `rack_uid` | the rack (a record of type Rack) |
| `asset_uid` | the unit; empty for a reserved space, optional for a shelf |
| `kind` | `device`, `shelf`, `reserved`, or `zero_u` (in the rack, taking no unit: a vertical PDU) |
| `start_u`, `height_u` | the lowest unit taken, counted from the bottom, and how many units |
| `face` | `front`, `rear`, or `both` (a full-depth unit) |
| `shelf_uid` | the shelf mounting a unit stands on; it then takes no unit of its own |
| `source`, `evidence` | `manual`, `field` or `import`; what a photograph showed, with its confidence |
| `state`, `valid_from`, `valid_until`, `confirmed_by` | nothing is overwritten: a move closes the old row and opens a new one |

The rack's capacity is its `rack_units` attribute (42 when not set). A unit's height is **suggested** by its own
`rack_units`, else by its product model's; the person mounting it has the last word.

## The checks

A change is refused, whole, when its result would have:

- a mounting outside U1…capacity (`capacity`);
- two mountings in the same unit of the same face — `both` counts on both (`overlap`);
- the same unit mounted twice (`twice`);
- a unit standing on a shelf that is not in this rack (`shelf`).

A unit can be in one rack at a time: placing it in another closes its mounting in the first.

## The API

| | |
|---|---|
| `GET /v1/racks/{uid}` | the elevation: mountings, free ranges per face, units used, what is wrong now |
| `GET /v1/racks/{uid}/history` | every mounting the rack has had, newest first |
| `POST /v1/racks/{uid}/preview` | what a list of operations would do — changes in words, problems, the rack as it would be; writes nothing |
| `POST /v1/racks/{uid}/apply` | the same operations, all or none (409 with the problems when inconsistent) |
| `GET /v1/racks/candidates?q=` | records that could be mounted, where each is now, the height its model suggests |
| `GET /v1/racks/of/{asset_uid}` | where a unit is mounted now |

Operations: `place` (a unit, or `kind: zero_u`), `shelf`, `reserve`, `update` (move or resize a mounting),
`remove`. A shelf made in a change can carry a unit placed later in the same change: give it a `ref` and name
that as the unit's `shelf_uid`.

After a unit is placed, its `Located in` is set to the rack as a person's statement in the ledger, so the
`located in` edge, the floor plan and impact analysis follow. If that cannot be written (a frozen workspace), the
mounting stands and the response's `notes` say so.

## In the web application

A Rack's page shows its elevation; **Edit the rack** (`/racks/{uid}`) opens the editor: front and rear, units
numbered from the bottom, blocks dragged with the mouse or a finger or placed by a form, shelves, reserved spaces,
0U devices, and the history. Every change is staged and shown as a preview; nothing is saved until it is
confirmed. A mounted unit's page says which rack and units it is in.

## Bundles

`rack_mountings` is a family of the workspace bundle, so an export and import reproduces the racks with their
history.

## The demos

Both demo bundles (`backend/demo_workspaces/it-services`, `medium-linac`) come with their units in their racks:

- **IT services:** ten racks — hypervisors, storage, GPU servers, core and access switches, firewalls, WAN routers,
  a spares rack with a shelf — each unit at its units; rear-door coolers as 0U; space reserved for the fifth
  hypervisor host a ticket asks for. Every rack of the data hall, the network room and the backup room has a PDU A
  and a PDU B (0U, rear) fed by UPS-01 and UPS-02 and feeding each unit.
- **Medium linac:** eight racks — magnet supplies (3U each) and the Moxa in A12-1/A12-2, vacuum controllers and
  PLC in A12-3, controls in CTRL, Kubernetes nodes, storage, core network and the IOC host in the server room, the
  backup rack in the external data centre — with PDUs fed by the server-room and controls UPS. The Kubernetes
  cluster is its nodes (`part of`), not a box in a rack.

Their floor plans' drawings show the building only (rooms, room numbers, beam axis, north, title): the records
are drawn over them by layer (docs/plan-layers.md). A unit in a rack is not a point of its own: its rack is.

The drawings are a room schedule, made by `backend/scripts/demo_plan_drawing.py`: the building's double outer wall,
a column grid every 5 m with axis bubbles (numbers along the top, letters up the side), each room filled in the
colour of what it is for (bunker, RF, laser, control, electrical, IT, plant, circulation, offices, stores), its name
in a label sized and wrapped to fit inside it, its number and area (1 m = 10 px), a door, hatched shielding around
a bunker or tunnel, and a title block with north and a 10 m scale bar. The geometry does not move — same size, same
rooms, same beam axis — so every point, outline and rack placed on a plan stays where it was. The model is kept in
the drawing's `<desc>`, so drawing it again changes nothing. The plans are synthetic: no real building is drawn.

They are made by `backend/scripts/rack_demos.py` from the previous bundle and a layout file
(`backend/scripts/demo_rack_layouts/<demo>.json`), through the application, in an empty database:

    PYTHONPATH=/app python scripts/rack_demos.py <bundle dir> scripts/demo_rack_layouts/<demo>.json <output dir>

Identifiers, relations, tickets, documents and attachments of the previous bundle are all kept; the script adds the
PDUs, their relations, the mountings, and the tour's steps for the plan by layer, a rack and the tunnel, and redraws
the plans. A PDU feeds the rack's units, never itself or its twin (an earlier run made those `powers` relations; they
are taken out).

## Updating an imported demo

A bundle is imported as a clone into a new workspace; importing it again into the same workspace is refused (docs/
workspace-bundle.md). To bring a demo that was imported before — and may have been worked on since — up to the
new rack positions **without losing anything**:

    # inside the API container
    PYTHONPATH=/app python scripts/apply_rack_layout.py <workspace id> scripts/demo_rack_layouts/<demo>.json --dry-run
    PYTHONPATH=/app python scripts/apply_rack_layout.py <workspace id> scripts/demo_rack_layouts/<demo>.json

- The layout names records by the bundle's identifiers; in a clone where they were renamed
  (`uuid5(<workspace>, <identifier>)`), the renamed ones are found too.
- Only what differs changes: a unit already where the layout says is left alone, one elsewhere is moved (with its
  history), shelves and reserved spaces are matched by their label. Running it twice changes nothing the second time.
- Nothing is deleted or rewritten: records, relations, tickets, documents, attachments, photos, comments and the
  positions people set on plans stay. A unit mounted by the layout stops being a point of its own on a plan.
- A rack whose result would overlap or stick out is refused whole and reported; the others are applied.
- What the layout names but the workspace lacks is listed as *not found*: records the new bundle adds (the PDUs)
  and the cleaned drawings come only with the new bundle. To have them, import the new bundle into a new workspace
  and move people to it; positions set by hand in the old one can be read from its racks' history.
