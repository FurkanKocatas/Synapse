"""Backups, verifications and restores with a scripted Docker: the exact commands, in order, and
what is refused. The containers' writes to the staging directory are played by the script."""

import hashlib
import json
import os
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from synapsectl import backup, cli, doctor, render, secrets
from synapsectl.config import Backup, SynapseConfig, save

SNAPSHOT = "4f3c2b1a" + "0" * 56
NOW = datetime(2026, 10, 6, 2, 30, tzinfo=UTC)
DUMP_BYTES = b"PGDMP fake dump"
ROWS = "documents|3\ntenants|1\nusers|2\n"


class ScriptedDocker:
    """Records every command; answers and side effects keyed by how the command starts, after
    the compose prefix (``docker compose -f FILE --profile backup``)."""

    def __init__(
        self,
        answers: dict[str, tuple[int, str]] | None = None,
        effects: dict[str, Callable[[list[str]], None]] | None = None,
    ) -> None:
        self.answers = answers or {}
        self.effects = effects or {}
        self.calls: list[list[str]] = []

    @staticmethod
    def command(args: Sequence[str]) -> str:
        if list(args[:2]) == ["docker", "compose"]:
            return " ".join(args[6:])
        return " ".join(args)

    def __call__(
        self, args: Sequence[str], *, interactive: bool = False
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        command = self.command(args)
        for prefix, effect in self.effects.items():
            if command.startswith(prefix):
                effect(list(args))
        for prefix, (code, out) in self.answers.items():
            if command.startswith(prefix):
                return subprocess.CompletedProcess(list(args), code, out, "boom" if code else "")
        return subprocess.CompletedProcess(list(args), 0, "", "")

    def commands(self) -> list[str]:
        return [self.command(args) for args in self.calls]


def quiet(_: str) -> None:
    pass


@pytest.fixture
def setup(config: SynapseConfig, tmp_path: Path) -> tuple[SynapseConfig, Path]:
    """An installation with backups set up: an initialised repository, the secrets, its file."""
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "config").write_text("restic", encoding="utf-8")
    configured = SynapseConfig(
        instance=config.instance,
        paths=config.paths,
        backup=Backup(repository=repository, staging_dir=tmp_path / "staging"),
    )
    config.paths.secrets_dir.mkdir(parents=True)
    for name in ("postgres_superuser", "backup_password", "audit_signing_key"):
        (config.paths.secrets_dir / name).write_text(f"{name}-value\n", encoding="utf-8")
    config_file = tmp_path / "synapse.toml"
    save(configured, config_file)
    return configured, config_file


def write_dump(config: SynapseConfig) -> Callable[[list[str]], None]:
    """pg_dump in the container, writing into the staging directory."""

    def effect(_: list[str]) -> None:
        (config.backup.staging_dir / "data" / backup.DUMP).write_bytes(DUMP_BYTES)

    return effect


def backup_answers() -> dict[str, tuple[int, str]]:
    summary = {"message_type": "summary", "snapshot_id": SNAPSHOT, "files_new": 3}
    return {
        "ps --status running -q db": (0, "abc123\n"),
        "run --rm -T pgtools psql --dbname=synapse": (0, "0018_answers\n"),
        "run --rm -T pgtools sh -c pg_restore --data-only": (0, ROWS),
        "run --rm -T restic backup": (0, '{"message_type":"status"}\n' + json.dumps(summary)),
    }


def test_a_backup_dumps_counts_copies_and_keeps_in_order(
    setup: tuple[SynapseConfig, Path],
) -> None:
    config, config_file = setup
    seen: dict[str, bool] = {}

    def at_copy(_: list[str]) -> None:
        data = config.backup.staging_dir / "data"
        seen["dump"] = (data / backup.DUMP).exists()
        seen["secrets"] = (data / "config" / "secrets" / "backup_password").exists()
        seen["config"] = (data / "config" / "synapse.toml").read_text() == config_file.read_text()
        manifest = backup.Manifest.from_json((data / backup.MANIFEST).read_text())
        seen["manifest"] = manifest.rows == {"documents": 3, "tenants": 1, "users": 2}
        seen["sha"] = manifest.dump_sha256 == hashlib.sha256(DUMP_BYTES).hexdigest()

    docker = ScriptedDocker(
        backup_answers(),
        {"run --rm -T pgtools pg_dump": write_dump(config), "run --rm -T restic backup": at_copy},
    )
    snapshot = backup.backup(config, config_file, run=docker, echo=quiet, now=lambda: NOW)
    host = f"synapse-{config.instance.id}"
    assert snapshot == SNAPSHOT
    assert docker.commands() == [
        "ps --status running -q db",
        "run --rm -T pgtools pg_dump --dbname=synapse --format=custom "
        "--file=/backup/data/synapse.dump",
        "run --rm -T pgtools psql --dbname=synapse --no-psqlrc --tuples-only --no-align "
        "--set=ON_ERROR_STOP=1 --command SELECT version_num FROM synapse.alembic_version",
        f"run --rm -T pgtools sh -c {backup.DUMP_ROWS}",
        f"run --rm -T restic backup /backup/data /data/blobs --tag synapse --host {host} --json",
        f"run --rm -T restic forget --tag synapse --host {host} --prune --keep-daily 7 "
        "--keep-weekly 4 --keep-monthly 6",
        "run --rm --no-deps -T api operations record --kind backup --ok --started "
        f"{NOW.isoformat()} --finished {NOW.isoformat()} --details "
        f'{{"snapshot": "4f3c2b1a", "rows": 6, "dump_bytes": {len(DUMP_BYTES)}}}',
    ]
    # the counts come from the dump, of the same moment as its data
    assert seen == dict.fromkeys(("dump", "secrets", "config", "manifest", "sha"), True)
    # nothing of the database or the secrets stays outside the encrypted repository
    assert not (config.backup.staging_dir / "data").exists()
    status = backup.read_status(config)
    assert status["backup"]["ok"] and status["backup_ok"]["snapshot"] == SNAPSHOT


def test_a_run_that_cannot_be_recorded_in_the_database_still_counts(
    setup: tuple[SynapseConfig, Path],
) -> None:
    config, config_file = setup
    said: list[str] = []
    docker = ScriptedDocker(
        {**backup_answers(), "run --rm --no-deps -T api operations record": (1, "")},
        {"run --rm -T pgtools pg_dump": write_dump(config)},
    )
    assert backup.backup(config, config_file, run=docker, echo=said.append, now=lambda: NOW)
    assert any(line.startswith("!! not recorded for the operations page") for line in said)
    assert backup.read_status(config)["backup"]["ok"]


def test_a_failed_backup_is_recorded_for_the_operations_page(
    setup: tuple[SynapseConfig, Path],
) -> None:
    config, config_file = setup
    docker = ScriptedDocker({**backup_answers(), "run --rm -T pgtools pg_dump": (1, "")})
    with pytest.raises(backup.BackupError):
        backup.backup(config, config_file, run=docker, echo=quiet, now=lambda: NOW)
    recorded = docker.commands()[-1]
    assert recorded.startswith("run --rm --no-deps -T api operations record --kind backup --failed")
    assert '"error": "Dump the database: failed (exit 1)"' in recorded


def test_a_backup_needs_the_database_running(setup: tuple[SynapseConfig, Path]) -> None:
    config, config_file = setup
    docker = ScriptedDocker({"ps --status running -q db": (0, "")})
    with pytest.raises(backup.BackupError, match="database is not running"):
        backup.backup(config, config_file, run=docker, echo=quiet, now=lambda: NOW)
    commands = docker.commands()
    assert commands[0] == "ps --status running -q db"
    # nothing else, but recording the failure for the operations page
    assert len(commands) == 2
    assert commands[1].startswith(
        "run --rm --no-deps -T api operations record --kind backup --failed"
    )
    assert backup.read_status(config)["backup"]["ok"] is False


def test_a_failed_backup_is_recorded_and_the_last_good_one_kept(
    setup: tuple[SynapseConfig, Path],
) -> None:
    config, config_file = setup
    good = ScriptedDocker(backup_answers(), {"run --rm -T pgtools pg_dump": write_dump(config)})
    backup.backup(config, config_file, run=good, echo=quiet, now=lambda: NOW)
    failing = ScriptedDocker(
        {**backup_answers(), "run --rm -T restic backup": (1, "")},
        {"run --rm -T pgtools pg_dump": write_dump(config)},
    )
    later = NOW + timedelta(days=1)
    with pytest.raises(backup.BackupError, match="Copy the dump"):
        backup.backup(config, config_file, run=failing, echo=quiet, now=lambda: later)
    status = backup.read_status(config)
    assert status["backup"]["ok"] is False
    assert backup.last_good(config) == NOW


def test_a_backup_needs_a_repository(config: SynapseConfig, tmp_path: Path) -> None:
    with pytest.raises(backup.BackupError, match="no backup repository"):
        backup.backup(config, tmp_path / "synapse.toml", run=ScriptedDocker(), echo=quiet)
    unmounted = SynapseConfig(
        instance=config.instance,
        paths=config.paths,
        backup=Backup(repository=tmp_path / "nas", staging_dir=tmp_path / "staging"),
    )
    with pytest.raises(backup.BackupError, match="is not a backup repository"):
        backup.backup(unmounted, tmp_path / "synapse.toml", run=ScriptedDocker(), echo=quiet)


def test_the_repository_is_set_up_once(setup: tuple[SynapseConfig, Path]) -> None:
    config, _ = setup
    new = ScriptedDocker({"run --rm -T restic cat config": (1, "")})
    backup.init_repository(config, run=new, echo=quiet)
    assert new.commands() == ["run --rm -T restic cat config", "run --rm -T restic init"]
    existing = ScriptedDocker()
    backup.init_repository(config, run=existing, echo=quiet)
    assert existing.commands() == ["run --rm -T restic cat config"]


def restored_data(config: SynapseConfig, **manifest: object) -> Callable[[list[str]], None]:
    """restic restoring the dump, the manifest and the configuration into the staging directory."""

    def effect(_: list[str]) -> None:
        data = config.backup.staging_dir / "data"
        (data / "config" / "secrets").mkdir(parents=True)
        (data / backup.DUMP).write_bytes(DUMP_BYTES)
        for name in ("postgres_superuser", "audit_signing_key"):
            value = "another-key\n" if name == "audit_signing_key" else f"{name}-value\n"
            (data / "config" / "secrets" / name).write_text(value, encoding="utf-8")
        fields: dict[str, Any] = {
            "created": NOW.isoformat(),
            "instance": str(config.instance.id),
            "tenant": str(config.instance.tenant_id),
            "images_version": config.images.version,
            "schema": "0018_answers",
            "rows": {"documents": 3, "tenants": 1, "users": 2},
            "dump_bytes": len(DUMP_BYTES),
            "dump_sha256": hashlib.sha256(DUMP_BYTES).hexdigest(),
        }
        fields.update(manifest)
        (data / backup.MANIFEST).write_text(backup.Manifest(**fields).to_json(), encoding="utf-8")

    return effect


def restore_answers(*, holds_data: bool = True, rows: str = ROWS) -> dict[str, tuple[int, str]]:
    return {
        "run --rm -T restic snapshots": (0, json.dumps([{"id": SNAPSHOT, "short_id": "4f3c2b1a"}])),
        "run --rm -T pgtools psql --dbname=postgres --no-psqlrc --tuples-only --no-align "
        "--set=ON_ERROR_STOP=1 --command SELECT count(*) FROM pg_database": (
            0,
            "1\n" if holds_data else "0\n",
        ),
        "run --rm -T pgtools psql --dbname=synapse --no-psqlrc --tuples-only --no-align "
        "--set=ON_ERROR_STOP=1 --command SELECT to_regclass": (0, "t\n"),
        "run --rm -T pgtools psql --dbname=synapse --no-psqlrc --tuples-only --no-align "
        "--set=ON_ERROR_STOP=1 --command SELECT count(*) FROM synapse.tenants": (0, "1\n"),
        "run --rm -T pgtools psql --dbname=synapse --no-psqlrc --tuples-only --no-align "
        "--set=ON_ERROR_STOP=1 --command SELECT table_name": (0, rows),
    }


def restore_effects(
    config: SynapseConfig, **manifest: object
) -> dict[str, Callable[[list[str]], None]]:
    return {"run --rm -T restic-restore restore": _only_data(restored_data(config, **manifest))}


def _only_data(effect: Callable[[list[str]], None]) -> Callable[[list[str]], None]:
    def wrapped(args: list[str]) -> None:
        if args[-1] == backup.DATA:
            effect(args)

    return wrapped


def test_a_restore_replaces_the_database_and_the_files_in_order(
    setup: tuple[SynapseConfig, Path],
) -> None:
    config, _ = setup
    said: list[str] = []
    docker = ScriptedDocker(restore_answers(), restore_effects(config))
    manifest = backup.restore(config, replace=True, run=docker, echo=said.append)
    psql = "run --rm -T pgtools psql --dbname={} --no-psqlrc --tuples-only --no-align "
    psql += "--set=ON_ERROR_STOP=1 --command {}"
    host = f"synapse-{config.instance.id}"
    assert docker.commands() == [
        f"run --rm -T restic snapshots --tag synapse --host {host} --latest 1 --json",
        f"run --rm -T restic-restore restore {SNAPSHOT} --target / --include /backup/data",
        "stop",
        "up -d --wait db",
        psql.format("postgres", "SELECT count(*) FROM pg_database WHERE datname = 'synapse'"),
        psql.format("synapse", "SELECT to_regclass('synapse.tenants') IS NOT NULL"),
        psql.format("synapse", "SELECT count(*) FROM synapse.tenants"),
        "run --rm bootstrap",
        psql.format("postgres", "DROP DATABASE IF EXISTS synapse WITH (FORCE)"),
        "run --rm -T pgtools pg_restore --dbname=postgres --create --exit-on-error "
        "/backup/data/synapse.dump",
        psql.format("synapse", backup.COUNT_ROWS),
        "run --rm -T --entrypoint find restic-restore /data/blobs -mindepth 1 -delete",
        # the same snapshot as the database, not "latest" looked up again
        f"run --rm -T restic-restore restore {SNAPSHOT} --target / --include /data/blobs",
    ]
    assert manifest.rows == {"documents": 3, "tenants": 1, "users": 2}
    # a secret that differs from the backup's is named, and this machine's kept
    assert any("audit_signing_key" in line and "!!" in line for line in said)
    assert not (config.backup.staging_dir / "data").exists()


def test_a_restore_keeps_a_database_that_holds_data_unless_told(
    setup: tuple[SynapseConfig, Path],
) -> None:
    config, _ = setup
    docker = ScriptedDocker(restore_answers(), restore_effects(config))
    with pytest.raises(backup.BackupError, match="--replace"):
        backup.restore(config, run=docker, echo=quiet)
    assert "run --rm bootstrap" not in docker.commands()
    assert not any("DROP DATABASE" in command for command in docker.commands())
    empty = ScriptedDocker(restore_answers(holds_data=False), restore_effects(config))
    backup.restore(config, run=empty, echo=quiet)
    assert "run --rm bootstrap" in empty.commands()


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ({"instance": "00000000-0000-0000-0000-000000000001"}, "not this one"),
        ({"images_version": "0.9.0"}, "set \\[images\\] version to 0.9.0"),
        ({"dump_sha256": "0" * 64}, "restored dump differs"),
    ],
)
def test_a_restore_refuses_another_installation_version_or_a_damaged_dump(
    setup: tuple[SynapseConfig, Path], manifest: dict[str, str], message: str
) -> None:
    config, _ = setup
    docker = ScriptedDocker(restore_answers(), restore_effects(config, **manifest))
    with pytest.raises(backup.BackupError, match=message):
        backup.restore(config, replace=True, run=docker, echo=quiet)
    assert "stop" not in docker.commands()


def test_a_restore_whose_rows_differ_fails(setup: tuple[SynapseConfig, Path]) -> None:
    config, _ = setup
    docker = ScriptedDocker(
        restore_answers(rows="documents|2\ntenants|1\nusers|2\nextra|0\n"), restore_effects(config)
    )
    with pytest.raises(backup.BackupError, match="documents: 2 rows, expected 3; extra"):
        backup.restore(config, replace=True, run=docker, echo=quiet)
    assert not any("--include /data/blobs" in command for command in docker.commands())


PSQL = "--no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 --command"
EVENT_HASH = "ab" * 32


def verify_answers(rows: str = ROWS, live_hash: str = EVENT_HASH) -> dict[str, tuple[int, str]]:
    return {
        "run --rm -T restic snapshots": (0, json.dumps([{"id": SNAPSHOT}])),
        f"run --rm -T pgtools psql --dbname=synapse_drill {PSQL} SELECT seq": (
            0,
            f"7|{EVENT_HASH}\n",
        ),
        f"run --rm -T pgtools psql --dbname=synapse {PSQL} SELECT encode": (0, f"{live_hash}\n"),
        "run --rm -T pgtools psql --dbname=synapse_drill": (0, rows),
    }


def test_a_verification_restores_into_a_scratch_database_and_drops_it(
    setup: tuple[SynapseConfig, Path],
) -> None:
    config, _ = setup
    docker = ScriptedDocker(verify_answers(), restore_effects(config))
    backup.verify(config, run=docker, echo=quiet, now=lambda: NOW)
    commands = docker.commands()
    tenant = str(config.instance.tenant_id)
    last, same = commands[6:8]
    assert last.startswith(f"run --rm -T pgtools psql --dbname=synapse_drill {PSQL} SELECT seq")
    assert tenant in last
    assert last.endswith("ORDER BY seq DESC LIMIT 1")
    assert same.startswith(f"run --rm -T pgtools psql --dbname=synapse {PSQL} SELECT encode")
    assert tenant in same
    assert same.endswith("AND seq = 7")
    commands[6:8] = ["the backup's last audit event", "the same event in the live audit log"]
    assert commands[2:] == [
        "run --rm -T pgtools psql --dbname=postgres --no-psqlrc --tuples-only --no-align "
        "--set=ON_ERROR_STOP=1 --command DROP DATABASE IF EXISTS synapse_drill WITH (FORCE)",
        "run --rm -T pgtools psql --dbname=postgres --no-psqlrc --tuples-only --no-align "
        "--set=ON_ERROR_STOP=1 --command CREATE DATABASE synapse_drill",
        "run --rm -T pgtools pg_restore --dbname=synapse_drill --single-transaction "
        "--exit-on-error /backup/data/synapse.dump",
        "run --rm -T pgtools psql --dbname=synapse_drill --no-psqlrc --tuples-only --no-align "
        f"--set=ON_ERROR_STOP=1 --command {backup.COUNT_ROWS}",
        "the backup's last audit event",
        "the same event in the live audit log",
        "run --rm -T pgtools psql --dbname=postgres --no-psqlrc --tuples-only --no-align "
        "--set=ON_ERROR_STOP=1 --command DROP DATABASE IF EXISTS synapse_drill WITH (FORCE)",
        "run --rm -T restic check --read-data-subset=5%",
        "run --rm --no-deps -T api operations record --kind backup_verify --ok --started "
        f"{NOW.isoformat()} --finished {NOW.isoformat()} --details "
        '{"rows": 6, "backup_of": "2026-10-06T02:30:00+00:00"}',
    ]
    # the live database is only read, and only for that one audit event
    assert [command for command in docker.commands() if "--dbname=synapse " in command] == [same]
    assert backup.read_status(config)["verify_ok"]["ok"]


@pytest.mark.parametrize(
    ("live_hash", "change"), [("cd" * 32, "differs in"), ("", "is missing from")]
)
def test_a_verification_finds_a_live_audit_log_rewritten_since_the_backup(
    setup: tuple[SynapseConfig, Path], live_hash: str, change: str
) -> None:
    config, _ = setup
    docker = ScriptedDocker(verify_answers(live_hash=live_hash), restore_effects(config))
    with pytest.raises(backup.BackupError, match=f"audit event 7 of the backup .* {change}"):
        backup.verify(config, run=docker, echo=quiet, now=lambda: NOW)
    # the scratch database dropped, then the failure recorded
    assert "DROP DATABASE IF EXISTS synapse_drill" in docker.commands()[-2]
    assert "operations record --kind backup_verify --failed" in docker.commands()[-1]
    assert not backup.read_status(config)["verify"]["ok"]


def test_a_failed_verification_still_drops_the_scratch_database(
    setup: tuple[SynapseConfig, Path],
) -> None:
    config, _ = setup
    docker = ScriptedDocker(
        {**verify_answers(), "run --rm -T pgtools pg_restore": (1, "")}, restore_effects(config)
    )
    with pytest.raises(backup.BackupError, match="Restore the dump"):
        backup.verify(config, run=docker, echo=quiet, now=lambda: NOW)
    assert docker.commands()[-2].endswith("DROP DATABASE IF EXISTS synapse_drill WITH (FORCE)")
    assert backup.read_status(config)["verify"]["ok"] is False


def test_a_new_machine_gets_its_configuration_and_secrets_from_the_repository(
    setup: tuple[SynapseConfig, Path], tmp_path: Path
) -> None:
    config, config_file = setup
    target = tmp_path / "new" / "synapse.toml"

    def restic_restore(args: list[str]) -> None:
        scratch = Path(next(a for a in args if a.endswith(":/restore")).rsplit(":", 1)[0])
        source = scratch / "backup" / "data" / "config"
        (source / "secrets").mkdir(parents=True)
        (source / "synapse.toml").write_text(config_file.read_text(), encoding="utf-8")
        (source / "secrets" / "backup_password").write_text("p\n", encoding="utf-8")

    docker = ScriptedDocker(effects={"docker run --rm --network none": restic_restore})
    password = tmp_path / "password"
    password.write_text("p\n", encoding="utf-8")
    # the secrets directory of the restored synapse.toml is this test's, so move it away first
    for item in config.paths.secrets_dir.iterdir():
        item.unlink()
    restored = backup.restore_configuration(
        config.backup.repository or tmp_path, password, target, run=docker, echo=quiet
    )
    assert restored.instance.id == config.instance.id
    assert target.read_text() == config_file.read_text()
    assert (config.paths.secrets_dir / "backup_password").read_text() == "p\n"
    [call] = docker.calls
    assert render.RESTIC_IMAGE in call and "--include" in call
    with pytest.raises(backup.BackupError, match="exists"):
        backup.restore_configuration(tmp_path, password, target, run=docker, echo=quiet)


def test_the_schedule_is_nightly_and_verified_each_quarter(
    setup: tuple[SynapseConfig, Path], tmp_path: Path
) -> None:
    config, config_file = setup
    units = backup.schedule_units(config, config_file)
    assert "OnCalendar=*-*-* 02:30:00" in units["synapse-backup.timer"]
    assert "OnCalendar=*-01,04,07,10-01 05:30:00" in units["synapse-backup-verify.timer"]
    assert f"--config {config_file} backup run" in units["synapse-backup.service"]
    late = SynapseConfig(
        instance=config.instance,
        paths=config.paths,
        backup=Backup(repository=config.backup.repository, time="23:15"),
    )
    assert (
        "*-01,04,07,10-01 02:15:00"
        in backup.schedule_units(late, config_file)["synapse-backup-verify.timer"]
    )
    docker = ScriptedDocker()
    backup.install_schedule(config, config_file, units_dir=tmp_path, run=docker, echo=quiet)
    assert sorted(p.name for p in tmp_path.glob("synapse-backup*")) == sorted(units)
    assert docker.commands() == [
        "systemctl daemon-reload",
        "systemctl enable --now synapse-backup.timer synapse-backup-verify.timer",
    ]


def test_doctor_reports_backups(setup: tuple[SynapseConfig, Path], config: SynapseConfig) -> None:
    configured, _ = setup
    assert doctor.check_backup(config).status is doctor.Status.WARN  # not set up
    assert "no backup has succeeded" in doctor.check_backup(configured).detail
    backup.record(configured, "backup", NOW, ok=True, detail="fine", snapshot=SNAPSHOT)
    assert doctor.check_backup(configured, now=NOW + timedelta(hours=20)).status is doctor.Status.OK
    old = doctor.check_backup(configured, now=NOW + timedelta(days=3))
    assert (old.status, old.detail) == (doctor.Status.WARN, "the last good backup is 3 days old")
    backup.record(configured, "backup", NOW, ok=False, detail="disk full")
    assert "failed: disk full" in doctor.check_backup(configured, now=NOW).detail
    (configured.backup.repository or Path()).joinpath("config").unlink()
    assert "holds no repository" in doctor.check_backup(configured).detail


def test_the_backup_commands(
    monkeypatch: pytest.MonkeyPatch,
    setup: tuple[SynapseConfig, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, config_file = setup
    done: list[str] = []

    def take(_loaded: SynapseConfig, path: Path) -> str:
        done.append(f"backup {path.name}")
        return SNAPSHOT

    def check(_loaded: SynapseConfig, *, snapshot: str) -> None:
        done.append(f"verify {snapshot}")

    def listed(_loaded: SynapseConfig) -> list[dict[str, Any]]:
        return [{"short_id": "4f3c2b1a", "time": "2026-10-06T02:30:00.123+03:00"}]

    monkeypatch.setattr(backup, "backup", take)
    monkeypatch.setattr(backup, "verify", check)
    monkeypatch.setattr(backup, "snapshots", listed)
    command = ["--config", str(config_file), "backup"]
    assert cli.main(command) == 0
    assert cli.main([*command, "verify", "--snapshot", "4f3c2b1a"]) == 0
    assert cli.main([*command, "list"]) == 0
    assert done == ["backup synapse.toml", "verify 4f3c2b1a"]
    assert "4f3c2b1a  2026-10-06T02:30:00" in capsys.readouterr().out

    def broken(*_args: object, **_kwargs: object) -> str:
        raise backup.BackupError("Dump the database: failed (exit 1)")

    monkeypatch.setattr(backup, "backup", broken)
    assert cli.main(command) == 1
    assert "Dump the database: failed" in capsys.readouterr().err


def test_a_restore_asks_for_the_installation_slug(
    monkeypatch: pytest.MonkeyPatch, setup: tuple[SynapseConfig, Path]
) -> None:
    _, config_file = setup
    restored: list[tuple[str, bool]] = []

    def restore(_loaded: SynapseConfig, *, snapshot: str, replace: bool) -> None:
        restored.append((snapshot, replace))

    monkeypatch.setattr(backup, "restore", restore)
    answers = iter(["another", "demo"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    command = ["--config", str(config_file), "restore"]
    assert cli.main(command) == 1
    assert restored == []
    assert cli.main([*command, "--replace"]) == 0
    assert cli.main([*command, "--yes", "--snapshot", "4f3c2b1a"]) == 0
    assert restored == [("latest", True), ("4f3c2b1a", False)]

    def refused(*_args: object, **_kwargs: object) -> None:
        raise backup.BackupError("the database holds an installation's data")

    monkeypatch.setattr(backup, "restore", refused)
    assert cli.main([*command, "--yes"]) == 1


def test_a_new_machine_restores_its_configuration_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "etc" / "synapse.toml"
    seen: list[tuple[str, str, Path, str]] = []

    def restore_configuration(
        repository: Path, password_file: Path, config_file: Path, *, snapshot: str
    ) -> None:
        seen.append((repository.name, password_file.name, config_file, snapshot))

    monkeypatch.setattr(backup, "restore_configuration", restore_configuration)
    command = ["--config", str(target), "restore", "--configuration-from", str(tmp_path / "nas")]
    assert cli.main(command) == 1
    assert "--password-file" in capsys.readouterr().err
    assert cli.main([*command, "--password-file", str(tmp_path / "password")]) == 0
    assert seen == [("nas", "password", target, "latest")]

    def refused(*_args: object, **_kwargs: object) -> None:
        raise backup.BackupError(f"{target} exists; this machine is set up already")

    monkeypatch.setattr(backup, "restore_configuration", refused)
    assert cli.main([*command, "--password-file", str(tmp_path / "password")]) == 1


def test_apply_schedules_the_backups_as_root_under_systemd(
    monkeypatch: pytest.MonkeyPatch,
    setup: tuple[SynapseConfig, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, config_file = setup
    scheduled: list[Path] = []
    monkeypatch.setattr(cli, "apply", lambda _loaded, admin: None)
    monkeypatch.setattr(backup, "install_schedule", lambda _loaded, path: scheduled.append(path))
    monkeypatch.setattr(cli, "SYSTEMD_RUNTIME", tmp_path)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    assert cli.main(["--config", str(config_file), "apply"]) == 0
    assert "Backups are not scheduled" in capsys.readouterr().out
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert cli.main(["--config", str(config_file), "apply"]) == 0
    assert scheduled == [config_file.resolve()]


def test_backup_init_sets_up_an_installation_that_had_no_backups(
    monkeypatch: pytest.MonkeyPatch, config: SynapseConfig, tmp_path: Path
) -> None:
    secrets.generate(config)
    render.write(config, render.render(config))
    configured = SynapseConfig(
        instance=config.instance,
        paths=config.paths,
        backup=Backup(repository=tmp_path / "repository", staging_dir=tmp_path / "staging"),
    )
    config_file = tmp_path / "synapse.toml"
    save(configured, config_file)
    # what the repository's set-up finds: its password, and the containers it runs
    found: list[tuple[bool, bool]] = []

    def init_repository(loaded: SynapseConfig) -> None:
        compose = yaml.safe_load((loaded.paths.render_dir / "compose.yml").read_text())
        password = loaded.paths.secrets_dir / "backup_password"
        found.append((password.is_file(), "restic" in compose["services"]))

    monkeypatch.setattr(backup, "init_repository", init_repository)
    assert cli.main(["--config", str(config_file), "backup", "init"]) == 0
    assert found == [(True, True)]
    assert doctor.check_secrets(configured).status is doctor.Status.OK
    assert doctor.check_rendered(configured).status is doctor.Status.OK


def test_the_backup_containers_are_rendered_only_when_backups_are_set_up(
    setup: tuple[SynapseConfig, Path], config: SynapseConfig
) -> None:
    configured, _ = setup
    assert "restic" not in yaml.safe_load(render.render(config).files["compose.yml"])["services"]
    text = render.render(configured).files["compose.yml"]
    assert "&id" not in text  # written out in full, without YAML anchors
    compose = yaml.safe_load(text)
    services = compose["services"]
    assert services["restic"]["network_mode"] == "none"
    assert services["restic"]["profiles"] == ["backup"]
    assert "blobs:/data/blobs:ro" in services["restic"]["volumes"]
    assert "blobs:/data/blobs" in services["restic-restore"]["volumes"]
    assert "$$(cat /run/secrets/postgres_superuser)" in services["pgtools"]["entrypoint"][2]
    assert "backup_password" in compose["secrets"]


def test_backup_settings_are_checked(config: SynapseConfig, tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="absolute"):
        Backup(repository=Path("relative/dir"))
    with pytest.raises(ValidationError, match=r"inside backup\.staging_dir"):
        Backup(repository=tmp_path / "staging" / "repo", staging_dir=tmp_path / "staging")
    with pytest.raises(ValidationError):
        Backup(repository=tmp_path / "repo", time="24:00")
    configured = SynapseConfig(
        instance=config.instance, paths=config.paths, backup=Backup(repository=tmp_path / "r")
    )
    assert "backup_password" in secrets.generate(configured)
    assert "backup_password" not in [f.name for f in secrets.required_files(config)]
