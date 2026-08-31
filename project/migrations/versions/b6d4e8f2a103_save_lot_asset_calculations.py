"""Save calculations per lot and orthophoto.

Revision ID: b6d4e8f2a103
Revises: e2a6b8c4d901
Create Date: 2026-08-30 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "b6d4e8f2a103"
down_revision = "e2a6b8c4d901"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("lot_asset_geometries")}
    if "calculation_data" not in columns:
        op.add_column("lot_asset_geometries", sa.Column("calculation_data", sa.JSON(), nullable=True))
    if "calculated_at" not in columns:
        op.add_column("lot_asset_geometries", sa.Column("calculated_at", sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("lot_asset_geometries")}
    if "calculated_at" in columns:
        op.drop_column("lot_asset_geometries", "calculated_at")
    if "calculation_data" in columns:
        op.drop_column("lot_asset_geometries", "calculation_data")