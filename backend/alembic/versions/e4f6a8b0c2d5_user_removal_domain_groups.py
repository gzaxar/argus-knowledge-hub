"""People removed from ARGUS, whether their e-mail address is verified, and groups by e-mail domain.

Revision ID: e4f6a8b0c2d5
Revises: d3e5f7a9b2c4
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "e4f6a8b0c2d5"
down_revision = "d3e5f7a9b2c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified", sa.Boolean(), nullable=True))
    op.add_column("users", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("removed_by", sa.String(), nullable=True))
    op.add_column("groups", sa.Column("email_domains", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("groups", "email_domains")
    op.drop_column("users", "removed_by")
    op.drop_column("users", "removed_at")
    op.drop_column("users", "email_verified")
