"""activities in more than one workspace

Revision ID: a7c9e1f3b5d6
Revises: f6b8d0e2a4c5
"""
import sqlalchemy as sa
from alembic import op

revision = "a7c9e1f3b5d6"
down_revision = "f6b8d0e2a4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_workspaces",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_uid", sa.String(), sa.ForeignKey("activities.uid", ondelete="CASCADE"), nullable=True),
        sa.Column("series_uid", sa.String(), sa.ForeignKey("activity_series.uid", ondelete="CASCADE"), nullable=True),
        sa.UniqueConstraint("workspace_id", "activity_uid", name="uq_activity_workspace"),
        sa.UniqueConstraint("workspace_id", "series_uid", name="uq_activity_series_workspace"),
        sa.CheckConstraint("(activity_uid IS NULL) <> (series_uid IS NULL)", name="ck_activity_workspace_one"),
    )
    op.create_index("ix_activity_workspaces_workspace_id", "activity_workspaces", ["workspace_id"])
    op.create_index("ix_activity_workspaces_activity_uid", "activity_workspaces", ["activity_uid"])
    op.create_index("ix_activity_workspaces_series_uid", "activity_workspaces", ["series_uid"])


def downgrade() -> None:
    op.drop_table("activity_workspaces")
