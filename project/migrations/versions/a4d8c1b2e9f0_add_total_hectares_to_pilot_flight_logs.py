"""Add total hectares to pilot flight logs

Revision ID: a4d8c1b2e9f0
Revises: 7b1c9f2d4e63
Create Date: 2026-06-30 00:00:03.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a4d8c1b2e9f0"
down_revision = "7b1c9f2d4e63"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pilot_flight_logs", sa.Column("total_hectares", sa.Numeric(10, 2), nullable=True))


def downgrade():
    op.drop_column("pilot_flight_logs", "total_hectares")
