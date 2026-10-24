"""routes and outlines: the heights an outline spans

Revision ID: d3f5a7c9e1b2
Revises: c2e4a6b8d0f1
"""
import sqlalchemy as sa
from alembic import op

revision = "d3f5a7c9e1b2"
down_revision = "c2e4a6b8d0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("spatial_features", sa.Column("base_m", sa.Float(), nullable=True))
    op.add_column("spatial_features", sa.Column("top_m", sa.Float(), nullable=True))
    op.create_index("ix_spatial_features_role", "spatial_features", ["role", "state"])


def downgrade() -> None:
    op.drop_index("ix_spatial_features_role", table_name="spatial_features")
    op.drop_column("spatial_features", "top_m")
    op.drop_column("spatial_features", "base_m")
