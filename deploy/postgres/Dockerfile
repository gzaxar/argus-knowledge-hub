# The database image: the PostgreSQL 16 + pgvector image ARGUS has always run (Ask ARGUS's written-knowledge
# search), with PostGIS added for the spatial model. Same PostgreSQL major version and data directory format,
# so an existing data directory starts as it is; the PostGIS extension is created by a migration, not here.
# Built and pushed by .github/workflows/release.yml; rehearse before switching to it (tools/db-image-rehearsal).
FROM mirror.gcr.io/pgvector/pgvector:pg16-trixie

# The official image already has the PostgreSQL apt repository (apt.postgresql.org): PostGIS 3 built for 16.
# The server is upgraded with it: the repository's PostGIS is built against its latest PostgreSQL 16 minor, and a
# base image one minor behind cannot load it ("undefined symbol: heap_datum_check" with 16.15 and PostGIS 3.7).
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-16 postgresql-16-postgis-3 postgresql-16-postgis-3-scripts \
 && rm -rf /var/lib/apt/lists/*

LABEL org.opencontainers.image.title="argus-knowledge-hub-postgres" \
      org.opencontainers.image.description="PostgreSQL 16 with pgvector and PostGIS, for ARGUS Knowledge Hub" \
      org.opencontainers.image.source="https://github.com/infn-argus/argus-knowledge-hub"
