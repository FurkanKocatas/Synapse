"""The cluster-level setup: roles, privileges and idempotence."""

import psycopg
import pytest

from synapse.dbadmin import bootstrap, migrate
from synapse.dbadmin.roles import MIGRATOR, RUNTIME_GROUP, RUNTIME_ROLES, SCHEMA
from tests.db.conftest import TestDatabase

RUNTIME = [role.name for role in RUNTIME_ROLES]


def test_bootstrap_is_idempotent(test_database: TestDatabase) -> None:
    bootstrap.bootstrap(test_database.admin_conninfo, test_database.name, test_database.secrets_dir)
    migrate.upgrade(test_database.settings(MIGRATOR))


def test_login_roles_have_no_elevated_attributes(test_database: TestDatabase) -> None:
    with test_database.admin() as admin:
        rows = admin.execute(
            "SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls, rolreplication "
            "FROM pg_roles WHERE rolname = ANY(%s)",
            ([MIGRATOR, RUNTIME_GROUP, *RUNTIME],),
        ).fetchall()
    assert len(rows) == len(RUNTIME) + 2
    for name, *elevated in rows:
        assert not any(elevated), f"{name} has an elevated attribute"


def test_runtime_roles_own_nothing(test_database: TestDatabase) -> None:
    with test_database.admin() as admin:
        owned = admin.execute(
            "SELECT c.relname, r.rolname FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND r.rolname <> %s",
            (SCHEMA, MIGRATOR),
        ).fetchall()
    assert owned == [], "objects in the synapse schema must be owned by the migrator only"


def test_every_runtime_role_can_log_in_with_its_secret(test_database: TestDatabase) -> None:
    # Also proves the SCRAM verifiers are computed correctly: the server accepts the password.
    for role in RUNTIME_ROLES:
        settings = test_database.settings(role.name)
        with psycopg.connect(settings.conninfo()) as connection:
            timeout = connection.execute("SHOW statement_timeout").fetchone()
            assert timeout == (role.statement_timeout,)


def test_public_cannot_connect(test_database: TestDatabase) -> None:
    with test_database.admin() as admin:
        admin.execute("DROP ROLE IF EXISTS synapse_test_outsider")
        admin.execute("CREATE ROLE synapse_test_outsider LOGIN PASSWORD NULL")
        try:
            can_connect = admin.execute(
                "SELECT has_database_privilege('synapse_test_outsider', %s, 'CONNECT')",
                (test_database.name,),
            ).fetchone()
        finally:
            admin.execute("DROP ROLE synapse_test_outsider")
    assert can_connect == (False,)


def test_runtime_roles_cannot_change_the_schema(test_database: TestDatabase) -> None:
    settings = test_database.settings("synapse_api")
    with (
        psycopg.connect(settings.conninfo()) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute("CREATE TABLE intruder (id int)")


def test_extensions_are_installed(test_database: TestDatabase) -> None:
    with test_database.admin() as admin:
        names = {row[0] for row in admin.execute("SELECT extname FROM pg_extension")}
    assert {"vector", "pg_textsearch"} <= names


def test_runtime_roles_cannot_change_the_recorded_revision(test_database: TestDatabase) -> None:
    settings = test_database.settings("synapse_api")
    with psycopg.connect(settings.conninfo()) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("UPDATE alembic_version SET version_num = 'forged'")
