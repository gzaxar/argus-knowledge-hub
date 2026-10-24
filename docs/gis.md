# Basic GIS

Where records are on the earth, kept apart from what they are connected to (the knowledge graph).

## Model (backend/app/models/spatial.py, PostGIS)

- `spatial_features` — a record's **approved** location, by `role`: `position` (a point), `route` (a
  LineString or MultiLineString: a cable, a pipe, a beamline) or `outline` (a Polygon or MultiPolygon: a
  building, hall, room or zone; `base_m`/`top_m`, the heights it spans, make it a volume). `geometry` (PostGIS
  `geometry(Geometry, 4326)`), `geometry_type`, `crs` (as given; stored in WGS 84), `source` (manual, field,
  import), `accuracy_m`, `observed_at`, validity (`valid_from`, `valid_until`), `state` (confirmed,
  superseded, removed), `confirmed_by`/`confirmed_at`, `reviewer`, `provenance`. One confirmed feature per record and role (a partial unique
  index). A shape is checked before it is kept (services/spatial.shape): its kind fits its role, WGS 84, a line
  has two distinct positions, a ring is closed (for it) with four positions, at most 10 000 positions, and
  `ST_IsValidReason` finds it valid.
- `location_observations` — what the field (or an import) saw: never the approved location by itself.
  `status`: consistent (within 15 m plus both accuracies), pending (review), accepted, rejected; the
  `distance_m` to the approved location at the time.

Which types have a location comes from the packages: `locatable: true` on a type (inherited down the
tree), `map_layer` naming one of the packages' `map_layers` (the nearest up the tree wins). core-objects 1.1.0
places Asset (equipment) and Location (places); electrical, hydraulic and hvac give their equipment their own
layers. A workspace on core-objects 1.0.0 gets placement through an upgrade with no decision to take.

## Access

A location is shown to whoever may see the record, unless the record's type restricts a `location`
attribute from them (the same field restriction as any attribute). The map and nearby search apply the
list rules: the workspaces the person may read, restricted records left out.

## API

`GET/PUT/DELETE /v1/assets/{uid}/location`, `PUT/DELETE /v1/assets/{uid}/location/{route|outline}`,
`GET /v1/assets/{uid}/location/context?along_m=` (inside, crossing, along, within),
`POST /v1/assets/{uid}/location/observations`,
`GET /v1/location-reviews`, `POST /v1/location-reviews/{id}/accept|reject`,
`GET /v1/map/features?bbox=west,south,east,north&workspaces=&types=&status=` (GeoJSON),
`GET /v1/map/nearby?latitude&longitude&radius_m` (GeoJSON, nearest first, with `distance_m`),
`GET /v1/map/layers`, `POST /v1/locations/import?dry_run=` (CSV or GeoJSON).

## Map tiles

The web map draws OpenStreetMap tiles unless `VITE_MAP_TILES_URL` (and `VITE_MAP_TILES_ATTRIBUTION`) name
the installation's own tile server. Heavy use of the public OpenStreetMap servers is against their policy:
an installation with many users should run or rent a tile server.

## Database

PostGIS comes with the database image `argus-knowledge-hub-postgres` (deploy/postgres). The migration that
creates the extension refuses to run on a database without it. Switching an installation to the image is
rehearsed first (docs/operations.md, "Rehearsing the database image").

## Spatial questions (services/spatial.context)

For a record, among those the person may list: `inside` (positions `ST_Within` its outline, and outlines within
it), `crossing` (routes `ST_Intersects` its outline or route), `along` (positions within `along_m` of its route,
by geography distance), `within` (outlines containing its position, or intersecting its route or outline — not
those inside its own outline). Heights are carried, not used: the questions are in plan.

## Limits of this release

WGS 84 only; no floors, floor plans or indoor placement; no machine (s) or survey coordinates — the next steps.
Which types may have a route or an outline is not narrowed by the packages yet: any type placed on the map may.
