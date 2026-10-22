"""Usage statistics and Ask ARGUS feedback

Revision ID: c3e5a7b9d1f2
Revises: b2d4f6a8c0e1
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c3e5a7b9d1f2"
down_revision = "b2d4f6a8c0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_requests",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("client", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), primary_key=True),
        sa.Column("function", sa.String(), primary_key=True),
        sa.Column("count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("errors", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("ms_total", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_table(
        "usage_presence",
        sa.Column("bucket", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("client", sa.String(), primary_key=True),
        sa.Column("person", sa.String(), primary_key=True),
    )
    op.create_table(
        "usage_llm",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("workspace_id", sa.String(), primary_key=True),
        sa.Column("model", sa.String(), primary_key=True),
        sa.Column("purpose", sa.String(), primary_key=True),
        sa.Column("calls", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("failures", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("estimated_calls", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("ms_total", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_table(
        "ask_feedback",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("rating", sa.String(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False, server_default=""),
        sa.Column("answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("argus_version", sa.String(), nullable=True),
        sa.Column("client", sa.String(), nullable=True),
        sa.Column("tools", postgresql.JSONB(), nullable=True),
        sa.Column("stopped", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("seconds", sa.Float(), nullable=True),
        sa.Column("ticket_uid", sa.String(), nullable=True),
    )
    op.create_index("ix_ask_feedback_created_at", "ask_feedback", ["created_at"])
    op.create_index("ix_ask_feedback_workspace_id", "ask_feedback", ["workspace_id"])
    op.add_column("ask_messages", sa.Column("model", sa.String(), nullable=True))
    op.add_column("ask_messages", sa.Column("rating", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("ask_messages", "rating")
    op.drop_column("ask_messages", "model")
    op.drop_table("ask_feedback")
    op.drop_table("usage_llm")
    op.drop_table("usage_presence")
    op.drop_table("usage_requests")
