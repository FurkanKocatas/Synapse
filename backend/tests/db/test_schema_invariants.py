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


def test_the_check_catches_a_table_without_rls(test_database: TestDatabase) -> None:
    # Guards the guard: a check that cannot fail proves nothing.
    with test_database.admin() as admin, admin.transaction(force_rollback=True):
        admin.execute(f"CREATE TABLE {SCHEMA}.probe_without_rls (id int)")
        problems = tenancy_problems(admin)
    assert "probe_without_rls: no NOT NULL tenant_id column" in problems
    assert "probe_without_rls: row-level security not enabled and forced" in problems
