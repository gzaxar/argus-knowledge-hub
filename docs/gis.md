# Basic GIS

Where records are on the earth, kept apart from what they are connected to (the knowledge graph).

## Model (backend/app/models/spatial.py, PostGIS)

- `spatial_features` — a record's **approved** location: `geometry` (PostGIS `geometry(Geometry, 4326)`,
  points in this release), `geometry_type`, `crs` (as given; stored in WGS 84), `source` (manual, field,
  import), `accuracy_m`, `observed_at`, validity (`valid_from`, `valid_until`), `state` (confirmed,
  superseded, removed), `confirmed_by`/`confirmed_at`, `reviewer`, `provenance`. One confirmed `position`
  per record (a partial unique index); `role` leaves room for routes, footprints and areas, and the geometry
  column takes lines and polygons, so they come without changing identifiers or the stored points.
- `location_observations` — what the field (or an import) saw: never the approved location by itself.
  `status`: consistent (within 15 m plus both accuracies), pending (review), accepted, rejected; the
  `distance_m` to the approved location at the time.

Which types have a location comes from the packages: `locatable: true` on a type (inherited down the
tree), `map_layer` naming one of the package's `map_layers`. accelerator 1.1.0 places Asset (equipment)
and Location (places).

## Access

A location is shown to whoever may see the record, unless the record's type restricts a `location`
attribute from them (the same field restriction as any attribute). The map and nearby search apply the
list rules: the workspaces the person may read, restricted records left out.

## API

`GET/PUT/DELETE /v1/assets/{uid}/location`, `POST /v1/assets/{uid}/location/observations`,
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

## Limits of this release

Points only; WGS 84 only; no routes, footprints, floor plans or spatial impact analysis — each needs its own
design and acceptance tests.
