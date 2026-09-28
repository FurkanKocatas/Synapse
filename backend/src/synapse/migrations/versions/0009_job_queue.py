"""The job queue: Procrastinate's schema in the application schema (ADR 0004).

The SQL comes from the installed Procrastinate package, so this migration is pinned to the
version it was written for: the dependency is constrained to 3.10.x, and a different version
stops the migration instead of installing a schema nobody reviewed. Upgrading Procrastinate
means a new migration that applies its own migration files.

The queue tables are not tenant-scoped: a job row holds only identifiers (tenant, document
version, actor) in its arguments. The task wrapper sets the tenant from them before touching any
tenant data, so row-level security still applies to everything a job reads or writes.

Revision ID: 0009
Revises: 0008
"""

from importlib import metadata, resources

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

PINNED = "3.10."


def upgrade() -> None:
    installed = metadata.version("procrastinate")
    if not installed.startswith(PINNED):
        raise RuntimeError(f"migration 0009 expects Procrastinate {PINNED}x, found {installed}")
    op.execute(resources.files("procrastinate.sql").joinpath("schema.sql").read_text())


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
