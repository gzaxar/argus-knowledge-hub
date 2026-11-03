"""The AI settings name a model for structured work, and say how each model is called (docs: Administration › AI).

`llm_configs.structured_model`: the model that answers with data (rework, filling a form, a ticket) rather than
prose — a fast one that does not reason, where the chat model does. `llm_configs.model_settings`: per model name,
how it is called — its temperature, whether it is told not to think, JSON mode, and how long ARGUS waits.

Revision ID: f8b0c2d4e6a1
Revises: e5f7a9b1c3d4
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "f8b0c2d4e6a1"
down_revision = "e5f7a9b1c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_configs", sa.Column("structured_model", sa.String(), nullable=True))
    op.add_column("llm_configs", sa.Column("model_settings", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_configs", "model_settings")
    op.drop_column("llm_configs", "structured_model")
