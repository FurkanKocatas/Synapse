"""Tamper-evident audit log (ADR 0008).

Revision ID: 0004
Revises: 0003
"""

from alembic import op

from synapse.migrations.sql_helpers import tenant_rls

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE audit_events (
            tenant_id      uuid NOT NULL REFERENCES tenants (id),
            -- Gapless per tenant; a missing number is evidence of a deleted row.
            seq            bigint NOT NULL CHECK (seq >= 1),
            id             uuid NOT NULL UNIQUE,
            occurred_at    timestamptz NOT NULL,
            actor_user_id  uuid,
            actor_ip       inet,
            action         text NOT NULL CHECK (action ~ '^[a-z]+(\\.[a-z_]+)+$'),
            target_type    text CHECK (length(target_type) <= 64),
            target_id      text CHECK (length(target_id) <= 200),
            outcome        text NOT NULL CHECK (outcome IN ('success', 'failure', 'denied')),
            details        jsonb NOT NULL,
            schema_version smallint NOT NULL,
            -- SHA-256 of the previous event in this tenant's chain (32 zero bytes for the first)
            -- and of this event's canonical form; computed by synapse.audit.chain.
            prev_hash      bytea NOT NULL CHECK (octet_length(prev_hash) = 32),
            hash           bytea NOT NULL UNIQUE CHECK (octet_length(hash) = 32),
            PRIMARY KEY (tenant_id, seq)
        );
        CREATE INDEX audit_events_time ON audit_events (tenant_id, occurred_at);
        CREATE INDEX audit_events_actor ON audit_events (tenant_id, actor_user_id, occurred_at);

        -- Audit rows are written once and never changed, not even by the table owner.
        -- Retention will be a separate, audited maintenance procedure (ADR 0008).
        CREATE FUNCTION audit_events_reject_change() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog
            AS $$ BEGIN RAISE EXCEPTION 'audit events are immutable'; END $$;
        CREATE TRIGGER audit_events_immutable
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION audit_events_reject_change();
        CREATE TRIGGER audit_events_no_truncate
            BEFORE TRUNCATE ON audit_events
            FOR EACH STATEMENT EXECUTE FUNCTION audit_events_reject_change();

        REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM synapse_runtime;
    """)
    op.execute(tenant_rls("audit_events"))


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
