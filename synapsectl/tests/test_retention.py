"""Audit retention from the host (ADR 0022): the container it runs and the outcome it records,
the timer, doctor's check, the periods and the password it renders, the secret apply adds, and
a backup verification that finds an event retention removed."""

import os
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from synapsectl import backup, cli, doctor, render, retention, secrets
from synapsectl.apply import apply
from synapsectl.config import Audit, Backup, SynapseConfig
from tests.test_apply import LATER_RUN, FakeDocker, healthy
from tests.test_backup import (
    NOW,
    PSQL,
    ScriptedDocker,
    quiet,
    restore_effects,
    verify_answers,
)

REPORT = '{"events": 12, "texts": 30, "through_seq": 12}'


def test_prune_runs_the_retention_container_and_records_the_outcome(
    setup: tuple[SynapseConfig, Path],
) -> None:
    config, _ = setup
    docker = ScriptedDocker({"run --rm -T retention": (0, "a log line\n" + REPORT + "\n")})
    removed = retention.prune(config, run=docker, echo=quiet, now=lambda: NOW)
    assert removed == {"events": 12, "texts": 30, "through_seq": 12}
    assert docker.commands() == ["run --rm -T retention"]
    compose = str(config.paths.render_dir / "compose.yml")
    assert docker.calls[0][:6] == ["docker", "compose", "-f", compose, "--profile", "backup"]
    status = backup.read_status(config)[retention.KIND]
    assert (status["ok"], status["detail"]) == (True, "12 events, 30 question texts removed")

    failing = ScriptedDocker({"run --rm -T retention": (1, "")})
    with pytest.raises(backup.BackupError, match="audit retention"):
        retention.prune(config, run=failing, echo=quiet, now=lambda: NOW + timedelta(days=1))
    assert not backup.read_status(config)[retention.KIND]["ok"]
    assert backup.last_good(config, retention.KIND) == NOW


def test_the_timer_runs_an_hour_after_the_backup(
    setup: tuple[SynapseConfig, Path], tmp_path: Path
) -> None:
    config, config_file = setup
    units = retention.schedule_units(config, config_file)
    assert "OnCalendar=*-*-* 03:30:00" in units["synapse-audit-prune.timer"]
    assert f"--config {config_file} audit prune" in units["synapse-audit-prune.service"]
    late = SynapseConfig(instance=config.instance, paths=config.paths, backup=Backup(time="23:15"))
    timer = retention.schedule_units(late, config_file)["synapse-audit-prune.timer"]
    assert "OnCalendar=*-*-* 00:15:00" in timer
    docker = ScriptedDocker()
    retention.install_schedule(config, config_file, units_dir=tmp_path, run=docker, echo=quiet)
    assert sorted(p.name for p in tmp_path.glob("synapse-audit*")) == sorted(units)
    assert docker.commands() == [
        "systemctl daemon-reload",
        "systemctl enable --now synapse-audit-prune.timer",
    ]


def test_doctor_reports_retention(setup: tuple[SynapseConfig, Path]) -> None:
    config, _ = setup
    assert "has not run yet" in doctor.check_retention(config).detail
    backup.record(config, retention.KIND, NOW, ok=True, detail="fine")
    assert doctor.check_retention(config, now=NOW + timedelta(days=2)).status is doctor.Status.OK
    old = doctor.check_retention(config, now=NOW + timedelta(days=8))
    assert (old.status, old.detail) == (doctor.Status.WARN, "the last good run is 8 days old")
    backup.record(config, retention.KIND, NOW, ok=False, detail="the database is down")
    assert "failed: the database is down" in doctor.check_retention(config, now=NOW).detail


def test_the_periods_reach_the_migrator_and_one_container_holds_the_password(
    config: SynapseConfig,
) -> None:
    chosen = SynapseConfig(
        instance=config.instance,
        paths=config.paths,
        audit=Audit(keep_events_days=730, keep_question_days=365),
    )
    services = yaml.safe_load(render.render(chosen).files["compose.yml"])["services"]
    migrate = services["migrate"]["environment"]
    assert migrate["SYNAPSE_AUDIT_KEEP_EVENTS_DAYS"] == "730"
    assert migrate["SYNAPSE_AUDIT_KEEP_QUESTION_DAYS"] == "365"
    pruning = services["retention"]
    assert (pruning["profiles"], pruning["command"]) == (["backup"], ["audit", "prune"])
    assert pruning["environment"]["SYNAPSE_DB_USER"] == "synapse_retention"
    holders = [
        name for name, s in services.items() if "db_synapse_retention" in s.get("secrets", [])
    ]
    assert holders == ["bootstrap", "retention"]  # bootstrap sets the role's password
    for wrong in (
        {"keep_events_days": 60},
        {"keep_question_days": 20},
        {"keep_events_days": 100, "keep_question_days": 200},
    ):
        with pytest.raises(ValidationError):
            Audit.model_validate(wrong)


def test_apply_creates_the_secrets_a_release_adds(config: SynapseConfig) -> None:
    secrets.generate(config)
    added = config.paths.secrets_dir / "db_synapse_retention"
    added.unlink()
    said: list[str] = []
    apply(config, run=FakeDocker(LATER_RUN), checks=healthy, echo=said.append)
    assert added.is_file()
    assert said[0] == "== Created the secrets this release adds: db_synapse_retention"
    said.clear()
    apply(config, run=FakeDocker(LATER_RUN), checks=healthy, echo=said.append)
    assert not any("Created the secrets" in line for line in said)


def test_the_commands_and_apply_schedule_retention(
    monkeypatch: pytest.MonkeyPatch,
    setup: tuple[SynapseConfig, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, config_file = setup
    pruned: list[SynapseConfig] = []

    def prune(loaded: SynapseConfig) -> dict[str, int]:
        pruned.append(loaded)
        return {}

    monkeypatch.setattr(retention, "prune", prune)
    assert cli.main(["--config", str(config_file), "audit", "prune"]) == 0
    assert len(pruned) == 1

    def fails(_: SynapseConfig) -> dict[str, int]:
        raise backup.BackupError("audit retention: the database is down")

    monkeypatch.setattr(retention, "prune", fails)
    assert cli.main(["--config", str(config_file), "audit", "prune"]) == 1
    assert "the database is down" in capsys.readouterr().err

    scheduled: list[Path] = []
    monkeypatch.setattr(cli, "apply", lambda _loaded, admin: None)
    monkeypatch.setattr(backup, "install_schedule", lambda _loaded, path: None)
    monkeypatch.setattr(retention, "install_schedule", lambda _loaded, path: scheduled.append(path))
    monkeypatch.setattr(cli, "SYSTEMD_RUNTIME", tmp_path)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    assert cli.main(["--config", str(config_file), "apply"]) == 0
    assert "Audit retention is not scheduled" in capsys.readouterr().out
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert cli.main(["--config", str(config_file), "apply"]) == 0
    assert scheduled == [config_file.resolve()]


def test_a_verification_accepts_a_backup_event_retention_removed(
    setup: tuple[SynapseConfig, Path],
) -> None:
    config, _ = setup
    said: list[str] = []
    answers = {
        # the backup's last event (7) is gone from the live log, and the anchor accounts for it
        **verify_answers(live_hash=""),
        f"run --rm -T pgtools psql --dbname=synapse {PSQL} SELECT coalesce": (0, "9\n"),
    }
    docker = ScriptedDocker(answers, restore_effects(config))
    backup.verify(config, run=docker, echo=said.append, now=lambda: NOW)
    assert "== audit event 7 of the backup is past its period, removed by retention" in said
    assert backup.read_status(config)["verify"]["ok"]
