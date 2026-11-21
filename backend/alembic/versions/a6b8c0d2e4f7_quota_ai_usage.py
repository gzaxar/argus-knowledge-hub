"""Quotas: language-model tokens per workspace and hour, for the 5-hour and weekly AI quotas (services/quotas.py).

Revision ID: a6b8c0d2e4f7
Revises: f5a7c9e1b3d6
"""
from alembic import op
import sqlalchemy as sa

revision = "a6b8c0d2e4f7"
down_revision = "f5a7c9e1b3d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quota_ai_usage",
        sa.Column("hour", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("workspace_id", sa.String(), primary_key=True),
        sa.Column("tokens", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_index("ix_quota_ai_usage_workspace_hour", "quota_ai_usage", ["workspace_id", "hour"])


def downgrade() -> None:
    op.drop_index("ix_quota_ai_usage_workspace_hour", table_name="quota_ai_usage")
    op.drop_table("quota_ai_usage")
