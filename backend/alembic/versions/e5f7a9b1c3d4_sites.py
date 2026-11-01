"""Sites: a laboratory workspace whose places its facility workspaces use (docs/sites.md).

`workspaces.site_id` names the site a facility is at (a workspace with role `site`); `assets.site_shared` says a
site's place is visible from its facilities (kept by app/services/sites.py); `assets.site_withheld` withholds a
place, and what is inside it, from them.

Revision ID: e5f7a9b1c3d4
Revises: d4e6f8a0b2c3
"""
import sqlalchemy as sa

from alembic import op

revision = "e5f7a9b1c3d4"
down_revision = "d4e6f8a0b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("site_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
                                          nullable=True))
    op.create_index("ix_workspaces_site_id", "workspaces", ["site_id"])
    op.add_column("assets", sa.Column("site_shared", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("assets", sa.Column("site_withheld", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_assets_site_shared", "assets", ["workspace_id"], postgresql_where=sa.text("site_shared"))


def downgrade() -> None:
    op.drop_index("ix_assets_site_shared", table_name="assets")
    op.drop_column("assets", "site_withheld")
    op.drop_column("assets", "site_shared")
    op.drop_index("ix_workspaces_site_id", table_name="workspaces")
    op.drop_column("workspaces", "site_id")
