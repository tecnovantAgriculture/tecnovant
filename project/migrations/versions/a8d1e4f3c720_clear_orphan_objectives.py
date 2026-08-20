"""Clear objective flags without an associated orthophoto.

Revision ID: a8d1e4f3c720
Revises: f7c9a3e2b610
"""

from alembic import op


revision = "a8d1e4f3c720"
down_revision = "f7c9a3e2b610"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE lots SET is_objective = 0 "
        "WHERE is_objective = 1 AND media_asset_id IS NULL"
    )


def downgrade():
    # The previous objective cannot be inferred safely without its orthophoto.
    pass
