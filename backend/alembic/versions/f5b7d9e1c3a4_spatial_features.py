"""The spatial model: approved locations of records and the field observations proposing them (PostGIS).

Needs the database image with PostGIS (deploy/postgres): rehearsed and switched to before this release.

Revision ID: f5b7d9e1c3a4
Revises: e4a6c8e0b2d3
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f5b7d9e1c3a4"
down_revision = "e4a6c8e0b2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not bind.execute(sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'postgis'")).scalar():
        raise RuntimeError("This database has no PostGIS: the spatial model needs the database image with it "
                           "(deploy/postgres, docs/operations.md \"Rehearsing the database image\").")
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "spatial_features",
        sa.Column("uid", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_kind", sa.String(), nullable=False, server_default="asset"),
        sa.Column("subject_uid", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="position"),
        sa.Column("geometry", sa.Text().with_variant(sa.Text(), "postgresql"), nullable=False),
        sa.Column("geometry_type", sa.String(), nullable=False),
        sa.Column("crs", sa.String(), nullable=False, server_default="EPSG:4326"),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(), nullable=False, server_default="confirmed"),
        sa.Column("confirmed_by", sa.String(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer", sa.String(), nullable=True),
        sa.Column("observation_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("provenance", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "location_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_kind", sa.String(), nullable=False, server_default="asset"),
        sa.Column("subject_uid", sa.String(), nullable=False),
        sa.Column("geometry", sa.Text(), nullable=False),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_by", sa.String(), nullable=True),
        sa.Column("device_id", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="field"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("feature_uid", sa.String(), nullable=True),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The geometry columns as PostGIS types (any geometry, WGS 84), with spatial indexes.
    for table in ("spatial_features", "location_observations"):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN geometry TYPE geometry(Geometry, 4326) "
                   f"USING ST_SetSRID(ST_GeomFromText(geometry), 4326)")
        op.execute(f"CREATE INDEX ix_{table}_geometry ON {table} USING gist (geometry)")
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])
        op.create_index(f"ix_{table}_subject_uid", table, ["subject_uid"])
    # One approved position per record at a time.
    op.execute("CREATE UNIQUE INDEX ux_spatial_features_current ON spatial_features (subject_kind, subject_uid, role) "
               "WHERE state = 'confirmed'")
    op.create_index("ix_location_observations_status", "location_observations", ["workspace_id", "status"])


def downgrade() -> None:
    op.drop_table("location_observations")
    op.drop_table("spatial_features")
    # The extension stays: other data may use it, and dropping it is the database owner's decision.
