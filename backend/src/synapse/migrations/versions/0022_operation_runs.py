"""What maintenance did, for the operations page (ADR 0014): backups and their verifications,
recorded by synapsectl through ``synapse operations record``, and the scheduler's nightly file
sweep and audit verification. Administrators may view the page (``operations.view``).

Revision ID: 0022
Revises: 0021
"""

from alembic import op

from synapse.migrations.sql_helpers import tenant_rls

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE operation_runs (
            id           uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id    uuid NOT NULL REFERENCES tenants (id),
            kind         text NOT NULL
                         CHECK (kind IN ('backup', 'backup_verify', 'files_sweep', 'audit_verify')),
            ok           boolean NOT NULL,
            started_at   timestamptz NOT NULL,
            finished_at  timestamptz NOT NULL CHECK (finished_at >= started_at),
            -- What the run found or did: counts, and the first line of an error.
            details      jsonb NOT NULL DEFAULT '{}'
                         CHECK (jsonb_typeof(details) = 'object' AND length(details::text) <= 4000)
        );
        CREATE INDEX operation_runs_latest ON operation_runs (tenant_id, kind, finished_at DESC);

        INSERT INTO role_permissions (role, permission) VALUES ('admin', 'operations.view');
    """)
    op.execute(tenant_rls("operation_runs"))


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
