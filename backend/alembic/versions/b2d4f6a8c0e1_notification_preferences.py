"""How each person wants notifications by e-mail.

Revision ID: b2d4f6a8c0e1
Revises: a1c3e5f7b9d2
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b2d4f6a8c0e1"
down_revision = "a1c3e5f7b9d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, server_default="instant"),
        sa.Column("muted", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("last_digest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("notification_preferences")
