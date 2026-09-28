"""The ``synapse db`` commands against the test database."""

import json
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory

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
    settings = test_database.settings(MIGRATOR)
    head = ScriptDirectory.from_config(migrate.alembic_config(settings)).get_current_head()
    assert head is not None
    assert migrate.current_revision(settings) == head


@pytest.mark.usefixtures("migrator_environment")
def test_tenant_and_user_commands(
    test_database: TestDatabase,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    api = test_database.settings("synapse_api")
    monkeypatch.setenv("SYNAPSE_DB_USER", api.user)
    monkeypatch.setenv("SYNAPSE_DB_PASSWORD_FILE", str(api.password_file))
    monkeypatch.setenv("SYNAPSE_CSRF_KEY_FILE", str(test_database.secrets_dir / "csrf_key"))
    monkeypatch.setenv("SYNAPSE_TOTP_KEY_FILE", str(test_database.secrets_dir / "totp_key"))
    get_settings.cache_clear()

    chosen = uuid.uuid4()
    assert (
        main(
            [
                "tenant",
                "create",
                "--slug",
                f"cli-{chosen.hex[:8]}",
                "--name",
                "CLI",
                "--id",
                str(chosen),
            ]
        )
        == 0
    )
    tenant_id = capsys.readouterr().out.strip().splitlines()[-1]
    assert tenant_id == str(chosen)
    monkeypatch.setenv("SYNAPSE_TENANT_ID", str(uuid.UUID(tenant_id)))
    get_settings.cache_clear()

    password = tmp_path / "password"
    arguments = [
        "user",
        "create",
        "--email",
        "cli@example.org",
        "--name",
        "CLI User",
        "--role",
        "member",
        "--password-file",
        str(password),
    ]
    password.write_text("too short", encoding="utf-8")
    assert main(arguments) == 1
    assert "password_too_short" in capsys.readouterr().err

    password.write_text("a sufficiently long passphrase", encoding="utf-8")
    assert main(arguments) == 0
    uuid.UUID(capsys.readouterr().out.strip().splitlines()[-1])


def test_user_command_needs_a_tenant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SYNAPSE_TENANT_ID", raising=False)
    get_settings.cache_clear()
    password = tmp_path / "password"
    password.write_text("a sufficiently long passphrase", encoding="utf-8")
    code = main(
        [
            "user",
            "create",
            "--email",
            "x@example.org",
            "--name",
            "X",
            "--role",
            "member",
            "--password-file",
            str(password),
        ]
    )
    get_settings.cache_clear()
    assert code == 1
    assert "SYNAPSE_TENANT_ID" in capsys.readouterr().err


@pytest.mark.usefixtures("migrator_environment")
def test_audit_commands(
    test_database: TestDatabase, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    api = test_database.settings("synapse_api")
    for name, value in {
        "SYNAPSE_DB_USER": api.user,
        "SYNAPSE_DB_PASSWORD_FILE": str(api.password_file),
        "SYNAPSE_AUDIT_SIGNING_KEY_FILE": str(test_database.secrets_dir / "audit_signing_key"),
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    assert main(["tenant", "create", "--slug", f"aud-{uuid.uuid4().hex[:8]}", "--name", "A"]) == 0
    tenant_id = capsys.readouterr().out.strip().splitlines()[-1]
    monkeypatch.setenv("SYNAPSE_TENANT_ID", tenant_id)
    get_settings.cache_clear()

    assert main(["audit", "checkpoint"]) == 1  # nothing to sign yet
    assert "empty" in capsys.readouterr().err

    password = test_database.secrets_dir / "db_synapse_api"  # any long random text will do
    monkeypatch.setenv("SYNAPSE_CSRF_KEY_FILE", str(test_database.secrets_dir / "csrf_key"))
    monkeypatch.setenv("SYNAPSE_TOTP_KEY_FILE", str(test_database.secrets_dir / "totp_key"))
    get_settings.cache_clear()
    create = [
        "user",
        "create",
        "--email",
        "audit@example.org",
        "--name",
        "Audit",
        "--role",
        "auditor",
        "--password-file",
        str(password),
    ]
    assert main(create) == 0
    capsys.readouterr()

    assert main(["audit", "verify"]) == 0
    assert '"ok": true' in capsys.readouterr().out
    assert main(["audit", "checkpoint"]) == 0
    checkpoint = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert '"seq":1' in checkpoint["payload"]
    get_settings.cache_clear()


@pytest.mark.usefixtures("migrator_environment")
def test_installer_steps_can_run_again(
    test_database: TestDatabase,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    api = test_database.settings("synapse_api")
    monkeypatch.setenv("SYNAPSE_DB_USER", api.user)
    monkeypatch.setenv("SYNAPSE_DB_PASSWORD_FILE", str(api.password_file))
    monkeypatch.setenv("SYNAPSE_CSRF_KEY_FILE", str(test_database.secrets_dir / "csrf_key"))
    monkeypatch.setenv("SYNAPSE_TOTP_KEY_FILE", str(test_database.secrets_dir / "totp_key"))
    get_settings.cache_clear()
    chosen = str(uuid.uuid4())
    slug = f"again-{chosen[:8]}"
    tenant = ["tenant", "create", "--slug", slug, "--name", "Again", "--id", chosen, "--if-missing"]
    assert main(tenant) == 0
    assert main(tenant) == 0
    assert capsys.readouterr().out.split() == [chosen, chosen]
    other_slug = [*tenant[:3], "someone-else", *tenant[4:]]
    assert main(other_slug) == 1
    assert "exists with slug" in capsys.readouterr().err
    assert main(["tenant", "create", "--slug", "x", "--name", "X", "--if-missing"]) == 1
    assert "--if-missing needs --id" in capsys.readouterr().err

    monkeypatch.setenv("SYNAPSE_TENANT_ID", chosen)
    get_settings.cache_clear()
    password = tmp_path / "password"
    password.write_text("a sufficiently long passphrase", encoding="utf-8")
    admin = [
        "user",
        "create",
        "--email",
        "first@example.org",
        "--name",
        "First",
        "--role",
        "admin",
        "--password-file",
        str(password),
        "--unless-admin-exists",
    ]
    assert main(["user", "admins"]) == 0
    assert capsys.readouterr().out.strip() == "0"
    assert main(admin) == 0
    uuid.UUID(capsys.readouterr().out.strip())
    assert main(["user", "admins"]) == 0
    assert capsys.readouterr().out.strip() == "1"
    second = [*admin]
    second[3] = "second@example.org"
    assert main(second) == 0
    assert capsys.readouterr().out.strip() == "skipped: an active administrator exists"
    get_settings.cache_clear()
