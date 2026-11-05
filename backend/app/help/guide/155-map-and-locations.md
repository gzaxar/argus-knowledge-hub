---
title: Map and locations
summary: Where equipment and places are: positions, routes (cables, pipes, beamlines) and outlines (buildings, halls, rooms, zones, with heights a volume) and their history, what lies inside or crosses an area, the map, searching near a point, reporting a position from the phone, reviewing what the field saw, and importing locations from a file.
keywords: [north, north arrow, compass, heading, facing, orientation, turn with me, calibrate, declination, site, sites, laboratory, facility, facilities, LNF, shared places, not shared with the facilities, withhold, transfer preview, reconciliation, indoors, indoor, floor, floors, level, storey, floor plan, plan, room, hall, building, place on the plan, control points, georeference, residual, dxf plan, pdf plan,  line, cable route, pipe route, outline, polygon, area, footprint, building outline, hall, zone, volume, height, inside, crossing, along, draw, map, gis, location, locations, coordinates, latitude, longitude, gps, position, where is, near me, nearby, distance, radius, review, observation, import locations, csv, geojson, wgs84, layer, place]
order: 155
---

Equipment and places can have a **location** on the earth: latitude and longitude in WGS 84 (the GPS system),
with how accurate it is. Only types their package places on the map have one: **equipment** (every type
under Asset, on the *Equipment* layer) and **places** (buildings, halls, racks, stores, on the *Places* layer),
from Core objects; the electrical, hydraulic and HVAC packages show their equipment on layers of their own. A location is where a unit physically is; what it is connected to is the
knowledge graph's, and the two are kept apart.

## A record's location

A record placed on the map can have three kinds of location, each with its own history:

- a **position** — a point: where a unit is;
- a **route** — a line: where a cable, a pipe or a beamline runs;
- an **outline** — an area: a building, hall, room or zone. Give it the heights it spans (bottom and top, in
  metres, e.g. a room's floor and ceiling, a shielding block's bottom and top) and it is a **volume**.

On an equipment or place page, **Location** shows them on a small map, with the position's accuracy, a route's
length, an outline's area and heights, where each came from (set by hand, from the field, imported) and who
confirmed it.

- **Set its position** / **Move it**: click the map, or type the coordinates, and **Save**.
- **Draw its route** / **Draw its outline**: click the map point by point (an outline closes by itself), **undo
  last point** or **start again**, then **Save** — or paste the GeoJSON of a survey or a GIS export. A shape is
  checked before it is kept: a line needs two different points, an area three corners, and an area whose edges
  cross each other is refused, saying where.
- The previous one is kept under *Earlier*, with the dates it was valid, and the change is in the record's
  History. **remove route** / **remove outline** takes one away.
- Who may see the record sees its location, unless its type restricts the location from them.

## What a shape says about the others

Under the small map, ARGUS lists what the record's location says about the records you may see:

- **It is in** — the outlines its position, route or outline lies in: the hall, the building, a radiation or
  access zone;
- **Inside it** — for an outline, the records positioned inside it, and the outlines within it (rooms in a hall);
- **Crossing it** — the routes that cross its outline or its route (the cables through a hall or a zone);
- **Along its route** — for a route, the records positioned within 5 m of it, with their distance.

Heights are shown with an outline; what is inside is decided on the map (in plan), not by height.

## Indoors: floors, plans and rooms

GPS is weak indoors, and most laboratory equipment is indoors: there, a record is placed by **the room it is in**
and, when there is one, **a point on a floor plan**.

On a place's page (a building, a hall, a room), **Indoors**:

- **Floors** — add the place's floors: a name ("Ground floor", "-1"), their order (0 the ground floor, 1 the
  first, -1 below) and, if known, the height they are at and their own height.
- **Floor plans** — **Add a plan** for the whole place or one floor: an image (PNG, JPEG…), an SVG, a **PDF**
  (its first page) or a **DXF/DWG** drawing. **show** opens it with the records placed on it.
- **Place on the map** — click a point you can recognise on the plan (a corner, a column), then the same place
  on the map; repeat. Two points keep the plan's shape; three or more fit it and say how far off each point is
  (in metres): a point far off is one clicked in the wrong place — remove it and click again. Placed, the plan
  shows on the map, for its floor, and has a **north**: an arrow on the plan shows where true north is on the
  drawing (a check that the plan was placed the right way round).
- **Placed here** — the records placed in this place.

On any record's page, **Indoors → Place it inside**: search the place it is in (a room, a hall), optionally choose
a plan (the place's, or that of a place it is in — a room's plan is usually its building's) and click where it is.
A point on a plan placed on the map gives the record its **position** too (*from the plan*, as accurate as the
plan's fit). The record then says **which is in** — its room, the hall the room is in, the building — and the
place lists it; the record's *It is in* and the place's *Inside it* include them.

### Which way am I facing (the phone)

On the phone, a plan placed on the map shows a **dial**: the red arrow is true north on the drawing, the blue one
the way the top of the phone points, by its compass. **Turn with me** turns the plan so the way you face is up, as
a car's navigator does. Below the plan the compass says how sure it is (*±5°*); when it is unsure it asks to be
calibrated — wave the phone in a figure of eight. Near magnets, power supplies, cable trays and steel a phone's
compass can be off by tens of degrees: trust the plan and the labels around you over the arrow there. The phone
corrects magnetic north to true north itself (about 3–4° in Italy). Where you are on the plan is not known yet:
the dial says which way you face, not the way to a unit.

A record placed indoors is not disturbed by a vague GPS fix: one less precise than 10 m is **noted**, not sent to
review. Place it on its plan instead.

## A laboratory's places, shared with its facilities (sites)

A laboratory such as LNF hosts several facilities (SPARC, BTF, DAΦNE…), each with its own workspace. The places —
buildings, halls, rooms, their floors and plans — are the laboratory's, drawn and kept once. Its workspace is a
**site**, and each facility's workspace is **at** it.

**Setting it up (administrators).** On *Administration › Workspaces*, the **Site** column: *Make it a site* on the
laboratory's workspace, then choose *at LNF* on each facility's. A site is at no site, the catalogue is neither,
and a site cannot stop being one while facilities are at it. Taking a facility away from its site first lists
the placements of its equipment on the site's places that would end.

**What a facility gets.** From SPARC's workspace — its asset list shows *This workspace + LNF's places* by
default — LNF's places — every record of type Location or below it
(Building, Area, Rack…) — appear in lists, search, the map and the *Place it inside* search, with their floors,
plans and their position on the map; nothing else of LNF's does, and nothing of BTF's. SPARC places **its own**
equipment in an LNF room and on an LNF plan: the equipment stays SPARC's, the place and the plan stay LNF's —
only LNF's people change them.

**Who sees what on a shared plan.** A plan shows each record placed on it only to those who could see that record:
SPARC's people see SPARC's equipment (and LNF's places), not BTF's, unless they may also read BTF; a restricted
record stays hidden from those not given its class.

**Not shared with the facilities.** On a site's place, **Indoors › Shared with the facilities** says who sees it.
*Stop sharing it* withholds the place **and every place inside it**, with their floors and plans — first listing,
facility by facility, the equipment placed there. Those placements end: each record keeps the position the plan
gave it on the map, and its history says why. *Share it again* brings the places back; the placements are made
again by hand.

**Moving a place to the laboratory.** A record's *Copy/Move…* is previewed first: the report lists the records
going, their floors and plans (whether their files are there and their fit kept), the placements carried or
ending, the equipment of other workspaces placed in them, and every record naming them — whether it would still
reach them, and whether it would if they stopped being global. A **move** keeps the records' ids and keys, so
references to them hold; it drops a relation to a record left behind (the report names it). A record whose type
is its old workspace's own takes the new workspace's type of the same name (the report says which); with none,
the transfer is refused — transfer the type too. A record moved before this rule, whose type the workspace
cannot use, has its type chosen again on **Edit** (the same-named type is suggested). A **copy** makes new
records with copies of the floors and plans, placed where the originals were.

## The map

**Assets → Map** shows the records with a location, coloured by layer: points, routes as lines and outlines as
areas (under the points, so every point can be clicked). Narrow it to **types** (a type includes
the types under it), **workspaces** you can read, and **status**. A marker opens its record (in its own
workspace). **Near a point**: choose a distance and *of the map's centre* to list what is within it, nearest
first — a route or an outline by its nearest part (inside an outline is 0 m). **Indoors** chooses a floor: the
floor plans placed on the map in view are laid on it (the same floor of every building together). The map shows exactly what a list would show you: nothing restricted, nothing from a workspace you
cannot open.

## Reporting a position from the phone

Someone who may edit the record sets its position from its page in the app:

- **Set position here** takes where the phone is, with its GPS accuracy, once you have confirmed it;
- **Choose on the map** moves the map (or takes a tap) until the crosshair is on the place, then **Use this point**.

The position takes effect at once, and the one it had stays in the history, with who set it. A record pinned on a
floor plan is moved on the plan instead, since its position comes from there; and one in a room is not moved by a
GPS fix less precise than 10 m (**Choose on the map** or a plan is the way there).

Anyone can say where they see a record. **I'm next to it** sends where the phone is, with its GPS accuracy. It never
moves the record:

- close to the approved location (within 15 m plus both accuracies), it is noted as **consistent**;
- elsewhere — or when the record has no location yet — it goes to **review**, and its followers are told.

**Near me** (menu) lists what has a location around the phone, within 50 m, 200 m or 1 km. **Map** (menu)
shows what has a location around — positions as dots, routes as lines, outlines as areas; a tap opens the record;
the button centres it on the phone. On an equipment page, a small map shows its position, route and outline, and
**Open the map here**.

Indoors, on an equipment page: **In Room 12, Ground floor** and the places it is in; **Show on the plan** opens
the plan with its pin, and a tap there (asked first) places it at that point. **Place it on a plan** offers the
plans of its room and of the places the room is in (or, with only a position, those around it; for someone who may
edit a record with no location yet, those around the phone).

## Review

The map's side panel, the equipment page, and the app's **Locations to review** list the positions the field
saw that disagree. **Accept** makes one the approved location (the previous kept in the history, the reviewer
recorded); **reject** leaves the location as it was. Nothing moves without a person deciding.

## Import locations

**Map → Import locations**: a CSV with a header (`key` or `label` or `serial`, `latitude`/`lat`,
`longitude`/`lon`, `accuracy_m`, optionally `observed_at`), or GeoJSON whose features' properties name the
record: points (positions), lines (routes) and polygons (outlines; `base_m` and `top_m` for their heights).
**Preview** checks every row — coordinates in range (a latitude above 90 is refused, 0, 0 too), the record
found as a scan finds it, its type placed on the map — and says what each row would do. **Apply**:

- a record with no location gets the imported one, with the file and the row it came from;
- a record that has one is **never overwritten**: the same position is noted as consistent, a different one
  goes to review; the same route or outline is noted as consistent, a different one is refused (change it on
  the record).

## What is not here yet

Coordinates other than WGS 84 (a site grid, a survey frame, a position *s* along a beamline) are for a later
release; heights are kept with floors and outlines, but what is inside is decided in plan.
