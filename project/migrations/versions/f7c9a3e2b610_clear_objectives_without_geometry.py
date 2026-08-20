"""Clear objective flags from lots without geometry.

Revision ID: f7c9a3e2b610
Revises: d6b4f2a1c908
"""

from alembic import op


revision = "f7c9a3e2b610"
down_revision = "d6b4f2a1c908"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE lots SET is_objective = 0 "
        "WHERE is_objective = 1 AND (geometry IS NULL OR TRIM(geometry) = '')"
    )


def downgrade():
    # The previous objective cannot be inferred safely once its geometry is gone.
    pass
