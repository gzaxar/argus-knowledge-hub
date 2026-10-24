"""scheduled imports

Revision ID: c2e4a6b8d0f1
Revises: a7c9e1f3b5d6
"""
import sqlalchemy as sa
from alembic import op

revision = "c2e4a6b8d0f1"
down_revision = "a7c9e1f3b5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("import_configs", sa.Column("schedule_kind", sa.String(), nullable=False, server_default="off"))
    op.add_column("import_configs", sa.Column("schedule_every_hours", sa.Integer(), nullable=True))
    op.add_column("import_configs", sa.Column("schedule_time", sa.String(), nullable=True))
    op.add_column("import_configs", sa.Column("schedule_weekday", sa.Integer(), nullable=True))
    op.add_column("import_configs", sa.Column("schedule_timezone", sa.String(), nullable=True))
    op.add_column("import_configs", sa.Column("scheduled_by", sa.String(), nullable=True))
    op.add_column("import_configs", sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("import_configs", sa.Column("running_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("import_configs", sa.Column("schedule_failures", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("import_configs", sa.Column("last_outcome", sa.String(), nullable=True))
    op.add_column("import_configs", sa.Column("last_message", sa.String(), nullable=True))
    op.create_index("ix_import_configs_next_run_at", "import_configs", ["next_run_at"])


def downgrade() -> None:
    op.drop_index("ix_import_configs_next_run_at", table_name="import_configs")
    for c in ("last_message", "last_outcome", "schedule_failures", "running_since", "next_run_at", "scheduled_by",
              "schedule_timezone", "schedule_weekday", "schedule_time", "schedule_every_hours", "schedule_kind"):
        op.drop_column("import_configs", c)
