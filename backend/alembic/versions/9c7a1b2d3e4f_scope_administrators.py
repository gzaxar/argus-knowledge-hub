"""Explicit administrators for groups and sites.

Revision ID: 9c7a1b2d3e4f
Revises: 230d8beb8731
"""
from alembic import op
import sqlalchemy as sa

revision = "9c7a1b2d3e4f"
down_revision = "230d8beb8731"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "group_administrators",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("group_uid", sa.String(), sa.ForeignKey("groups.uid", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("group_uid", "user_id"),
    )
    op.create_index("ix_group_administrators_group_uid", "group_administrators", ["group_uid"])
    op.create_index("ix_group_administrators_user_id", "group_administrators", ["user_id"])
    op.create_table(
        "site_administrators",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("site_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("site_id", "user_id"),
    )
    op.create_index("ix_site_administrators_site_id", "site_administrators", ["site_id"])
    op.create_index("ix_site_administrators_user_id", "site_administrators", ["user_id"])


def downgrade() -> None:
    op.drop_table("site_administrators")
    op.drop_table("group_administrators")
