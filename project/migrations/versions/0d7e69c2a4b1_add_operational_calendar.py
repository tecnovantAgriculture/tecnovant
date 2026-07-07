"""Add operational calendar

Revision ID: 0d7e69c2a4b1
Revises: f31b7c9e0a42
Create Date: 2026-06-30 00:00:01.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0d7e69c2a4b1"
down_revision = "f31b7c9e0a42"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pilot_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=8), nullable=True),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("first_name", sa.String(length=90), nullable=False),
        sa.Column("last_name", sa.String(length=90), nullable=False),
        sa.Column("document_number", sa.String(length=50), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=120), nullable=True),
        sa.Column("certification_status", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index(op.f("ix_pilot_profiles_document_number"), "pilot_profiles", ["document_number"], unique=False)
    op.create_index(op.f("ix_pilot_profiles_user_id"), "pilot_profiles", ["user_id"], unique=False)
    op.create_index(op.f("ix_pilot_profiles_username"), "pilot_profiles", ["username"], unique=False)

    op.create_table(
        "pilot_certifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pilot_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=140), nullable=False),
        sa.Column("issuer", sa.String(length=120), nullable=True),
        sa.Column("certificate_number", sa.String(length=90), nullable=True),
        sa.Column("issued_at", sa.Date(), nullable=True),
        sa.Column("expires_at", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["pilot_id"], ["pilot_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pilot_certifications_pilot_id"), "pilot_certifications", ["pilot_id"], unique=False)

    op.create_table(
        "operational_activities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=140), nullable=False),
        sa.Column("operation_type", sa.String(length=80), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("place", sa.String(length=180), nullable=False),
        sa.Column("client_project", sa.String(length=160), nullable=True),
        sa.Column("pilot_id", sa.Integer(), nullable=False),
        sa.Column("drone_id", sa.Integer(), nullable=False),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_by_id", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["drone_id"], ["maintenance_drones.id"]),
        sa.ForeignKeyConstraint(["pilot_id"], ["pilot_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_operational_activities_drone_id"), "operational_activities", ["drone_id"], unique=False)
    op.create_index(op.f("ix_operational_activities_ends_at"), "operational_activities", ["ends_at"], unique=False)
    op.create_index(op.f("ix_operational_activities_pilot_id"), "operational_activities", ["pilot_id"], unique=False)
    op.create_index(op.f("ix_operational_activities_starts_at"), "operational_activities", ["starts_at"], unique=False)
    op.create_index(op.f("ix_operational_activities_status"), "operational_activities", ["status"], unique=False)

    op.create_table(
        "operational_activity_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("activity_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=8), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["operational_activities.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_operational_activity_logs_activity_id"), "operational_activity_logs", ["activity_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_operational_activity_logs_activity_id"), table_name="operational_activity_logs")
    op.drop_table("operational_activity_logs")
    op.drop_index(op.f("ix_operational_activities_status"), table_name="operational_activities")
    op.drop_index(op.f("ix_operational_activities_starts_at"), table_name="operational_activities")
    op.drop_index(op.f("ix_operational_activities_pilot_id"), table_name="operational_activities")
    op.drop_index(op.f("ix_operational_activities_ends_at"), table_name="operational_activities")
    op.drop_index(op.f("ix_operational_activities_drone_id"), table_name="operational_activities")
    op.drop_table("operational_activities")
    op.drop_index(op.f("ix_pilot_certifications_pilot_id"), table_name="pilot_certifications")
    op.drop_table("pilot_certifications")
    op.drop_index(op.f("ix_pilot_profiles_username"), table_name="pilot_profiles")
    op.drop_index(op.f("ix_pilot_profiles_user_id"), table_name="pilot_profiles")
    op.drop_index(op.f("ix_pilot_profiles_document_number"), table_name="pilot_profiles")
    op.drop_table("pilot_profiles")
