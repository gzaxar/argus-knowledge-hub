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
