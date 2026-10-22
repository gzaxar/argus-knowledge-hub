"""Storage occupancy per day, for the Statistics page

Revision ID: d4f6b8c0e2a3
Revises: c3e5a7b9d1f2
"""
import sqlalchemy as sa
from alembic import op

revision = "d4f6b8c0e2a3"
down_revision = "c3e5a7b9d1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_storage",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("area", sa.String(), primary_key=True),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("planned_bytes", sa.BigInteger(), nullable=True),
        sa.Column("disk_free_bytes", sa.BigInteger(), nullable=True),
        sa.Column("files", sa.BigInteger(), nullable=True),
        sa.Column("measured_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("usage_storage")
