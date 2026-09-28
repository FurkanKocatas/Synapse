"""A real PostgreSQL for database tests (ADR 0017).

Each test session bootstraps and migrates a fresh database on the server named by the admin
connection file, and drops it afterwards. Without a server these tests fail with instructions;
they are never skipped, because skipped security tests look exactly like passing ones.

Defaults match local development and CI:
    python3 tools/dev_secrets.py
    docker compose -f deploy/compose.dev.yml up -d --wait db
"""

import os
import secrets
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from synapse.dbadmin import bootstrap, migrate
from synapse.dbadmin.roles import MIGRATOR
from synapse.kernel.database import ConnectionSettings, Database
from synapse.kernel.secrets import read_secret

REPO = Path(__file__).resolve().parents[3]
DEFAULT_SECRETS = REPO / ".dev" / "secrets"


@dataclass(frozen=True)
class TestDatabase:
    __test__ = False  # not a test class, despite the name

    admin_conninfo: str
    name: str
    secrets_dir: Path
    host: str
    port: int

    def settings(self, role: str) -> ConnectionSettings:
        return ConnectionSettings(
            host=self.host,
            port=self.port,
            dbname=self.name,
            user=role,
            password_file=bootstrap.password_file(self.secrets_dir, role),
            application_name="synapse-tests",
        )

    def admin(self) -> psycopg.Connection:
        """A superuser connection to the test database, for inspecting it."""
        return psycopg.connect(self.admin_conninfo, dbname=self.name, autocommit=True)


@pytest.fixture(scope="session")
def test_database() -> Iterator[TestDatabase]:
    secrets_dir = Path(os.environ.get("SYNAPSE_TEST_SECRETS_DIR", DEFAULT_SECRETS))
    admin_file = secrets_dir / "admin_conninfo"
    if not admin_file.exists():
        pytest.fail(
            f"No test database configured: {admin_file} does not exist.\n"
            "Run: python3 tools/dev_secrets.py && "
            "docker compose -f deploy/compose.dev.yml up -d --wait db",
            pytrace=False,
        )
    admin_conninfo = read_secret(admin_file)
    params = conninfo_to_dict(admin_conninfo)
    name = f"synapse_test_{secrets.token_hex(4)}"

    bootstrap.bootstrap(admin_conninfo, name, secrets_dir)
    database = TestDatabase(
        admin_conninfo=admin_conninfo,
        name=name,
        secrets_dir=secrets_dir,
        host=str(params.get("host", "127.0.0.1")),
        port=int(params.get("port") or 5432),
    )
    migrate.upgrade(database.settings(MIGRATOR))
    try:
        yield database
    finally:
        with psycopg.connect(admin_conninfo, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture(scope="session")
async def api_db(test_database: TestDatabase) -> AsyncIterator[Database]:
    database = Database(test_database.settings("synapse_api"), max_size=4)
    await database.open()
    try:
        yield database
    finally:
        await database.close()
