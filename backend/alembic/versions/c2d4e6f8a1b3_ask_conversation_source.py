"""Where an Ask conversation comes from: the web's Ask ARGUS, or proposals sent by an assistant through MCP.

Revision ID: c2d4e6f8a1b3
Revises: b1c3d5e7f9a2
"""
import sqlalchemy as sa
from alembic import op

revision = "c2d4e6f8a1b3"
down_revision = "b1c3d5e7f9a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ask_conversations", sa.Column("source", sa.String(), nullable=False, server_default="ask"))
    op.add_column("ask_conversations", sa.Column("client", sa.String(), nullable=True))
    op.create_index("ix_ask_conversations_source", "ask_conversations", ["workspace_id", "source"])


def downgrade() -> None:
    op.drop_index("ix_ask_conversations_source", table_name="ask_conversations")
    op.drop_column("ask_conversations", "client")
    op.drop_column("ask_conversations", "source")
