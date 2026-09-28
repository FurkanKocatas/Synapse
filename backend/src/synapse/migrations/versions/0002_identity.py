"""Identity: users, sessions, login throttling, TOTP and recovery codes (ADR 0006).

Revision ID: 0002
Revises: 0001
"""

from alembic import op

from synapse.migrations.sql_helpers import tenant_rls

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = ("users", "user_sessions", "auth_throttle", "totp_credentials", "recovery_codes")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE users (
            id                  uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id           uuid NOT NULL REFERENCES tenants (id),
            -- Stored normalized (trimmed, lower case) so uniqueness is a plain constraint.
            email               text NOT NULL
                                CHECK (email = lower(email) AND length(email) <= 254
                                       AND email ~ '^[^@\\s]+@[^@\\s]+$'),
            display_name        text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
            role                text NOT NULL
                                CHECK (role IN ('admin', 'editor', 'member', 'auditor')),
            status              text NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'disabled')),
            locale              text NOT NULL DEFAULT 'tr' CHECK (locale IN ('tr', 'en')),
            -- NULL means password login is not possible for this account.
            password_hash       text,
            password_changed_at timestamptz,
            created_at          timestamptz NOT NULL DEFAULT now(),
            updated_at          timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, email),
            -- Lets child tables reference (tenant_id, id), so a row can never point at a user
            -- of another tenant.
            UNIQUE (tenant_id, id)
        );

        CREATE TABLE user_sessions (
            id                  uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id           uuid NOT NULL,
            user_id             uuid NOT NULL,
            -- SHA-256 of the cookie token; the token itself is never stored.
            token_hash          bytea NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),
            -- 'pending_mfa': password accepted, second factor still required.
            -- 'enroll_mfa':  password accepted, the account must set up a second factor first.
            -- 'full':        fully signed in.
            auth_level          text NOT NULL
                                CHECK (auth_level IN ('pending_mfa', 'enroll_mfa', 'full')),
            created_at          timestamptz NOT NULL DEFAULT now(),
            last_seen_at        timestamptz NOT NULL DEFAULT now(),
            absolute_expires_at timestamptz NOT NULL,
            revoked_at          timestamptz,
            revoked_reason      text,
            client_ip           inet,
            user_agent          text CHECK (length(user_agent) <= 512),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE
        );
        CREATE INDEX user_sessions_user ON user_sessions (tenant_id, user_id)
            WHERE revoked_at IS NULL;

        -- Failed-attempt counters for exponential backoff. The subject is an opaque key such as
        -- 'email:<sha256>' or 'ip:<address>', so throttling also works for unknown accounts.
        CREATE TABLE auth_throttle (
            tenant_id       uuid NOT NULL REFERENCES tenants (id),
            subject         text NOT NULL CHECK (length(subject) <= 200),
            failures        integer NOT NULL CHECK (failures >= 0),
            last_failure_at timestamptz NOT NULL,
            blocked_until   timestamptz,
            PRIMARY KEY (tenant_id, subject)
        );

        CREATE TABLE totp_credentials (
            tenant_id         uuid NOT NULL,
            user_id           uuid NOT NULL,
            -- AES-256-GCM ciphertext of the base32 secret (nonce prepended).
            secret_ciphertext bytea NOT NULL,
            -- NULL until the user has proven the authenticator works by entering a code.
            confirmed_at      timestamptz,
            -- Highest TOTP time step accepted; a code for this step or earlier is a replay.
            last_used_step    bigint,
            created_at        timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, user_id),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE
        );

        CREATE TABLE recovery_codes (
            id         uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id  uuid NOT NULL,
            user_id    uuid NOT NULL,
            code_hash  text NOT NULL,
            used_at    timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE
        );
        CREATE INDEX recovery_codes_user ON recovery_codes (tenant_id, user_id)
            WHERE used_at IS NULL;
    """)
    for table in TABLES:
        op.execute(tenant_rls(table))


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
