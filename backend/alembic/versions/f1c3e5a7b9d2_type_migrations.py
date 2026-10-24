"""Type migrations: plans and their records.

Revision ID: f1c3e5a7b9d2
Revises: e4a6c8e0f2a3
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f1c3e5a7b9d2"
down_revision = "e4a6c8e0f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "type_migrations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("source_schema_uid", sa.String(), nullable=False, index=True),
        sa.Column("source", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("include_descendants", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("workspaces", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("target", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("mapping", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("inventory", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("verification", postgresql.JSONB(), nullable=True),
        sa.Column("log", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "type_migration_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("migration_id", sa.String(), sa.ForeignKey("type_migrations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("record_uid", sa.String(), nullable=False, index=True),
        sa.Column("workspace_id", sa.String(), nullable=False, index=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("batch", sa.Integer(), nullable=True),
        sa.Column("before", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("after", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("provenance", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("actor", sa.String(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("migration_id", "record_uid", name="uq_type_migration_item"),
    )


def downgrade() -> None:
    op.drop_table("type_migration_items")
    op.drop_table("type_migrations")
