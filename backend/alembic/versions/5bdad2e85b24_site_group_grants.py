"""Site-owned groups and site-wide group grants (issue #26).

`groups.home_site_id`: the site a local group belongs to (null: the installation, as every existing group stays).
`site_group_role_bindings`: a role given to a group once for a site, applying in the site and its current
facilities. No grant is made here: existing access stays exactly as it was.

Revision ID: 5bdad2e85b24
Revises: 9c7a1b2d3e4f
"""
import sqlalchemy as sa

from alembic import op

revision = "5bdad2e85b24"
down_revision = "9c7a1b2d3e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("groups", sa.Column("home_site_id", sa.String(),
                                      sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_groups_home_site_id", "groups", ["home_site_id"])
    op.create_table(
        "site_group_role_bindings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("site_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_uid", sa.String(), sa.ForeignKey("groups.uid", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.String(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("site_id", "group_uid", "role_id"),
    )
    op.create_index("ix_site_group_role_bindings_site_id", "site_group_role_bindings", ["site_id"])
    op.create_index("ix_site_group_role_bindings_group_uid", "site_group_role_bindings", ["group_uid"])


def downgrade() -> None:
    op.drop_table("site_group_role_bindings")
    op.drop_index("ix_groups_home_site_id", table_name="groups")
    op.drop_column("groups", "home_site_id")
