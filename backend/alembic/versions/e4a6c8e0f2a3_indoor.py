"""indoors: floors, floor plans and indoor placements

Revision ID: e4a6c8e0f2a3
Revises: d3f5a7c9e1b2
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e4a6c8e0f2a3"
down_revision = "d3f5a7c9e1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "place_levels",
        sa.Column("uid", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("place_uid", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("elevation_m", sa.Float(), nullable=True),
        sa.Column("height_m", sa.Float(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("place_uid", "name", name="uq_place_level_name"),
    )
    op.create_index("ix_place_levels_workspace_id", "place_levels", ["workspace_id"])
    op.create_index("ix_place_levels_place_uid", "place_levels", ["place_uid"])
    op.create_table(
        "floor_plans",
        sa.Column("uid", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("place_uid", sa.String(), nullable=False),
        sa.Column("level_uid", sa.String(), sa.ForeignKey("place_levels.uid", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("width_px", sa.Float(), nullable=False),
        sa.Column("height_px", sa.Float(), nullable=False),
        sa.Column("source_filename", sa.String(), nullable=True),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("source_path", sa.String(), nullable=True),
        sa.Column("control_points", postgresql.JSONB(), nullable=True),
        sa.Column("transform", postgresql.JSONB(), nullable=True),
        sa.Column("residual_m", sa.Float(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_floor_plans_workspace_id", "floor_plans", ["workspace_id"])
    op.create_index("ix_floor_plans_place_uid", "floor_plans", ["place_uid"])
    op.create_index("ix_floor_plans_level_uid", "floor_plans", ["level_uid"])
    op.create_table(
        "indoor_placements",
        sa.Column("uid", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_uid", sa.String(), nullable=False),
        sa.Column("place_uid", sa.String(), nullable=True),
        sa.Column("level_uid", sa.String(), sa.ForeignKey("place_levels.uid", ondelete="SET NULL"), nullable=True),
        sa.Column("plan_uid", sa.String(), sa.ForeignKey("floor_plans.uid", ondelete="SET NULL"), nullable=True),
        sa.Column("plan_x", sa.Float(), nullable=True),
        sa.Column("plan_y", sa.Float(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False, server_default="confirmed"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_indoor_placements_workspace_id", "indoor_placements", ["workspace_id"])
    op.create_index("ix_indoor_placements_asset_uid", "indoor_placements", ["asset_uid"])
    op.create_index("ix_indoor_placements_place_uid", "indoor_placements", ["place_uid"])
    op.create_index("ix_indoor_placements_plan_uid", "indoor_placements", ["plan_uid"])
    # One approved placement per record at a time.
    op.execute("CREATE UNIQUE INDEX ux_indoor_placements_current ON indoor_placements (asset_uid) "
               "WHERE state = 'confirmed'")


def downgrade() -> None:
    op.drop_table("indoor_placements")
    op.drop_table("floor_plans")
    op.drop_table("place_levels")
