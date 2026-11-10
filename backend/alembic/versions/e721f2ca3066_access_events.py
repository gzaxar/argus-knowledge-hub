"""The record of changes to access (issue #26): roles given and taken away, group members, administrators, sites.

Revision ID: e721f2ca3066
Revises: 5bdad2e85b24
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "e721f2ca3066"
down_revision = "5bdad2e85b24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "access_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=True),
        sa.Column("site_id", sa.String(), nullable=True),
        sa.Column("group_uid", sa.String(), nullable=True),
        sa.Column("subject_type", sa.String(), nullable=True),
        sa.Column("subject_id", sa.String(), nullable=True),
        sa.Column("role_id", sa.String(), nullable=True),
        sa.Column("detail", JSONB(), nullable=True),
    )
    for col in ("at", "kind", "workspace_id", "site_id", "group_uid"):
        op.create_index(f"ix_access_events_{col}", "access_events", [col])


def downgrade() -> None:
    op.drop_table("access_events")
