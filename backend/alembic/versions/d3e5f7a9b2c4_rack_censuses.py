"""Rack surveys from a phone: photos, what was read from them, and the person's decisions, until applied.

Revision ID: d3e5f7a9b2c4
Revises: c2d4e6f8a1b3
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "d3e5f7a9b2c4"
down_revision = "c2d4e6f8a1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rack_censuses",
        sa.Column("uid", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rack_uid", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False, server_default="open"),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_rack_censuses_workspace_id", "rack_censuses", ["workspace_id"])
    op.create_index("ix_rack_censuses_rack_uid", "rack_censuses", ["rack_uid"])
    op.create_index("ix_rack_censuses_state", "rack_censuses", ["state"])


def downgrade() -> None:
    op.drop_table("rack_censuses")
