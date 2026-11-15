# Draw a plan

A place with no drawing to upload gets its plan drawn by ARGUS from a layout in metres: the building's width and
depth, and its rooms. The drawing is the one the demos use (`backend/app/services/plan_drawing.py`): a room schedule
at 1 m = 10 px — double outer wall, a column grid every 5 m with axis bubbles, each room in the colour of what it is
for, its name in a label that fits inside it, its number and area, a door, hatched shielding around a bunker or
tunnel, and a title block with north and a 10 m scale bar.

A room's label goes where nothing ARGUS draws over the plan covers it (`plan_layers.drawn_over`: every point — a
rack for what it holds — and every route, in the plan's pixels). It is high in the room and centred when that spot
is free. Otherwise it goes to the free spot nearest to there; if no spot is free, it wraps a word to a line or gets
smaller. A point on the name counts far more than one at its edge or on the number and area. In a room too full for
any free spot (a 7 m × 8 m room with ten racks and devices), the label is as little covered as can be. The points
are not kept in the drawing's model: a plan drawn again places its labels for what is on it then.

## The layout

```json
{"title": "Hall B — ground floor", "width_m": 40, "depth_m": 20, "north": true,
 "rooms": [{"name": "Rack room", "number": "B0.01", "record": "<room uid>", "x": 0, "y": 0, "w": 12, "d": 8}]}
```

`x`, `y` are metres from the building's top-left corner, `w`, `d` the room's width and depth. A building is 2–400 m
a side, rooms are at least 1 m, inside the walls and do not overlap; at most 200. `record` is optional: the room record
the room stands for.

On the drawing the building's corner is at (20, 20) px, the title block takes 64 px under it: a 40 × 20 m building is
a 440 × 304 px plan. The layout is kept in the drawing's `<desc>` (with the marker `argus-demo-plan/2`), so the plan
opens again as its layout and drawing it again changes nothing.

## The API — routes in `routers/indoor.py`

- `POST /v1/plans/drawing-preview` `{layout}` — the SVG it would be; nothing saved (read permission).
- `POST /v1/assets/{place}/plans/drawn` `{layout, name?, level_uid?, place_rooms=true}` — a new plan of the place
  (`source_kind` `drawn`). With `place_rooms`, each room's record is placed at the room's centre on the plan, in the
  place, on the plan's floor; a record already there is left alone. The answer says how many were placed.
- `GET /v1/plans/{uid}/layout` — `{editable, layout}`; `editable` is false for an uploaded drawing.
- `PUT /v1/plans/{uid}/layout` `{layout, place_rooms=true}` — the plan drawn again. The building keeps its corner,
  so records placed on the plan keep their points; a layout that would leave one of them outside the plan is
  refused. The drawing goes to a new file (a demo's drawing can be shared with an attachment, which keeps its own).
  The demos' plans open this way too.

## In the web app

Indoors → Floor plans → **draw a plan**, and **edit drawing** on an SVG plan (`components/PlanDrawer.tsx`): the
server's preview, with a transparent layer over it to drag rooms (new ones on empty space, a room to move it; half a
metre a step), the selected room's name, number, position, size and room record, the room records of the place to
add, and whether to place them.
