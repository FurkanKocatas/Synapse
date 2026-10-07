"""``synapsectl apply``: bring the installation to the state synapse.toml describes (ADR 0012).

Every step is safe to repeat, so the same command installs, repairs and (with a new image
version) upgrades:

1. render the files again and run the doctor checks; stop on any failure;
2. start the database, then bootstrap (creates or repairs roles and schema) and migrate;
3. create the tenant with the ID from synapse.toml, unless it exists;
4. create the first administrator, unless one exists (needed only on the first run);
5. start every service and wait until each is healthy, then check again.

An installation still on the earlier network, which was not internal, is taken down first
(its volumes stay): brought up over it, compose recreates the network but restarts the other
containers on it without their names, and the services no longer find each other.

Docker is called through a runner so tests can check the exact commands without Docker.
"""

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from synapsectl import doctor, render
from synapsectl.config import SynapseConfig

# Inside the application container; the host file is mounted here read-only.
CONTAINER_PASSWORD_FILE = "/run/synapse-admin-password"  # noqa: S105  (a path, not a password)


class Runner(Protocol):
    def __call__(
        self, args: Sequence[str], *, interactive: bool = False
    ) -> subprocess.CompletedProcess[str]: ...


def docker(args: Sequence[str], *, interactive: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a command; an interactive one keeps the terminal, for password prompts."""
    if interactive:
        return subprocess.run(list(args), check=False, text=True)  # noqa: S603  (fixed program)
    return subprocess.run(list(args), check=False, text=True, capture_output=True)  # noqa: S603


@dataclass(frozen=True)
class FirstAdmin:
    email: str
    name: str
    # Read from this host file instead of prompting, for scripted installs.
    password_file: Path | None = None


class ApplyError(RuntimeError):
    """A step failed; the message says which, with its output."""


Checks = Callable[..., list[doctor.Check]]


def apply(
    config: SynapseConfig,
    *,
    admin: FirstAdmin | None = None,
    run: Runner = docker,
    checks: Checks = doctor.run_checks,
    echo: Callable[[str], None] = print,
) -> None:
    compose = ["docker", "compose", "-f", str(config.paths.render_dir / "compose.yml")]

    def step(title: str, *args: str, interactive: bool = False) -> str:
        echo(f"== {title}")
        result = run([*compose, *args], interactive=interactive)
        if result.returncode != 0:
            output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
            raise ApplyError(f"{title}: failed (exit {result.returncode})\n{output}".rstrip())
        return result.stdout or ""

    echo("== Render and check")
    render.write(config, render.render(config))
    running = bool(step("Look for running services", "ps", "--status", "running", "-q").strip())
    _require(checks(config, stack_running=running), echo)
    if _earlier_network(config, run):
        step("Stop the services, to move them to the internal network", "down")

    step("Start the database", "up", "-d", "--wait", "db")
    step("Create or repair the database, roles and schema", "run", "--rm", "bootstrap")
    step("Apply migrations", "run", "--rm", "migrate")
    instance = config.instance
    step(
        "Create the tenant",
        *("run", "--rm", "--no-deps", "-T", "api", "tenant", "create"),
        *("--slug", instance.slug, "--name", instance.organization),
        *("--id", str(instance.tenant_id), "--if-missing"),
    )
    admins = step("Count administrators", "run", "--rm", "--no-deps", "-T", "api", "user", "admins")
    if int(admins.strip().splitlines()[-1]) == 0:
        if admin is None:
            raise ApplyError(
                "the installation has no administrator yet; run again with "
                "--admin-email and --admin-name"
            )
        step(
            "Create the first administrator",
            *_admin_command(admin, instance.locale),
            interactive=admin.password_file is None,
        )

    step("Start every service", "up", "-d", "--wait")
    _require(checks(config, stack_running=True), echo)
    echo(f"== Ready: https://{render.site_address(config)}")


def _earlier_network(config: SynapseConfig, run: Runner) -> bool:
    """Whether the installation's network exists and is not internal yet."""
    name = f"synapse-{config.instance.slug}_internal"
    found = run(["docker", "network", "inspect", name, "--format", "{{.Internal}}"])
    return found.returncode == 0 and found.stdout.strip() == "false"


def _admin_command(admin: FirstAdmin, locale: str) -> list[str]:
    mount = (
        ["-v", f"{admin.password_file.resolve()}:{CONTAINER_PASSWORD_FILE}:ro"]
        if admin.password_file
        else []
    )
    password = ["--password-file", CONTAINER_PASSWORD_FILE] if admin.password_file else []
    tty = ["-T"] if admin.password_file else []
    return [
        *("run", "--rm", "--no-deps", *tty, *mount, "api", "user", "create"),
        *("--email", admin.email, "--name", admin.name, "--role", "admin", "--locale", locale),
        *password,
        "--unless-admin-exists",
    ]


def _require(results: list[doctor.Check], echo: Callable[[str], None]) -> None:
    for result in results:
        echo(f"{result.status:<4}  {result.name}: {result.detail}")
    failed = [result.name for result in results if result.status is doctor.Status.FAIL]
    if failed:
        raise ApplyError(f"checks failed: {', '.join(failed)}")
