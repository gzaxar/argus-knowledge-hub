"""Tickets have keys ({WS}-TCK-0042) from the workspace's Record keys pattern (docs: Record keys).

`issues.key`: unique across the installation, given when a ticket is created. Tickets made before have none until
an administrator fills them in (services/asset_keys.backfill_ticket_keys).

Revision ID: 230d8beb8731
Revises: b7d9f1a3c5e8
"""
import sqlalchemy as sa

from alembic import op

revision = "230d8beb8731"
down_revision = "b7d9f1a3c5e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("issues", sa.Column("key", sa.String(), nullable=True))
    op.create_index("ix_issues_key", "issues", ["key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_issues_key", table_name="issues")
    op.drop_column("issues", "key")
