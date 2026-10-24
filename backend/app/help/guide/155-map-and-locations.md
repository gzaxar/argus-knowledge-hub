---
title: Map and locations
summary: Where equipment and places are: positions, routes (cables, pipes, beamlines) and outlines (buildings, halls, rooms, zones, with heights a volume) and their history, what lies inside or crosses an area, the map, searching near a point, reporting a position from the phone, reviewing what the field saw, and importing locations from a file.
keywords: [route, line, cable route, pipe route, outline, polygon, area, footprint, building outline, hall, zone, volume, height, inside, crossing, along, draw, map, gis, location, locations, coordinates, latitude, longitude, gps, position, where is, near me, nearby, distance, radius, review, observation, import locations, csv, geojson, wgs84, layer, place]
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

## The map

**Assets → Map** shows the records with a location, coloured by layer: points, routes as lines and outlines as
areas (under the points, so every point can be clicked). Narrow it to **types** (a type includes
the types under it), **workspaces** you can read, and **status**. A marker opens its record (in its own
workspace). **Near a point**: choose a distance and *of the map's centre* to list what is within it, nearest
first — a route or an outline by its nearest part (inside an outline is 0 m). The map shows exactly what a list would show you: nothing restricted, nothing from a workspace you
cannot open.

## Reporting a position from the phone

On an equipment page in the app, **I'm next to it** sends where the phone is, with its GPS accuracy. It never
moves the record:

- close to the approved location (within 15 m plus both accuracies), it is noted as **consistent**;
- elsewhere — or when the record has no location yet — it goes to **review**, and its followers are told.

**Near me** (menu) lists what has a location around the phone, within 50 m, 200 m or 1 km.

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

Coordinates other than WGS 84 (a site grid, a survey frame, a position *s* along a beamline), floors and floor
plans, and placing equipment by room indoors are for later releases.
