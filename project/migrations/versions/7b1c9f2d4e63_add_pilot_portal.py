"""Add pilot portal tables

Revision ID: 7b1c9f2d4e63
Revises: 0d7e69c2a4b1
Create Date: 2026-06-30 00:00:02.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "7b1c9f2d4e63"
down_revision = "0d7e69c2a4b1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pilot_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pilot_id", sa.Integer(), nullable=False),
        sa.Column("device_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("is_authorized", sa.Boolean(), nullable=False),
        sa.Column("first_access_at", sa.DateTime(), nullable=False),
        sa.Column("last_access_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["pilot_id"], ["pilot_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pilot_devices_device_fingerprint"), "pilot_devices", ["device_fingerprint"], unique=False)
    op.create_index(op.f("ix_pilot_devices_pilot_id"), "pilot_devices", ["pilot_id"], unique=False)

    op.create_table(
        "pilot_flight_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pilot_id", sa.Integer(), nullable=False),
        sa.Column("activity_id", sa.Integer(), nullable=True),
        sa.Column("drone_id", sa.Integer(), nullable=False),
        sa.Column("flight_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=False),
        sa.Column("flight_minutes", sa.Integer(), nullable=False),
        sa.Column("takeoff_location", sa.String(length=180), nullable=True),
        sa.Column("landing_location", sa.String(length=180), nullable=True),
        sa.Column("weather", sa.String(length=120), nullable=True),
        sa.Column("battery_cycles", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["operational_activities.id"]),
        sa.ForeignKeyConstraint(["drone_id"], ["maintenance_drones.id"]),
        sa.ForeignKeyConstraint(["pilot_id"], ["pilot_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pilot_flight_logs_activity_id"), "pilot_flight_logs", ["activity_id"], unique=False)
    op.create_index(op.f("ix_pilot_flight_logs_drone_id"), "pilot_flight_logs", ["drone_id"], unique=False)
    op.create_index(op.f("ix_pilot_flight_logs_flight_date"), "pilot_flight_logs", ["flight_date"], unique=False)
    op.create_index(op.f("ix_pilot_flight_logs_pilot_id"), "pilot_flight_logs", ["pilot_id"], unique=False)

    op.create_table(
        "pilot_operation_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pilot_id", sa.Integer(), nullable=False),
        sa.Column("activity_id", sa.Integer(), nullable=True),
        sa.Column("report_type", sa.String(length=60), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["operational_activities.id"]),
        sa.ForeignKeyConstraint(["pilot_id"], ["pilot_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pilot_operation_reports_activity_id"), "pilot_operation_reports", ["activity_id"], unique=False)
    op.create_index(op.f("ix_pilot_operation_reports_pilot_id"), "pilot_operation_reports", ["pilot_id"], unique=False)
    op.create_index(op.f("ix_pilot_operation_reports_status"), "pilot_operation_reports", ["status"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_pilot_operation_reports_status"), table_name="pilot_operation_reports")
    op.drop_index(op.f("ix_pilot_operation_reports_pilot_id"), table_name="pilot_operation_reports")
    op.drop_index(op.f("ix_pilot_operation_reports_activity_id"), table_name="pilot_operation_reports")
    op.drop_table("pilot_operation_reports")
    op.drop_index(op.f("ix_pilot_flight_logs_pilot_id"), table_name="pilot_flight_logs")
    op.drop_index(op.f("ix_pilot_flight_logs_flight_date"), table_name="pilot_flight_logs")
    op.drop_index(op.f("ix_pilot_flight_logs_drone_id"), table_name="pilot_flight_logs")
    op.drop_index(op.f("ix_pilot_flight_logs_activity_id"), table_name="pilot_flight_logs")
    op.drop_table("pilot_flight_logs")
    op.drop_index(op.f("ix_pilot_devices_pilot_id"), table_name="pilot_devices")
    op.drop_index(op.f("ix_pilot_devices_device_fingerprint"), table_name="pilot_devices")
    op.drop_table("pilot_devices")
