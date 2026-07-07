"""Add request fields to operational activities

Revision ID: b9c2a7e4d1f8
Revises: a4d8c1b2e9f0
Create Date: 2026-07-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b9c2a7e4d1f8"
down_revision = "a4d8c1b2e9f0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("operational_activities", sa.Column("farm_name", sa.String(length=160), nullable=True))
    op.add_column("operational_activities", sa.Column("paddocks", sa.Text(), nullable=True))
    op.add_column("operational_activities", sa.Column("area_hectares", sa.Numeric(10, 2), nullable=True))
    op.add_column("operational_activities", sa.Column("rest_days", sa.Integer(), nullable=True))
    op.add_column("operational_activities", sa.Column("lot_code", sa.String(length=80), nullable=True))


def downgrade():
    op.drop_column("operational_activities", "lot_code")
    op.drop_column("operational_activities", "rest_days")
    op.drop_column("operational_activities", "area_hectares")
    op.drop_column("operational_activities", "paddocks")
    op.drop_column("operational_activities", "farm_name")
