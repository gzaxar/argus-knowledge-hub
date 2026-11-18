"""Allow a navigation folder to be placed under a document.

Revision ID: f5a7c9e1b3d6
Revises: e4f6a8b0c2d5
"""
from alembic import op
import sqlalchemy as sa

revision = "f5a7c9e1b3d6"
down_revision = "e4f6a8b0c2d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_folders", sa.Column("parent_document_uid", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_document_folders_parent_document_uid", "document_folders", "documents",
        ["parent_document_uid"], ["uid"], ondelete="SET NULL",
    )
    op.create_index("ix_document_folders_parent_document_uid", "document_folders", ["parent_document_uid"])
    op.create_check_constraint(
        "document_folder_one_parent", "document_folders",
        "parent_uid IS NULL OR parent_document_uid IS NULL",
    )


def downgrade() -> None:
    # Folders formerly under documents become root folders; no content is deleted.
    op.drop_constraint("document_folder_one_parent", "document_folders", type_="check")
    op.drop_index("ix_document_folders_parent_document_uid", table_name="document_folders")
    op.drop_constraint("fk_document_folders_parent_document_uid", "document_folders", type_="foreignkey")
    op.drop_column("document_folders", "parent_document_uid")
