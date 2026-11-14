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
