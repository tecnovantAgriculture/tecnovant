"""Add foliar and orthophoto dates to missions.

Revision ID: e2a6b8c4d901
Revises: c9e2f4a6b801
Create Date: 2026-08-30 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "e2a6b8c4d901"
down_revision = "c9e2f4a6b801"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("orthophoto_mission")}
    if "foliar_date" not in columns:
        op.add_column("orthophoto_mission", sa.Column("foliar_date", sa.Date(), nullable=True))
    if "orthophoto_date" not in columns:
        op.add_column("orthophoto_mission", sa.Column("orthophoto_date", sa.Date(), nullable=True))


def downgrade():
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("orthophoto_mission")}
    if "orthophoto_date" in columns:
        op.drop_column("orthophoto_mission", "orthophoto_date")
    if "foliar_date" in columns:
        op.drop_column("orthophoto_mission", "foliar_date")