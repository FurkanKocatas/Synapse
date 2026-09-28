"""Idempotent cluster-level setup for a Synapse database.

Creates what is missing and brings everything else to the expected state, so it is safe to run
on every install and upgrade:

1. the database, with ``CONNECT`` revoked from ``PUBLIC``;
2. the migrator, the runtime group and the runtime login roles, with passwords (re)set from the
   secret files as SCRAM verifiers;
3. the ``synapse`` schema owned by the migrator, extensions, and default privileges so that
   every table the migrator creates is usable by the runtime group and nothing else.

Runtime roles never own objects, are not superusers and cannot bypass row-level security.
"""

from pathlib import Path

import psycopg
from psycopg import sql

from synapse.dbadmin.roles import (
    ALL_LOGIN_ROLES,
    IDLE_IN_TRANSACTION_TIMEOUT,
    MIGRATOR,
    RUNTIME_GROUP,
    RUNTIME_ROLES,
    SCHEMA,
)
from synapse.dbadmin.scram import scram_sha256_verifier
from synapse.kernel.secrets import read_secret

EXTENSIONS = ("vector", "pg_textsearch")

# Every role attribute stated explicitly, so an existing role drifting from them is corrected.
_ROLE_ATTRIBUTES = sql.SQL("NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")


def password_file(secrets_dir: Path, role: str) -> Path:
    """Where the installer keeps each role's password (one file per role)."""
    return secrets_dir / f"db_{role}"


def bootstrap(admin_conninfo: str, database: str, secrets_dir: Path) -> None:
    """Bring ``database`` and its roles to the expected state.

    ``admin_conninfo`` must connect as a superuser to any existing database (``postgres``).
    """
    with psycopg.connect(admin_conninfo, autocommit=True) as admin:
        _ensure_roles(admin, secrets_dir)
        _ensure_database(admin, database)

    with (
        psycopg.connect(admin_conninfo, dbname=database, autocommit=True) as target,
        target.transaction(),
    ):
        _configure_database(target, database)


def _ensure_roles(admin: psycopg.Connection, secrets_dir: Path) -> None:
    _create_role_if_missing(admin, RUNTIME_GROUP)
    admin.execute(
        sql.SQL("ALTER ROLE {} NOLOGIN {}").format(sql.Identifier(RUNTIME_GROUP), _ROLE_ATTRIBUTES)
    )

    for role_name in ALL_LOGIN_ROLES:
        _create_role_if_missing(admin, role_name)
        verifier = scram_sha256_verifier(read_secret(password_file(secrets_dir, role_name)))
        admin.execute(
            sql.SQL("ALTER ROLE {} LOGIN {} PASSWORD {}").format(
                sql.Identifier(role_name), _ROLE_ATTRIBUTES, sql.Literal(verifier)
            )
        )
        admin.execute(
            sql.SQL("ALTER ROLE {} SET idle_in_transaction_session_timeout = {}").format(
                sql.Identifier(role_name), sql.Literal(IDLE_IN_TRANSACTION_TIMEOUT)
            )
        )

    for role in RUNTIME_ROLES:
        admin.execute(
            sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(RUNTIME_GROUP), sql.Identifier(role.name)
            )
        )
        admin.execute(
            sql.SQL("ALTER ROLE {} SET statement_timeout = {}").format(
                sql.Identifier(role.name), sql.Literal(role.statement_timeout)
            )
        )


def _create_role_if_missing(admin: psycopg.Connection, role: str) -> None:
    exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
    if not exists:
        admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))


def _ensure_database(admin: psycopg.Connection, database: str) -> None:
    exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone()
    if not exists:
        admin.execute(
            sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(
                sql.Identifier(database)
            )
        )


def _configure_database(target: psycopg.Connection, database: str) -> None:
    db = sql.Identifier(database)
    schema = sql.Identifier(SCHEMA)
    migrator = sql.Identifier(MIGRATOR)
    runtime = sql.Identifier(RUNTIME_GROUP)
    statements: list[sql.SQL | sql.Composed] = [
        sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db),
        sql.SQL("GRANT CONNECT, TEMPORARY ON DATABASE {} TO {}, {}").format(db, migrator, runtime),
        sql.SQL("REVOKE ALL ON SCHEMA public FROM PUBLIC"),
        sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION {}").format(schema, migrator),
        sql.SQL("ALTER SCHEMA {} OWNER TO {}").format(schema, migrator),
        sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(schema),
        sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, runtime),
        sql.SQL("ALTER DATABASE {} SET search_path = {}").format(db, schema),
        # What the migrator creates is usable by the runtime group; functions are not
        # executable by PUBLIC (PostgreSQL's default), only by the runtime group.
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
        ).format(migrator, schema, runtime),
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} "
            "GRANT USAGE, SELECT ON SEQUENCES TO {}"
        ).format(migrator, schema, runtime),
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
        ).format(migrator),
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} GRANT EXECUTE ON FUNCTIONS TO {}"
        ).format(migrator, schema, runtime),
    ]
    statements += [
        sql.SQL("CREATE EXTENSION IF NOT EXISTS {} WITH SCHEMA {}").format(
            sql.Identifier(extension), schema
        )
        for extension in EXTENSIONS
    ]
    for statement in statements:
        target.execute(statement)
