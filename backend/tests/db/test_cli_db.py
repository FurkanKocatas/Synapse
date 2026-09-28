"""The ``synapse db`` commands against the test database."""

from collections.abc import Iterator

import pytest

from synapse.cli import main
from synapse.dbadmin import migrate
from synapse.dbadmin.roles import MIGRATOR
from synapse.kernel.config import get_settings
from tests.db.conftest import TestDatabase


@pytest.fixture
def migrator_environment(
    test_database: TestDatabase, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    settings = test_database.settings(MIGRATOR)
    monkeypatch.setenv("SYNAPSE_DB_HOST", settings.host)
    monkeypatch.setenv("SYNAPSE_DB_PORT", str(settings.port))
    monkeypatch.setenv("SYNAPSE_DB_NAME", settings.dbname)
    monkeypatch.setenv("SYNAPSE_DB_USER", settings.user)
    monkeypatch.setenv("SYNAPSE_DB_PASSWORD_FILE", str(settings.password_file))
    monkeypatch.setenv("SYNAPSE_LOG_FORMAT", "console")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.usefixtures("migrator_environment")
def test_db_bootstrap_and_migrate_commands(test_database: TestDatabase) -> None:
    admin_file = test_database.secrets_dir / "admin_conninfo"
    assert (
        main(
            [
                "db",
                "bootstrap",
                "--admin-conninfo-file",
                str(admin_file),
                "--secrets-dir",
                str(test_database.secrets_dir),
            ]
        )
        == 0
    )
    assert main(["db", "migrate"]) == 0


def test_database_is_at_the_latest_revision(test_database: TestDatabase) -> None:
    assert migrate.current_revision(test_database.settings(MIGRATOR)) == "0001"
