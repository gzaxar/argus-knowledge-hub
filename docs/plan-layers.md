# Floor plans by layer, and the tunnel

Two views of where things are: a floor plan with the records drawn over it by layer, and the tunnel along a beam
path with the hardware installed at each element.

## The plan's layers — `GET /v1/plans/{uid}/layers`

The uploaded drawing is the **base**: walls, rooms, doors. ARGUS never writes on it. The records are drawn over it
(`app/services/plan_layers.py`):

| layer | what | on at first |
|---|---|---|
| `places` | room and technical-room outlines; doors and gates | yes |
| `beamline` | beamline components, waveguides, shielding, survey points | yes |
| `racks` | one point per rack, with how many units it holds | yes |
| `fixed` | main fixed plant (`FIXED_TYPES`: klystrons, modulators, chillers, switchboards, UPS, AHUs…) | yes |
| `devices` | every other record placed on the plan | no |
| `paths` | routes crossing the plan (cables, pipes, fibres) | no |
| `zones` | outlines whose type is a zone or an area (radiation, fire, access) | no |
| `tickets` | open tickets (not resolved or closed) on what is shown | no |
| `activities` | activities planned or in progress, from yesterday to 30 days ahead | no |

- A unit **in a rack** — mounted (`rack_mountings`), `located in` a rack, or placed inside one — is not a point of
  its own; `held` maps it to its rack and its tickets and activities count on the rack.
- Outlines and routes are geographic: they are turned into the plan's pixels with the inverse of the plan's
  transform, so they appear only on a plan placed on the map. Left out: the plan's own place and the places it is
  in, outlines covering the whole plan, outlines of another floor (`indoor_placements.level_uid`), and records of
  other workspaces that are not reachable from the plan's.
- On a drawing ARGUS made (a demo's, or "Draw a plan"), `building` gives the building's walls `[x, y, w, h]` in px.
  The web clips routes to them, so a cable from another building is drawn from the wall it comes through, not
  across the title block or the ground around. On an uploaded drawing, routes are clipped to the picture. A route
  coming through a wall is named there (`routeEnds` in `PlanLayersPage.tsx`) and a dot marks the end inside.
- The web offers only the layers that have something on this plan: an IT building has no beamline chip.
- Everything is filtered for the viewer as the plan itself is (`routers/indoor._viewer`); tickets need ticket read
  permission in their workspace; activities follow the activity rules (`services/activities.sees`).

The web page is `/plans/{uid}` (`?focus=uid,uid` marks records looked for). A rack opens `/racks/{uid}`; with
`?unit=` the rack editor selects that unit, or lists it under **In this rack, no position yet** when it has no
units yet (`GET /v1/racks/{uid}` returns `unplaced` and the rack's `plan`).

## The tunnel — `GET /v1/beam-paths/{uid}/tunnel`

The path's elements in order of `s` (from the dataset, the design optics by default), and for each the hardware
installed there now — confirmed installations of the ledger and confirmed beam–asset bindings — with:

- its room (the nearest container that is not a rack, through its rack when it is in one),
- its rack, its point on a floor plan (`indoor.spot`: its own, or its rack's or room's),
- what `powers` it or the element, with that supply's rack and room,
- its open tickets.

`rooms` are bands along `s`: consecutive elements whose hardware is in the same room. The web page is
`/tunnel/{path}`, linked from the beam model page.

## The 3D view — `GET /v1/plans/{uid}/scene`, page `/plans/{uid}/3d`

A simplified 3D view of a floor plan (three.js, loaded only when the page is opened): the drawing on the floor,
rooms as glass walls 2.8 m high, zones tinted on the floor, cables and pipes as lines, racks as 2 m cabinets with
their units at their units (U1 at 0.1 m, 44.45 mm a unit; front units towards the front, 0U strips at the rear),
beamline components at 1.2 m, fixed plant as 1.6 m blocks, other devices as small cubes. It opens, and **Reset
view** returns, with the whole floor in view from the south, about 55° above it, whatever the shape of the window.

`scene` is `layers` plus `metres_per_px` (from the plan's placement on the map; 0.1 m when it is not placed,
`scale_known: false`), `units` (each unit held in a rack on the plan, with its rack, units and face) and `relations`
between everything the plan shows. Relations that say where or what a record is (`located in`, `port of`,
`part of`, `installed at`…: `NOT_DRAWN`) are not drawn: placing shows them.

On the page, relations are arcs coloured by type, higher the farther apart their ends; they can be limited to some
types and, by default, to those of the record selected. A click selects (a room only when nothing else is under
the pointer); the panel says each relation in words and opens the rack, or the unit in its rack.

## The demos' cables and pipes

The demo routes were drawn on the map as a few straight strokes. Inside a building those crossed rooms diagonally
and stopped anywhere, so `scripts/rack_demos.py` redraws the part inside each building with
`scripts/demo_routes_inside.py`: from where the route comes through the wall, a square run along the free space
between rooms (a corridor, the gap between two rows of rooms) to well inside the room its end is in. Outside the
building the route is kept as it was; a route through a corner goes in through the side wall. Running it again
changes nothing (`tests/test_demo_routes_inside.py`).
