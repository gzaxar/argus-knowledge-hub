"""What is mounted in a rack: unit, height and face, with its history (docs/rack-elevation.md).

Revision ID: b1c3d5e7f9a2
Revises: a5e7c9b1d3f2
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "b1c3d5e7f9a2"
down_revision = "a5e7c9b1d3f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rack_mountings",
        sa.Column("uid", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rack_uid", sa.String(), nullable=False),
        sa.Column("asset_uid", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False, server_default="device"),
        sa.Column("start_u", sa.Integer(), nullable=True),
        sa.Column("height_u", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("face", sa.String(), nullable=False, server_default="front"),
        sa.Column("shelf_uid", sa.String(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("evidence", JSONB(), nullable=True),
        sa.Column("state", sa.String(), nullable=False, server_default="confirmed"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_rack_mountings_workspace_id", "rack_mountings", ["workspace_id"])
    op.create_index("ix_rack_mountings_rack_uid", "rack_mountings", ["rack_uid"])
    op.create_index("ix_rack_mountings_asset_uid", "rack_mountings", ["asset_uid"])


def downgrade() -> None:
    op.drop_table("rack_mountings")
