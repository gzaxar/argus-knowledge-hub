"""Activities and recurring activity series

Revision ID: f6b8d0e2a4c5
Revises: e5a7c9d1f3b4
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f6b8d0e2a4c5"
down_revision = "e5a7c9d1f3b4"
branch_labels = None
depends_on = None


def _common(*extra):
    return [
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assignee_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *extra,
        sa.Column("asset_uid", sa.String(), nullable=True),
        sa.Column("ticket_uid", sa.String(), nullable=True),
        sa.Column("document_uid", sa.String(), nullable=True),
        sa.Column("provenance", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    ]


def upgrade() -> None:
    op.create_table(
        "activity_series",
        sa.Column("uid", sa.String(), primary_key=True),
        *_common(
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("visibility", sa.String(), nullable=False, server_default="workspace"),
            sa.Column("rrule", sa.String(), nullable=False),
            sa.Column("first_local", sa.String(), nullable=False),
            sa.Column("timezone", sa.String(), nullable=False),
            sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("duration_minutes", sa.Integer(), nullable=True),
            sa.Column("continued_by_uid", sa.String(), nullable=True),
            sa.Column("ended", sa.Boolean(), nullable=False, server_default=sa.false()),
        ),
    )
    for col in ("workspace_id", "owner_user_id", "assignee_user_id", "asset_uid", "ticket_uid"):
        op.create_index(f"ix_activity_series_{col}", "activity_series", [col])
    op.create_table(
        "activities",
        sa.Column("uid", sa.String(), primary_key=True),
        sa.Column("series_uid", sa.String(), sa.ForeignKey("activity_series.uid", ondelete="CASCADE"), nullable=True),
        sa.Column("occurrence_key", sa.String(), nullable=True),
        *_common(
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("visibility", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="planned"),
            sa.Column("timezone", sa.String(), nullable=False, server_default="UTC"),
            sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("planned_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("planned_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("actual_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("actual_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
        ),
        sa.UniqueConstraint("series_uid", "occurrence_key", name="uq_activity_occurrence"),
    )
    for col in ("workspace_id", "series_uid", "owner_user_id", "assignee_user_id", "status", "planned_start",
                "actual_start", "actual_end", "asset_uid", "ticket_uid"):
        op.create_index(f"ix_activities_{col}", "activities", [col])


def downgrade() -> None:
    op.drop_table("activities")
    op.drop_table("activity_series")
