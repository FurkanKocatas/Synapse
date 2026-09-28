"""Passkeys (WebAuthn credentials) as a second factor, and their one-time challenges (ADR 0006).

Revision ID: 0007
Revises: 0006
"""

from alembic import op

from synapse.migrations.sql_helpers import tenant_rls

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TABLES = ("passkeys", "webauthn_challenges")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE passkeys (
            id              uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id       uuid NOT NULL,
            user_id         uuid NOT NULL,
            -- The authenticator's credential id (at most 1023 bytes in WebAuthn Level 3).
            credential_id   bytea NOT NULL CHECK (length(credential_id) BETWEEN 16 AND 1023),
            -- COSE-encoded public key. Public by nature, so stored in the clear.
            public_key      bytea NOT NULL,
            -- Signature counter; a value that does not increase can mean a cloned authenticator.
            sign_count      bigint NOT NULL CHECK (sign_count >= 0),
            transports      text[] NOT NULL DEFAULT '{}',
            -- Synced (backed up) passkeys live in a password manager, device-bound ones do not.
            backed_up       boolean NOT NULL,
            name            text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
            created_at      timestamptz NOT NULL,
            last_used_at    timestamptz,
            UNIQUE (tenant_id, credential_id),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE
        );
        CREATE INDEX passkeys_user ON passkeys (tenant_id, user_id);

        -- The challenge of a ceremony in progress. One per session and purpose; taking it deletes
        -- it, so a signed response can be used once only.
        CREATE TABLE webauthn_challenges (
            tenant_id   uuid NOT NULL,
            session_id  uuid NOT NULL,
            purpose     text NOT NULL CHECK (purpose IN ('register', 'authenticate')),
            challenge   bytea NOT NULL CHECK (length(challenge) >= 32),
            expires_at  timestamptz NOT NULL,
            PRIMARY KEY (tenant_id, session_id, purpose),
            FOREIGN KEY (session_id) REFERENCES user_sessions (id) ON DELETE CASCADE
        );

        -- A confirmed TOTP authenticator or at least one passkey. Recovery codes do not count:
        -- they are the fallback for a second factor, not one of their own. SECURITY INVOKER, so
        -- row-level security applies as for any other query.
        CREATE FUNCTION user_has_second_factor(p_user_id uuid) RETURNS boolean
        LANGUAGE sql STABLE SECURITY INVOKER AS $$
            SELECT EXISTS (SELECT 1 FROM totp_credentials
                           WHERE user_id = p_user_id AND confirmed_at IS NOT NULL)
                OR EXISTS (SELECT 1 FROM passkeys WHERE user_id = p_user_id)
        $$;
    """)
    for table in TABLES:
        op.execute(tenant_rls(table))


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
