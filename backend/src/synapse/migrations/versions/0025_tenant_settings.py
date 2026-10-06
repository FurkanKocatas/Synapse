"""The organisation's settings, one row per tenant (synapse.organization validates them).

Revision ID: 0025
Revises: 0024
"""

from alembic import op

from synapse.migrations.sql_helpers import tenant_rls

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE tenant_settings (
            tenant_id   uuid PRIMARY KEY REFERENCES tenants (id),
            settings    jsonb NOT NULL DEFAULT '{}'
                        CHECK (jsonb_typeof(settings) = 'object'
                               AND length(settings::text) <= 100000),
            updated_at  timestamptz NOT NULL,
            updated_by  uuid
        );
    """)
    op.execute(tenant_rls("tenant_settings"))


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
