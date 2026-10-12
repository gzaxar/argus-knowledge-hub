"""Which template packages each workspace uses, and their history.

Revision ID: d2f4a6c8e0b1
Revises: c9e1a3b5d7f0
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d2f4a6c8e0b1"
down_revision = "c9e1a3b5d7f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_packages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("package_id", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("checksum", sa.String(), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=True),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("installed_by", sa.String(), nullable=True),
        sa.UniqueConstraint("workspace_id", "package_id"),
    )
    op.create_index("ix_workspace_packages_workspace_id", "workspace_packages", ["workspace_id"])
    op.create_table(
        "package_installations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("package_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("from_version", sa.String(), nullable=True),
        sa.Column("to_version", sa.String(), nullable=False),
        sa.Column("checksum", sa.String(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("actor", sa.String(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_package_installations_workspace_id", "package_installations", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_package_installations_workspace_id", table_name="package_installations")
    op.drop_table("package_installations")
    op.drop_index("ix_workspace_packages_workspace_id", table_name="workspace_packages")
    op.drop_table("workspace_packages")
