"""Accounts, sessions, second factors, groups and grants, conversations, the tenant and its
settings are the API's alone: the worker and the scheduler, which read documents and keep the
system, lose every right on them (ADR 0013, ADR 0017). The runtime group kept them until now.

Tables made later still go to the runtime group by default; tests/db/test_schema_invariants.py
fails until each new one is put on one side.

Revision ID: 0027
Revises: 0026
"""

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

API_ONLY = (
    "auth_throttle",
    "collection_grants",
    "conversation_turns",
    "conversations",
    "document_grants",
    "group_members",
    "groups",
    "passkeys",
    "recovery_codes",
    "role_permissions",
    "tenant_settings",
    "tenants",
    "totp_credentials",
    "user_sessions",
    "users",
    "webauthn_challenges",
)


def upgrade() -> None:
    names = ", ".join(f"'{name}'" for name in API_ONLY)
    # The API gets exactly what the group had on each table, and the group loses it.
    op.execute(f"""
        DO $$
        DECLARE
            name text;
            privilege text;
        BEGIN
            FOREACH name IN ARRAY ARRAY[{names}] LOOP
                FOREACH privilege IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE'] LOOP
                    IF has_table_privilege('synapse_runtime', name, privilege) THEN
                        EXECUTE format('GRANT %s ON %I TO synapse_api', privilege, name);
                    END IF;
                END LOOP;
                EXECUTE format('REVOKE ALL ON %I FROM synapse_runtime', name);
            END LOOP;
        END $$;
    """)


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
