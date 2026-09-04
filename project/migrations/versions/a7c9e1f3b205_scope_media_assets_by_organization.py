"""Scope media assets by organization.

Revision ID: a7c9e1f3b205
Revises: b6d4e8f2a103
"""

from alembic import op
import sqlalchemy as sa

revision = "a7c9e1f3b205"
down_revision = "b6d4e8f2a103"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "media_asset", sa.Column("organization_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_media_asset_organization_id",
        "media_asset",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_media_asset_organization_id", "media_asset", ["organization_id"]
    )
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE media_asset AS asset
               SET organization_id = mission.organization_id
              FROM orthophoto_photo AS photo
              JOIN orthophoto_mission AS mission ON mission.id = photo.mission_id
             WHERE photo.asset_id = asset.id
               AND mission.organization_id IS NOT NULL
            """
        )
    )

    missions = {
        str(row.id): row.organization_id
        for row in bind.execute(
            sa.text(
                "SELECT id, organization_id FROM orthophoto_mission "
                "WHERE organization_id IS NOT NULL"
            )
        )
    }
    assets = bind.execute(
        sa.text("SELECT id, exif FROM media_asset WHERE organization_id IS NULL")
    )
    for row in assets:
        metadata = row.exif if isinstance(row.exif, dict) else {}
        mission_id = str(metadata.get("orthophoto_mission_id") or "")
        organization_id = missions.get(mission_id)
        if organization_id is not None:
            bind.execute(
                sa.text(
                    "UPDATE media_asset SET organization_id = :organization_id "
                    "WHERE id = :asset_id"
                ),
                {"organization_id": organization_id, "asset_id": row.id},
            )
    op.drop_constraint("uq_asset_dedup", "media_asset", type_="unique")
    op.create_unique_constraint(
        "uq_asset_org_dedup",
        "media_asset",
        ["organization_id", "sha256", "size_bytes"],
    )


def downgrade():
    op.drop_constraint("uq_asset_org_dedup", "media_asset", type_="unique")
    op.create_unique_constraint(
        "uq_asset_dedup", "media_asset", ["sha256", "size_bytes"]
    )
    op.drop_index("ix_media_asset_organization_id", table_name="media_asset")
    op.drop_constraint(
        "fk_media_asset_organization_id", "media_asset", type_="foreignkey"
    )
    op.drop_column("media_asset", "organization_id")