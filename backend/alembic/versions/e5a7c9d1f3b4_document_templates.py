"""Document templates (variants, immutable versions) and how drafts were made from raw text

Revision ID: e5a7c9d1f3b4
Revises: d4f6b8c0e2a3
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e5a7c9d1f3b4"
down_revision = "d4f6b8c0e2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_templates",
        sa.Column("uid", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("owner_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("base_template_id", sa.String(), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("draft_source", sa.Text(), nullable=False),
        sa.Column("latest_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_document_templates_workspace_id", "document_templates", ["workspace_id"])
    op.create_index("ix_document_templates_owner_user_id", "document_templates", ["owner_user_id"])
    op.create_index("ix_document_templates_document_type", "document_templates", ["document_type"])
    op.create_table(
        "document_template_versions",
        sa.Column("uid", sa.String(), primary_key=True),
        sa.Column("template_uid", sa.String(), sa.ForeignKey("document_templates.uid", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("official_id", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("template_uid", "version", name="uq_template_version"),
        sa.UniqueConstraint("official_id", "version", "sha256", name="uq_official_version"),
    )
    op.create_index("ix_document_template_versions_template_uid", "document_template_versions", ["template_uid"])
    op.create_index("ix_document_template_versions_official_id", "document_template_versions", ["official_id"])
    # A published version is never changed: the database refuses it, whatever the code does.
    op.execute("""
        CREATE FUNCTION document_template_versions_immutable() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'a published template version cannot be changed' USING ERRCODE = '42501'; END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER document_template_versions_no_update BEFORE UPDATE ON document_template_versions
        FOR EACH ROW EXECUTE FUNCTION document_template_versions_immutable();
    """)
    op.create_table(
        "document_generations",
        sa.Column("uid", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_uid", sa.String(), sa.ForeignKey("documents.uid", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_uid", sa.String(), sa.ForeignKey("document_revisions.uid", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("template_version_uid", sa.String(), sa.ForeignKey("document_template_versions.uid"),
                  nullable=False),
        sa.Column("template_id", sa.String(), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("template_scope", sa.String(), nullable=False),
        sa.Column("source_attachment_uid", sa.String(), nullable=True),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("source_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("dates", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("extraction", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("issues", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_document_generations_workspace_id", "document_generations", ["workspace_id"])
    op.create_index("ix_document_generations_document_uid", "document_generations", ["document_uid"])
    op.create_index("ix_document_generations_revision_uid", "document_generations", ["revision_uid"])


def downgrade() -> None:
    op.drop_table("document_generations")
    op.execute("DROP TRIGGER IF EXISTS document_template_versions_no_update ON document_template_versions; "
               "DROP FUNCTION IF EXISTS document_template_versions_immutable();")
    op.drop_table("document_template_versions")
    op.drop_table("document_templates")
