---
title: Map and locations
summary: Where equipment and places are: approved locations and their history, the map, searching an area or near a point, reporting a position from the phone, reviewing what the field saw, and importing locations from a file.
keywords: [map, gis, location, locations, coordinates, latitude, longitude, gps, position, where is, near me, nearby, distance, radius, review, observation, import locations, csv, geojson, wgs84, layer, place]
order: 155
---

Equipment and places can have a **location** on the earth: latitude and longitude in WGS 84 (the GPS system),
with how accurate it is. Only types their package places on the map have one — in the accelerator catalogue,
**equipment** (every type under Asset, on the *Equipment* layer) and **places** (buildings, halls, racks,
stores, on the *Places* layer). A location is where a unit physically is; what it is connected to is the
knowledge graph's, and the two are kept apart.

## A record's location

On an equipment page, **Location** shows its approved location on a small map, with its accuracy, where it
came from (set by hand, from the field, imported) and who confirmed it.

- **Set its location** / **Move it**: click the map, or type the coordinates, and **Save**. The previous one is
  kept under *Earlier locations*, with the dates it was valid, and the change is in the record's History.
- Who may see the record sees its location, unless its type restricts the location from them.

## The map

**Assets → Map** shows the records with a location, coloured by layer. Narrow it to **types** (a type includes
the types under it), **workspaces** you can read, and **status**. A marker opens its record (in its own
workspace). **Near a point**: choose a distance and *of the map's centre* to list what is within it, nearest
first. The map shows exactly what a list would show you: nothing restricted, nothing from a workspace you
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
`longitude`/`lon`, `accuracy_m`, optionally `observed_at`), or GeoJSON points whose properties name the record.
**Preview** checks every row — coordinates in range (a latitude above 90 is refused, 0, 0 too), the record
found as a scan finds it, its type placed on the map — and says what each row would do. **Apply**:

- a record with no location gets the imported one, with the file and the row it came from;
- a record that has one is **never overwritten**: the same position is noted as consistent, a different one
  goes to review.

## What is not here yet

Coordinates other than WGS 84 (a site grid), routes of pipes and cables, building outlines and floor plans,
and analysis by area are for later releases.
