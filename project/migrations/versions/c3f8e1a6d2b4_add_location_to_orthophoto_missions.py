"""Add client, farm and lot to orthophoto missions.

Revision ID: c3f8e1a6d2b4
Revises: b9c2a7e4d1f8
Create Date: 2026-07-22 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c3f8e1a6d2b4"
down_revision = "b9c2a7e4d1f8"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("orthophoto_mission")}
    for name in ("organization_id", "farm_id", "lot_id"):
        if name not in columns:
            op.add_column("orthophoto_mission", sa.Column(name, sa.Integer(), nullable=True))

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("orthophoto_mission")}
    for name in ("organization_id", "farm_id", "lot_id"):
        index_name = f"ix_orthophoto_mission_{name}"
        if index_name not in indexes:
            op.create_index(index_name, "orthophoto_mission", [name])

    foreign_keys = {item.get("name") for item in sa.inspect(bind).get_foreign_keys("orthophoto_mission")}
    constraints = (
        ("fk_orthophoto_mission_organization", "organizations", "organization_id"),
        ("fk_orthophoto_mission_farm", "farms", "farm_id"),
        ("fk_orthophoto_mission_lot", "lots", "lot_id"),
    )
    for constraint_name, target_table, column_name in constraints:
        if constraint_name not in foreign_keys:
            op.create_foreign_key(constraint_name, "orthophoto_mission", target_table, [column_name], ["id"], ondelete="SET NULL")


def downgrade():
    op.drop_constraint("fk_orthophoto_mission_lot", "orthophoto_mission", type_="foreignkey")
    op.drop_constraint("fk_orthophoto_mission_farm", "orthophoto_mission", type_="foreignkey")
    op.drop_constraint("fk_orthophoto_mission_organization", "orthophoto_mission", type_="foreignkey")
    op.drop_index("ix_orthophoto_mission_lot_id", table_name="orthophoto_mission")
    op.drop_index("ix_orthophoto_mission_farm_id", table_name="orthophoto_mission")
    op.drop_index("ix_orthophoto_mission_organization_id", table_name="orthophoto_mission")
    op.drop_column("orthophoto_mission", "lot_id")
    op.drop_column("orthophoto_mission", "farm_id")
    op.drop_column("orthophoto_mission", "organization_id")
