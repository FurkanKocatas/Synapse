import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from synapsectl import doctor
from synapsectl.apply import CONTAINER_PASSWORD_FILE, ApplyError, FirstAdmin, apply
from synapsectl.config import SynapseConfig


class FakeDocker:
    """Records every command and answers from a script keyed by the compose arguments."""

    def __init__(self, answers: dict[str, tuple[int, str]] | None = None) -> None:
        self.answers = answers or {}
        self.calls: list[tuple[list[str], bool]] = []

    def __call__(
        self, args: Sequence[str], *, interactive: bool = False
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(args), interactive))
        compose_args = " ".join(args[4:])
        for prefix, (code, out) in self.answers.items():
            if compose_args.startswith(prefix):
                return subprocess.CompletedProcess(list(args), code, out, "boom" if code else "")
        return subprocess.CompletedProcess(list(args), 0, "", "")

    def commands(self) -> list[str]:
        """The compose commands, without "docker compose -f FILE"."""
        return [" ".join(args[4:]) for args, _ in self.calls if args[:2] == ["docker", "compose"]]


def healthy(_: SynapseConfig, **__: Any) -> list[doctor.Check]:
    return [doctor.Check("docker", doctor.Status.OK, "fine")]


def quiet(_: str) -> None:
    pass


FIRST_RUN = {"run --rm --no-deps -T api user admins": (0, "0\n")}
LATER_RUN = {"run --rm --no-deps -T api user admins": (0, "1\n"), "ps": (0, "abc123\n")}


def test_first_run_installs_everything_in_order(config: SynapseConfig) -> None:
    docker = FakeDocker(FIRST_RUN)
    admin = FirstAdmin("admin@demo.local", "Demo Admin")
    apply(config, admin=admin, run=docker, checks=healthy, echo=quiet)
    tenant = config.instance.tenant_id
    assert docker.commands() == [
        "ps --status running -q",
        "up -d --wait db",
        "run --rm bootstrap",
        "run --rm migrate",
        f"run --rm --no-deps -T api tenant create --slug demo --name Demo Kurum --id {tenant}"
        " --if-missing",
        "run --rm --no-deps -T api user admins",
        "run --rm --no-deps api user create --email admin@demo.local --name Demo Admin"
        " --role admin --locale tr --unless-admin-exists",
        "up -d --wait",
    ]
    # The password prompt needs the terminal; nothing else gets it.
    assert [interactive for _, interactive in docker.calls].count(True) == 1
    assert docker.calls[0][0][:4] == [
        "docker",
        "compose",
        "-f",
        str(config.paths.render_dir / "compose.yml"),
    ]
    assert (config.paths.render_dir / "compose.yml").exists()


def test_a_later_run_skips_the_administrator_and_knows_the_stack_runs(
    config: SynapseConfig,
) -> None:
    docker = FakeDocker(LATER_RUN)
    seen: list[bool] = []

    def checks(_: SynapseConfig, *, stack_running: bool) -> list[doctor.Check]:
        seen.append(stack_running)
        return healthy(_)

    apply(config, run=docker, checks=checks, echo=quiet)
    assert not any("user create" in command for command in docker.commands())
    assert seen == [True, True]


def test_an_installation_on_the_earlier_network_goes_down_first(config: SynapseConfig) -> None:
    # The network inspection's arguments, past "docker network inspect NAME", are its key.
    docker = FakeDocker({**LATER_RUN, "--format": (0, "false\n")})
    apply(config, run=docker, checks=healthy, echo=quiet)
    inspect = next(args for args, _ in docker.calls if args[1] == "network")
    assert inspect[:4] == ["docker", "network", "inspect", "synapse-demo_internal"]
    commands = docker.commands()
    assert commands.index("down") < commands.index("up -d --wait db")


def test_an_installation_on_the_internal_network_stays_up(config: SynapseConfig) -> None:
    for answer in ((0, "true\n"), (1, "")):  # internal already, or no network yet
        docker = FakeDocker({**LATER_RUN, "--format": answer})
        apply(config, run=docker, checks=healthy, echo=quiet)
        assert "down" not in docker.commands()


def test_the_first_run_needs_an_administrator(config: SynapseConfig) -> None:
    docker = FakeDocker(FIRST_RUN)
    with pytest.raises(ApplyError, match="--admin-email"):
        apply(config, run=docker, checks=healthy, echo=quiet)
    assert "up -d --wait" not in docker.commands()


def test_a_scripted_install_reads_the_password_from_a_mounted_file(
    config: SynapseConfig, tmp_path: Path
) -> None:
    password = tmp_path / "admin-password"
    password.write_text("a long enough passphrase", encoding="utf-8")
    docker = FakeDocker(FIRST_RUN)
    apply(
        config,
        admin=FirstAdmin("a@demo.local", "A", password),
        run=docker,
        checks=healthy,
        echo=quiet,
    )
    create, interactive = next(
        (args, i) for args, i in docker.calls if "create" in args and "user" in args
    )
    assert f"{password.resolve()}:{CONTAINER_PASSWORD_FILE}:ro" in create
    assert create[create.index("--password-file") + 1] == CONTAINER_PASSWORD_FILE
    assert "-T" in create
    assert interactive is False


def test_a_failed_step_stops_with_its_output(config: SynapseConfig) -> None:
    docker = FakeDocker({"run --rm migrate": (1, "migration 0007 failed\n")})
    with pytest.raises(ApplyError, match="Apply migrations: failed") as failure:
        apply(config, run=docker, checks=healthy, echo=quiet)
    assert "migration 0007 failed" in str(failure.value)
    assert docker.commands()[-1] == "run --rm migrate"


def test_failed_checks_stop_before_anything_starts(config: SynapseConfig) -> None:
    def broken(_: SynapseConfig, **__: Any) -> list[doctor.Check]:
        return [doctor.Check("memory", doctor.Status.FAIL, "8 GiB, needs 16")]

    docker = FakeDocker(FIRST_RUN)
    with pytest.raises(ApplyError, match="checks failed: memory"):
        apply(config, run=docker, checks=broken, echo=quiet)
    assert docker.commands() == ["ps --status running -q"]
