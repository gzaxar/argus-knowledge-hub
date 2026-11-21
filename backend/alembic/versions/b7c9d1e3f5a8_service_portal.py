"""Service portal: a site's services, request types and requests; a ticket's service and team; comment and file
audiences (docs/service-portal.md).

Revision ID: b7c9d1e3f5a8
Revises: a6b8c0d2e4f7
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b7c9d1e3f5a8"
down_revision = "a6b8c0d2e4f7"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "site_service_settings",
        sa.Column("site_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("headline", sa.String(), nullable=True),
        sa.Column("welcome", sa.String(), nullable=True),
        sa.Column("emergency", sa.String(), nullable=True),
        sa.Column("helpdesk_request_type_uid", sa.String(), nullable=True),
        sa.Column("assistance", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("updated_at", TS, nullable=True),
    )
    op.create_table(
        "service_offerings",
        sa.Column("uid", sa.String(), primary_key=True),
        sa.Column("site_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("hours", sa.String(), nullable=True),
        sa.Column("contact", sa.String(), nullable=True),
        sa.Column("provider_workspace_id", sa.String(), nullable=False),
        sa.Column("team_group_uid", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("authorized_by", sa.String(), nullable=True),
        sa.Column("authorized_at", TS, nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", TS, nullable=True),
        sa.Column("updated_at", TS, nullable=True),
        sa.UniqueConstraint("site_id", "slug"),
    )
    op.create_index("ix_service_offerings_site_id", "service_offerings", ["site_id"])
    op.create_index("ix_service_offerings_provider_workspace_id", "service_offerings", ["provider_workspace_id"])
    op.create_index("ix_service_offerings_team_group_uid", "service_offerings", ["team_group_uid"])
    op.create_table(
        "service_request_types",
        sa.Column("uid", sa.String(), primary_key=True),
        sa.Column("service_uid", sa.String(), sa.ForeignKey("service_offerings.uid", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("guidance", sa.String(), nullable=True),
        sa.Column("schema_uid", sa.String(), nullable=True),
        sa.Column("fields", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("allow_attachments", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", TS, nullable=True),
        sa.Column("updated_at", TS, nullable=True),
        sa.UniqueConstraint("service_uid", "slug"),
    )
    op.create_index("ix_service_request_types_service_uid", "service_request_types", ["service_uid"])
    op.create_table(
        "support_requests",
        sa.Column("uid", sa.String(), primary_key=True),
        sa.Column("site_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("origin_workspace_id", sa.String(), nullable=True),
        sa.Column("requester_id", sa.String(), nullable=False),
        sa.Column("issue_uid", sa.String(), sa.ForeignKey("issues.uid", ondelete="CASCADE"), nullable=False,
                  unique=True),
        sa.Column("service_uid", sa.String(), nullable=True),
        sa.Column("request_type_uid", sa.String(), nullable=True),
        sa.Column("service_name", sa.String(), nullable=False),
        sa.Column("request_type_name", sa.String(), nullable=False),
        sa.Column("submitted", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("route", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("submission_uid", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("created_at", TS, nullable=True),
        sa.Column("public_activity_at", TS, nullable=True),
        sa.Column("requester_seen_at", TS, nullable=True),
        sa.UniqueConstraint("requester_id", "submission_uid"),
    )
    op.create_index("ix_support_requests_site_id", "support_requests", ["site_id"])
    op.create_index("ix_support_requests_requester_id", "support_requests", ["requester_id"])
    op.create_index("ix_support_requests_service_uid", "support_requests", ["service_uid"])

    op.add_column("issues", sa.Column("service_uid", sa.String(), nullable=True))
    op.add_column("issues", sa.Column("assigned_group_uid", sa.String(), nullable=True))
    op.create_index("ix_issues_service_uid", "issues", ["service_uid"])
    op.create_index("ix_issues_assigned_group_uid", "issues", ["assigned_group_uid"])
    # Every comment and file written before the portal stays internal: none becomes public by migration.
    op.add_column("issue_comments", sa.Column("audience", sa.String(), nullable=False, server_default="internal"))
    op.add_column("attachments", sa.Column("audience", sa.String(), nullable=False, server_default="internal"))


def downgrade() -> None:
    op.drop_column("attachments", "audience")
    op.drop_column("issue_comments", "audience")
    op.drop_index("ix_issues_assigned_group_uid", table_name="issues")
    op.drop_index("ix_issues_service_uid", table_name="issues")
    op.drop_column("issues", "assigned_group_uid")
    op.drop_column("issues", "service_uid")
    op.drop_table("support_requests")
    op.drop_table("service_request_types")
    op.drop_table("service_offerings")
    op.drop_table("site_service_settings")
