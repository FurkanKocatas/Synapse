"""Signed checkpoints of the audit chain's head, kept beside it (ADR 0008).

The scheduler signs the head every hour it has moved; ``synapse audit verify`` checks each
checkpoint's signature and that the chain still has the hash it signed. Like the events,
checkpoints are written once and never changed.

Revision ID: 0021
Revises: 0020
"""

from alembic import op

from synapse.migrations.sql_helpers import tenant_rls

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE audit_checkpoints (
            tenant_id  uuid NOT NULL,
            -- The event it signs: the chain's head when it was signed.
            seq        bigint NOT NULL,
            -- The canonical JSON signed (tenant, seq, hash, signed_at) and the base64 Ed25519
            -- signature over it, as synapse.audit.anchor writes them.
            payload    text NOT NULL CHECK (length(payload) <= 500),
            signature  text NOT NULL CHECK (length(signature) <= 200),
            signed_at  timestamptz NOT NULL,
            -- No foreign key to the event: a checkpoint must outlive an event deleted by
            -- someone who got past the triggers, to show that it is gone.
            PRIMARY KEY (tenant_id, seq),
            FOREIGN KEY (tenant_id) REFERENCES tenants (id)
        );
        CREATE TRIGGER audit_checkpoints_immutable
            BEFORE UPDATE OR DELETE ON audit_checkpoints
            FOR EACH ROW EXECUTE FUNCTION audit_events_reject_change();
        CREATE TRIGGER audit_checkpoints_no_truncate
            BEFORE TRUNCATE ON audit_checkpoints
            FOR EACH STATEMENT EXECUTE FUNCTION audit_events_reject_change();

        REVOKE UPDATE, DELETE, TRUNCATE ON audit_checkpoints FROM synapse_runtime;
    """)
    op.execute(tenant_rls("audit_checkpoints"))


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
