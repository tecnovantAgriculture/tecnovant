"""Link lot geometries to media assets.

Revision ID: d6b4f2a1c908
Revises: e5a7c9d2f104
"""

from alembic import op
import sqlalchemy as sa


revision = "d6b4f2a1c908"
down_revision = "e5a7c9d2f104"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("lots", sa.Column("media_asset_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_lots_media_asset_id",
        "lots",
        "media_asset",
        ["media_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_lots_media_asset_id", "lots", ["media_asset_id"])


def downgrade():
    op.drop_index("ix_lots_media_asset_id", table_name="lots")
    op.drop_constraint("fk_lots_media_asset_id", "lots", type_="foreignkey")
    op.drop_column("lots", "media_asset_id")
