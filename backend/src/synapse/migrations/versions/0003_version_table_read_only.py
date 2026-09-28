"""Runtime roles may read the migration version table but not change it.

The default privileges give the runtime group write access to every table the migrator
creates, which includes Alembic's own version table. Only the migrator may record revisions.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON alembic_version FROM synapse_runtime")


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
