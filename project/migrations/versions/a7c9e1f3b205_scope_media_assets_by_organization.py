"""Scope media assets by organization.

Revision ID: a7c9e1f3b205
Revises: b6d4e8f2a103
"""

import json

from alembic import op
import sqlalchemy as sa

revision = "a7c9e1f3b205"
down_revision = "b6d4e8f2a103"
branch_labels = None
depends_on = None


def _names(items):
    return {item.get("name") for item in items if item.get("name")}


def _has_columns(items, expected):
    expected = list(expected)
    return any(
        list(item.get("column_names") or item.get("constrained_columns") or [])
        == expected
        for item in items
    )


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "organization_id" not in _names(inspector.get_columns("media_asset")):
        op.add_column(
            "media_asset", sa.Column("organization_id", sa.Integer(), nullable=True)
        )

    inspector = sa.inspect(bind)
    if not _has_columns(
        inspector.get_foreign_keys("media_asset"), ["organization_id"]
    ):
        op.create_foreign_key(
            "fk_media_asset_organization_id",
            "media_asset",
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="SET NULL",
        )

    inspector = sa.inspect(bind)
    if not _has_columns(inspector.get_indexes("media_asset"), ["organization_id"]):
        op.create_index(
            "ix_media_asset_organization_id", "media_asset", ["organization_id"]
        )

    photo_assets = bind.execute(
        sa.text(
            """
            SELECT photo.asset_id, mission.organization_id
              FROM orthophoto_photo AS photo
              JOIN orthophoto_mission AS mission ON mission.id = photo.mission_id
             WHERE mission.organization_id IS NOT NULL
            """
        )
    )
    for row in photo_assets:
        bind.execute(
            sa.text(
                "UPDATE media_asset SET organization_id = :organization_id "
                "WHERE id = :asset_id AND organization_id IS NULL"
            ),
            {"organization_id": row.organization_id, "asset_id": row.asset_id},
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
        if isinstance(row.exif, str):
            try:
                metadata = json.loads(row.exif)
            except (TypeError, ValueError):
                metadata = {}
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

    inspector = sa.inspect(bind)
    unique_constraints = inspector.get_unique_constraints("media_asset")
    old_unique = next(
        (
            item
            for item in unique_constraints
            if list(item.get("column_names") or []) == ["sha256", "size_bytes"]
        ),
        None,
    )
    if old_unique and old_unique.get("name"):
        op.drop_constraint(old_unique["name"], "media_asset", type_="unique")

    inspector = sa.inspect(bind)
    unique_constraints = inspector.get_unique_constraints("media_asset")
    indexes = inspector.get_indexes("media_asset")
    new_columns = ["organization_id", "sha256", "size_bytes"]
    if not (
        _has_columns(unique_constraints, new_columns)
        or _has_columns(indexes, new_columns)
    ):
        op.create_unique_constraint(
            "uq_asset_org_dedup", "media_asset", new_columns
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    unique_constraints = inspector.get_unique_constraints("media_asset")
    indexes = inspector.get_indexes("media_asset")
    new_unique = next(
        (
            item
            for item in unique_constraints + indexes
            if list(item.get("column_names") or [])
            == ["organization_id", "sha256", "size_bytes"]
        ),
        None,
    )
    if new_unique and new_unique.get("name"):
        op.drop_constraint(new_unique["name"], "media_asset", type_="unique")

    inspector = sa.inspect(bind)
    unique_constraints = inspector.get_unique_constraints("media_asset")
    indexes = inspector.get_indexes("media_asset")
    old_columns = ["sha256", "size_bytes"]
    if not (
        _has_columns(unique_constraints, old_columns)
        or _has_columns(indexes, old_columns)
    ):
        op.create_unique_constraint("uq_asset_dedup", "media_asset", old_columns)

    inspector = sa.inspect(bind)
    index = next(
        (
            item
            for item in inspector.get_indexes("media_asset")
            if list(item.get("column_names") or []) == ["organization_id"]
        ),
        None,
    )
    if index and index.get("name"):
        op.drop_index(index["name"], table_name="media_asset")

    inspector = sa.inspect(bind)
    foreign_key = next(
        (
            item
            for item in inspector.get_foreign_keys("media_asset")
            if list(item.get("constrained_columns") or []) == ["organization_id"]
        ),
        None,
    )
    if foreign_key and foreign_key.get("name"):
        op.drop_constraint(
            foreign_key["name"], "media_asset", type_="foreignkey"
        )

    inspector = sa.inspect(bind)
    if "organization_id" in _names(inspector.get_columns("media_asset")):
        op.drop_column("media_asset", "organization_id")