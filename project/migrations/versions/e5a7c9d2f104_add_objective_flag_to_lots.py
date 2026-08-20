"""Add objective flag to lots.

Revision ID: e5a7c9d2f104
Revises: c3f8e1a6d2b4
"""

from alembic import op
import sqlalchemy as sa


revision = "e5a7c9d2f104"
down_revision = "c3f8e1a6d2b4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "lots",
        sa.Column("is_objective", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_lots_farm_objective", "lots", ["farm_id", "is_objective"])


def downgrade():
    op.drop_index("ix_lots_farm_objective", table_name="lots")
    op.drop_column("lots", "is_objective")