"""A catalogue release is pinned from Administration, and a model made in ARGUS is proposed to Git.

`catalogue_pins`: a catalogue source moved to a newer release tag than the lock file ARGUS ships (read only while
newer). `catalogue_proposals`: a Product Model proposed as a pull request on the catalogue repository, until a
release carrying it is installed and links the record (docs/catalogue-collections.md §4).

Revision ID: b7d9f1a3c5e8
Revises: f8b0c2d4e6a1
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "b7d9f1a3c5e8"
down_revision = "f8b0c2d4e6a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalogue_pins",
        sa.Column("source_id", sa.String(), primary_key=True),
        sa.Column("ref", sa.String(), nullable=False),
        sa.Column("commit", sa.String(), nullable=False),
        sa.Column("previous_ref", sa.String(), nullable=True),
        sa.Column("previous_commit", sa.String(), nullable=True),
        sa.Column("pinned_by", sa.String(), nullable=False),
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "catalogue_proposals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("record_uid", sa.String(), sa.ForeignKey("assets.uid", ondelete="CASCADE"), nullable=False),
        sa.Column("catalogue_id", sa.String(), nullable=False),
        sa.Column("vendor_record_uid", sa.String(), sa.ForeignKey("assets.uid", ondelete="SET NULL"), nullable=True),
        sa.Column("vendor_id", sa.String(), nullable=True),
        sa.Column("collection_id", sa.String(), nullable=False),
        sa.Column("repository", sa.String(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("branch", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False, server_default="open"),
        sa.Column("files", JSONB(), nullable=False, server_default="{}"),
        sa.Column("proposed_by", sa.String(), nullable=False),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_catalogue_proposals_workspace_id", "catalogue_proposals", ["workspace_id"])
    op.create_index("ix_catalogue_proposals_record_uid", "catalogue_proposals", ["record_uid"])
    op.create_index("ix_catalogue_proposals_catalogue_id", "catalogue_proposals", ["catalogue_id"])


def downgrade() -> None:
    op.drop_table("catalogue_proposals")
    op.drop_table("catalogue_pins")
