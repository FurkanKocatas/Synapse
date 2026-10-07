"""Every table in the schema follows the tenancy rules (ADR 0005, ADR 0017).

This test inspects the migrated database, so a new table that forgets row-level security fails
here even if no test ever queries it.
"""

import psycopg

from synapse.dbadmin.roles import SCHEMA
from tests.db.conftest import TestDatabase

# Tables that are deliberately not tenant-scoped, with the reason.
NOT_TENANT_SCOPED = {
    "alembic_version": "migration bookkeeping; holds no tenant data",
    "role_permissions": "the same catalogue for every tenant; read-only for runtime roles",
    # The job queue (migration 0009). Job rows hold identifiers only; the task wrapper sets the
    # tenant from them before touching tenant data.
    "procrastinate_jobs": "job queue; arguments are identifiers, tenant set by the task wrapper",
    "procrastinate_events": "job state history; identifiers only",
    "procrastinate_periodic_defers": "bookkeeping for periodic jobs; no tenant data",
    "procrastinate_workers": "worker heartbeats; no tenant data",
}
# Tables scoped by their own primary key instead of a tenant_id column.
SCOPED_BY_ID = {"tenants"}

_TABLES = """
    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
           EXISTS (SELECT 1 FROM information_schema.columns col
                   WHERE col.table_schema = n.nspname AND col.table_name = c.relname
                     AND col.column_name = 'tenant_id' AND col.is_nullable = 'NO'),
           (SELECT array_agg(p.polname ORDER BY p.polname) FROM pg_policy p
            WHERE p.polrelid = c.oid)
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = %s AND c.relkind IN ('r', 'p')
"""


def tenancy_problems(connection: psycopg.Connection) -> list[str]:
    tables = connection.execute(_TABLES, (SCHEMA,)).fetchall()
    assert tables, "no tables found; did the migrations run?"
    problems = []
    for name, rls, forced, has_tenant_id, policies in tables:
        if name in NOT_TENANT_SCOPED:
            continue
        if name not in SCOPED_BY_ID and not has_tenant_id:
            problems.append(f"{name}: no NOT NULL tenant_id column")
        if not (rls and forced):
            problems.append(f"{name}: row-level security not enabled and forced")
        if policies != ["tenant_isolation"]:
            problems.append(f"{name}: policies {policies}, expected ['tenant_isolation']")
    return problems


def test_every_tenant_table_has_forced_rls_and_the_standard_policy(
    test_database: TestDatabase,
) -> None:
    with test_database.admin() as admin:
        assert tenancy_problems(admin) == []


# Who may use each table (migration 0027). Accounts, sessions, permissions, conversations and
# settings are the API's alone; the worker and the scheduler read documents and keep the system.
# A new table fails the check below until it is put in one of the two sets.
API_ONLY = {
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
}
SHARED = {
    "alembic_version",
    "audit_checkpoints",
    "audit_events",
    "blobs",
    "chunk_entities",
    "collections",
    "document_chunks",
    "document_pages",
    "document_versions",
    "documents",
    "operation_runs",
    "procrastinate_events",
    "procrastinate_jobs",
    "procrastinate_periodic_defers",
    "procrastinate_workers",
}
_TABLE_NAMES = """
    SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = %s AND c.relkind IN ('r', 'p') ORDER BY c.relname
"""


def privilege_problems(connection: psycopg.Connection) -> list[str]:
    tables = [row[0] for row in connection.execute(_TABLE_NAMES, (SCHEMA,)).fetchall()]
    assert tables, "no tables found; did the migrations run?"

    def holds(role: str, table: str, privilege: str) -> bool:
        row = connection.execute(
            "SELECT has_table_privilege(%s, %s, %s)", (role, f"{SCHEMA}.{table}", privilege)
        ).fetchone()
        return bool(row and row[0])

    problems = []
    for table in tables:
        if table in API_ONLY:
            for role in ("synapse_worker", "synapse_scheduler"):
                held = [
                    p for p in ("SELECT", "INSERT", "UPDATE", "DELETE") if holds(role, table, p)
                ]
                if held:
                    problems.append(f"{table}: {role} holds {', '.join(held)}")
            if not holds("synapse_api", table, "SELECT"):
                problems.append(f"{table}: synapse_api cannot read it")
        elif table not in SHARED:
            problems.append(f"{table}: neither the API's alone nor shared; put it in one set")
    return problems


def test_accounts_and_conversations_are_the_apis_alone(test_database: TestDatabase) -> None:
    with test_database.admin() as admin:
        assert privilege_problems(admin) == []


def test_the_privilege_check_catches_a_leak_and_an_unsorted_table(
    test_database: TestDatabase,
) -> None:
    with test_database.admin() as admin, admin.transaction(force_rollback=True):
        admin.execute(f"GRANT SELECT ON {SCHEMA}.users TO synapse_runtime")
        admin.execute(f"CREATE TABLE {SCHEMA}.probe_unsorted (id int)")
        problems = privilege_problems(admin)
    assert "users: synapse_worker holds SELECT" in problems
    assert "users: synapse_scheduler holds SELECT" in problems
    assert "probe_unsorted: neither the API's alone nor shared; put it in one set" in problems


def test_the_check_catches_a_table_without_rls(test_database: TestDatabase) -> None:
    # Guards the guard: a check that cannot fail proves nothing.
    with test_database.admin() as admin, admin.transaction(force_rollback=True):
        admin.execute(f"CREATE TABLE {SCHEMA}.probe_without_rls (id int)")
        problems = tenancy_problems(admin)
    assert "probe_without_rls: no NOT NULL tenant_id column" in problems
    assert "probe_without_rls: row-level security not enabled and forced" in problems
