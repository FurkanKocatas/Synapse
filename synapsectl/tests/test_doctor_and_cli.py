import os
import socket
import subprocess
from pathlib import Path

import pytest

from synapsectl import cli, doctor, render, secrets
from synapsectl import config as cfg
from synapsectl.apply import ApplyError
from synapsectl.config import SynapseConfig, Tier
from synapsectl.doctor import Status


def prepared(config: SynapseConfig) -> SynapseConfig:
    secrets.generate(config)
    render.write(config, render.render(config))
    return config


def test_rendered_files_match_after_render(config: SynapseConfig) -> None:
    assert doctor.check_rendered(prepared(config)).status is Status.OK


def test_hand_edits_and_stale_renders_are_reported(config: SynapseConfig) -> None:
    prepared(config)
    compose = config.paths.render_dir / "compose.yml"
    compose.write_text(compose.read_text(encoding="utf-8") + "# tweak\n", encoding="utf-8")
    edited = doctor.check_rendered(config)
    assert edited.status is Status.FAIL
    assert "edited by hand: compose.yml" in edited.detail

    render.write(config, render.render(config))
    changed = config.model_copy(update={"hardware": Tier.CPU_32})
    assert "differ from what synapse.toml" in doctor.check_rendered(changed).detail


def test_missing_render_is_reported(config: SynapseConfig) -> None:
    assert "not rendered" in doctor.check_rendered(config).detail


def test_secret_problems_are_reported(config: SynapseConfig) -> None:
    assert doctor.check_secrets(config).status is Status.FAIL  # nothing generated yet
    prepared(config)
    assert doctor.check_secrets(config).status is Status.OK
    exposed = config.paths.secrets_dir / "totp_key"
    exposed.chmod(0o444)
    result = doctor.check_secrets(config)
    assert result.status is Status.FAIL
    assert "totp_key readable by others" in result.detail


def test_cpu_without_avx2_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    cpuinfo = tmp_path / "cpuinfo"
    cpuinfo.write_text("flags : fpu sse sse2 avx\n", encoding="utf-8")
    assert doctor.check_cpu(cpuinfo).status is Status.FAIL
    cpuinfo.write_text("flags : fpu sse sse2 avx avx2 fma\n", encoding="utf-8")
    assert doctor.check_cpu(cpuinfo).status is Status.OK


def test_too_little_memory_fails(monkeypatch: pytest.MonkeyPatch, config: SynapseConfig) -> None:
    pages = {"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 8 * 1024**3 // 4096}
    monkeypatch.setattr(os, "sysconf", lambda name: pages[name])
    assert doctor.check_memory(config).status is Status.FAIL


def test_cli_init_render_and_doctor(config: SynapseConfig, tmp_path: Path) -> None:
    source = tmp_path / "answers.toml"
    cfg.save(config, source)
    target = tmp_path / "etc" / "synapse.toml"
    assert cli.main(["--config", str(target), "init", "--from", str(source)]) == 0
    assert cli.main(["--config", str(target), "init", "--from", str(source)]) == 1  # exists
    assert cli.main(["--config", str(target), "render"]) == 0
    assert doctor.check_rendered(cfg.load(target)).status is Status.OK


def test_cli_reports_a_missing_configuration(tmp_path: Path) -> None:
    assert cli.main(["--config", str(tmp_path / "absent.toml"), "doctor"]) == 1


def completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


def test_docker_check(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = {"version": completed(0, "29.4.3\n"), "compose": completed(0, "2.40.0\n")}
    monkeypatch.setattr(doctor, "_run", lambda command: answers[command[1]])
    assert doctor.check_docker().status is Status.OK
    answers["compose"] = completed(1)
    assert "Compose plugin" in doctor.check_docker().detail
    monkeypatch.setattr(doctor, "_run", lambda _command: None)
    assert doctor.check_docker().status is Status.FAIL


def test_port_check_distinguishes_our_stack_from_others() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert doctor.check_port(port, running=False).status is Status.FAIL
        assert doctor.check_port(port, running=True).status is Status.OK
    assert doctor.check_port(port, running=False).detail == "free"


def test_all_checks_run_and_report(monkeypatch: pytest.MonkeyPatch, config: SynapseConfig) -> None:
    monkeypatch.setattr(doctor, "_run", lambda _command: completed(0, "1\n"))
    names = [check.name for check in doctor.run_checks(prepared(config))]
    assert names[:4] == ["docker", "cpu", "memory", "disk"]
    assert "secrets" in names
    assert "rendered files" in names


def test_cli_doctor_exit_code_follows_failures(
    monkeypatch: pytest.MonkeyPatch, config: SynapseConfig, tmp_path: Path
) -> None:
    path = tmp_path / "synapse.toml"
    cfg.save(prepared(config), path)
    ok = doctor.Check("x", Status.OK, "")
    monkeypatch.setattr(doctor, "run_checks", lambda *_args, **_kwargs: [ok])
    assert cli.main(["--config", str(path), "doctor"]) == 0
    failed = doctor.Check("x", Status.FAIL, "")
    monkeypatch.setattr(doctor, "run_checks", lambda *_args, **_kwargs: [ok, failed])
    assert cli.main(["--config", str(path), "doctor"]) == 1


def test_cli_reports_an_invalid_configuration(tmp_path: Path) -> None:
    path = tmp_path / "synapse.toml"
    path.write_text('hardware = "cpu-64"\n', encoding="utf-8")
    assert cli.main(["--config", str(path), "render"]) == 1


def test_cli_apply_needs_both_administrator_fields(
    config: SynapseConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "synapse.toml"
    cfg.save(config, target)
    code = cli.main(["--config", str(target), "apply", "--admin-email", "a@demo.local"])
    assert code == 1
    assert "--admin-email and --admin-name together" in capsys.readouterr().err


def test_cli_apply_reports_a_failed_step(
    config: SynapseConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "synapse.toml"
    cfg.save(config, target)

    def fail(*_: object, **__: object) -> None:
        raise ApplyError("Start the database: failed (exit 1)")

    monkeypatch.setattr(cli, "apply", fail)
    assert cli.main(["--config", str(target), "apply"]) == 1
    assert "Start the database: failed" in capsys.readouterr().err
