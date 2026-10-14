"""Periodic Git exports: a published export repeated at an interval.

Revision ID: a1c3e5f7b9d2
Revises: f5b7d9e1c3a4
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a1c3e5f7b9d2"
down_revision = "f5b7d9e1c3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portability_schedules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_export_id", sa.String(), nullable=False, index=True),
        sa.Column("chain", sa.String(), nullable=False, server_default="incremental"),
        sa.Column("every_minutes", sa.Integer(), nullable=False),
        sa.Column("skip_unchanged", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true", index=True),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("workspaces", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("destination", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("decisions", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("running_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outcome", sa.String(), nullable=True),
        sa.Column("last_message", sa.String(), nullable=True),
        sa.Column("last_export_id", sa.String(), nullable=True),
        sa.Column("last_published_export_id", sa.String(), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("portability_schedules")
