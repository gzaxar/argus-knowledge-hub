"""The definitions of each package version workspaces were given, for upgrades to compare against.

Revision ID: e4a6c8e0b2d3
Revises: d2f4a6c8e0b1
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e4a6c8e0b2d3"
down_revision = "d2f4a6c8e0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "package_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("package_id", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("checksum", sa.String(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("sections", postgresql.JSONB(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("package_id", "checksum"),
    )


def downgrade() -> None:
    op.drop_table("package_snapshots")
