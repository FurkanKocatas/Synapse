"""Tenancy foundation: the tenant setting accessor and the tenants table.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        -- The tenant of the current transaction, or NULL when none was set. NULL never equals
        -- a tenant_id, so a transaction without a tenant sees no tenant rows (ADR 0005).
        CREATE FUNCTION app_current_tenant() RETURNS uuid
            LANGUAGE sql STABLE PARALLEL SAFE
            SET search_path = pg_catalog
            AS $$ SELECT nullif(current_setting('app.tenant_id', true), '')::uuid $$;

        CREATE TABLE tenants (
            id         uuid PRIMARY KEY DEFAULT uuidv7(),
            slug       text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$'),
            name       text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            created_at timestamptz NOT NULL DEFAULT now()
        );

        -- A tenant row is visible only inside its own transaction context.
        ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
        ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON tenants
            USING (id = app_current_tenant())
            WITH CHECK (id = app_current_tenant());
    """)


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
