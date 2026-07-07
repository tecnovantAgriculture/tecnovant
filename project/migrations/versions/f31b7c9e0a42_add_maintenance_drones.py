"""Add maintenance drones

Revision ID: f31b7c9e0a42
Revises: 8838384f9d55
Create Date: 2026-06-30 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f31b7c9e0a42"
down_revision = "8838384f9d55"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "maintenance_drones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("serial_number", sa.String(length=80), nullable=False),
        sa.Column("brand", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("flight_hours", sa.Numeric(precision=10, scale=1), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("serial_number"),
    )
    op.create_index(
        op.f("ix_maintenance_drones_serial_number"),
        "maintenance_drones",
        ["serial_number"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_maintenance_drones_serial_number"), table_name="maintenance_drones")
    op.drop_table("maintenance_drones")
