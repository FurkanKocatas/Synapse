"""Role permission to manage grants (who may read, write or manage which collections).

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO role_permissions (role, permission) VALUES ('admin', 'permissions.manage')"
    )


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
