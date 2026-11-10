"""Document folders and one navigation placement per document.

Revision ID: a6d8e0f2b4c7
Revises: f8b0c2d4e6a1
"""
from alembic import op
import sqlalchemy as sa

revision = "a6d8e0f2b4c7"
down_revision = "f8b0c2d4e6a1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "document_folders",
        sa.Column("uid", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("parent_uid", sa.String(), sa.ForeignKey("document_folders.uid", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(trim(name)) > 0", name="document_folder_name_not_empty"),
    )
    op.create_index("ix_document_folders_workspace_id", "document_folders", ["workspace_id"])
    op.create_index("ix_document_folders_parent_uid", "document_folders", ["parent_uid"])
    op.create_table(
        "document_navigation_placements",
        sa.Column("document_uid", sa.String(), sa.ForeignKey("documents.uid", ondelete="CASCADE"), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("folder_uid", sa.String(), sa.ForeignKey("document_folders.uid", ondelete="CASCADE")),
        sa.Column("parent_document_uid", sa.String(), sa.ForeignKey("documents.uid", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("folder_uid IS NULL OR parent_document_uid IS NULL", name="document_placement_one_parent"),
        sa.CheckConstraint("parent_document_uid IS NULL OR document_uid <> parent_document_uid", name="document_placement_not_self"),
    )
    for col in ("workspace_id", "folder_uid", "parent_document_uid"):
        op.create_index(f"ix_document_navigation_placements_{col}", "document_navigation_placements", [col])


def downgrade():
    op.drop_table("document_navigation_placements")
    op.drop_table("document_folders")
