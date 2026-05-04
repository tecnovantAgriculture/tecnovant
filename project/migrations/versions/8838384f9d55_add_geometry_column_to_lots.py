"""Add geometry column to lots

Revision ID: 8838384f9d55
Revises:
Create Date: 2026-04-13 02:53:19.037371
"""

from alembic import op
import sqlalchemy as sa


revision = '8838384f9d55'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('lots', sa.Column('geometry', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('lots', 'geometry')
