"""Administrators may retry processing that stopped on an error from the operations page
(``operations.manage``).

Revision ID: 0023
Revises: 0022
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO role_permissions (role, permission) VALUES ('admin', 'operations.manage')"
    )


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
