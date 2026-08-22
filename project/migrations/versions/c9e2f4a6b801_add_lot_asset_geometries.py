"""Store one lot geometry per orthophoto.

Revision ID: c9e2f4a6b801
Revises: a8d1e4f3c720
"""

from alembic import op
import sqlalchemy as sa

revision = "c9e2f4a6b801"
down_revision = "a8d1e4f3c720"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "lot_asset_geometries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lot_id", sa.Integer(), nullable=False),
        sa.Column("media_asset_id", sa.Integer(), nullable=False),
        sa.Column("geometry", sa.Text(), nullable=False),
        sa.Column("geographic_geometry", sa.Text(), nullable=False),
        sa.Column("preview_width", sa.Integer(), nullable=False),
        sa.Column("preview_height", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["lot_id"], ["lots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_asset.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("lot_id", "media_asset_id", name="uq_lot_asset_geometry"),
    )
    op.create_index("ix_lot_asset_geometries_lot_id", "lot_asset_geometries", ["lot_id"])
    op.create_index("ix_lot_asset_geometries_media_asset_id", "lot_asset_geometries", ["media_asset_id"])

def downgrade():
    op.drop_index("ix_lot_asset_geometries_media_asset_id", table_name="lot_asset_geometries")
    op.drop_index("ix_lot_asset_geometries_lot_id", table_name="lot_asset_geometries")
    op.drop_table("lot_asset_geometries")
