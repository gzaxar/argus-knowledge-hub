"""Ask ARGUS evaluation runs and settings."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "a5e7c9b1d3f2"
down_revision = "d92b7e4a6103"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ask_eval_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("release", sa.String(), nullable=False),
        sa.Column("commit", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("source", sa.String(), nullable=False, server_default="server"),
        sa.Column("requested_by", sa.String(), nullable=True),
        sa.Column("models", JSONB(), nullable=False, server_default="[]"),
        sa.Column("progress", JSONB(), nullable=True),
        sa.Column("summary", JSONB(), nullable=True),
        sa.Column("report", JSONB(), nullable=True),
        sa.Column("report_sha256", sa.String(), nullable=True),
        sa.Column("public_sha256", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ask_eval_runs_release", "ask_eval_runs", ["release"])
    op.create_table(
        "ask_eval_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("base_url", sa.String(), nullable=True),
        sa.Column("encrypted_key", sa.Text(), nullable=True),
        sa.Column("models", JSONB(), nullable=False, server_default="[]"),
        sa.Column("release_model", sa.String(), nullable=True),
        sa.Column("embedding_model", sa.String(), nullable=True),
        sa.Column("rerank_model", sa.String(), nullable=True),
        sa.Column("judge_model", sa.String(), nullable=True),
        sa.Column("judge_base_url", sa.String(), nullable=True),
        sa.Column("encrypted_judge_key", sa.Text(), nullable=True),
        sa.Column("approved_hosts", JSONB(), nullable=False, server_default="[]"),
        sa.Column("repeats", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("case_timeout_s", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # A sealed report is never changed: only a run that has none yet may get one.
    op.execute("""
        CREATE OR REPLACE FUNCTION ask_eval_runs_sealed() RETURNS trigger AS $$
        BEGIN
          IF OLD.report_sha256 IS NOT NULL AND (NEW.report IS DISTINCT FROM OLD.report
               OR NEW.report_sha256 IS DISTINCT FROM OLD.report_sha256) THEN
            RAISE EXCEPTION 'an Ask evaluation report is sealed and cannot be changed';
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER ask_eval_runs_sealed BEFORE UPDATE ON ask_eval_runs
          FOR EACH ROW EXECUTE FUNCTION ask_eval_runs_sealed();
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS ask_eval_runs_sealed ON ask_eval_runs")
    op.execute("DROP FUNCTION IF EXISTS ask_eval_runs_sealed()")
    op.drop_table("ask_eval_settings")
    op.drop_index("ix_ask_eval_runs_release", table_name="ask_eval_runs")
    op.drop_table("ask_eval_runs")
