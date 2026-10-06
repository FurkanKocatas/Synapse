"""``synapsectl support-bundle``: what the vendor's support needs, in one file (ADR 0012).

The bundle is written on this machine and sent by nobody but its operator, who can read it
first: every file in it is text. It holds the versions, doctor's checks, synapse.toml, the
rendered files, the services' states and their recent logs, the backup status and the disk
use; of the secrets only their names, modes, owners and sizes.

Logs leave the organisation, so everything collected is redacted (``Redactor``): the secrets'
values, email addresses, IP addresses outside the stack's own network (each replaced by a
pseudonym that is the same within one bundle, so requests can still be followed, and that
cannot be reversed), query string values (they carry file names), credentials in headers and
connection strings, and the values PostgreSQL quotes in its errors. Document contents never
enter the logs or the bundle.
"""

import hashlib
import io
import ipaddress
import json
import os
import platform
import re
import shutil
import tarfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from synapsectl import __version__, doctor
from synapsectl.apply import Runner, docker
from synapsectl.config import SynapseConfig

# Recent lines of each service's log.
LOG_LINES = 2000
# A secret shorter than this could match ordinary text; none is generated that short.
SHORTEST_SECRET = 8

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
IPV6 = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")
QUERY_VALUE = re.compile(r"([?&][A-Za-z0-9_.\-\[\]]+=)[^&#\s\"'\\]+")
HEADER_VALUE = re.compile(
    r'("(?:cookie|set-cookie|authorization|x-synapse-csrf|x-api-key)"\s*:\s*\[\s*)"[^"]*"',
    re.IGNORECASE,
)
CREDENTIALS_IN_URL = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^:/\s@\"']+:)[^@\s\"']+@")
POSTGRES_DETAIL = re.compile(r"(Key \([^)]*\)=\()[^)]*(\))")

README = """Synapse support bundle, {created}

Written by synapsectl support-bundle on the customer's machine; nothing was sent anywhere.
Every file is text. Removed before writing: the secrets' values, email addresses, IP addresses
outside the stack's own network (each replaced by a pseudonym that holds within this bundle
only), query string values, credentials in headers and connection strings, and the values
PostgreSQL quotes in its errors. The secrets appear by name, mode, owner and size only.
"""


class SupportError(RuntimeError):
    """The bundle cannot be written safely; the message says why."""


class Redactor:
    """Removes what must not leave the machine from the text it is given."""

    def __init__(self, secret_values: dict[str, str], own_networks: list[str]) -> None:
        kept = [(value, name) for name, value in secret_values.items()]
        # longest first, so a secret that contains another is replaced whole
        self.secrets = sorted(
            (item for item in kept if len(item[0]) >= SHORTEST_SECRET),
            key=lambda item: -len(item[0]),
        )
        self.own = [ipaddress.ip_network(network, strict=False) for network in own_networks]
        self.salt = os.urandom(16)  # never stored: the pseudonyms cannot be reversed

    def __call__(self, text: str) -> str:
        for value, name in self.secrets:
            text = text.replace(value, f"[secret {name}]")
        text = CREDENTIALS_IN_URL.sub(r"\1[secret]@", text)
        text = HEADER_VALUE.sub(r'\1"[removed]"', text)
        text = EMAIL.sub("[email]", text)
        text = QUERY_VALUE.sub(r"\1[removed]", text)
        text = POSTGRES_DETAIL.sub(r"\1[removed]\2", text)
        text = IPV4.sub(self._address, text)
        return IPV6.sub(self._address, text)

    def _address(self, match: re.Match[str]) -> str:
        try:
            address = ipaddress.ip_address(match.group(0))
        except ValueError:
            return match.group(0)  # a version number or a time, not an address
        if address.is_loopback or address.is_unspecified or any(address in n for n in self.own):
            return match.group(0)
        digest = hashlib.sha256(self.salt + address.packed).hexdigest()[:8]
        return f"[ip {digest}]"


def write_bundle(
    config: SynapseConfig,
    config_file: Path,
    output: Path,
    *,
    run: Runner = docker,
    echo: Callable[[str], None] = print,
    checks: Callable[..., list[doctor.Check]] = doctor.run_checks,
) -> Path:
    """Collect, redact and write the bundle: a .tar.gz readable only by its owner."""
    redact = Redactor(_secret_values(config), [str(config.network.subnet)])
    compose = ["docker", "compose", "-f", str(config.paths.render_dir / "compose.yml")]
    files: dict[str, str] = {}

    def command(name: str, args: list[str]) -> str:
        result = run(args)
        text = "\n".join(part for part in (result.stdout, result.stderr) if part)
        files[name] = f"$ {' '.join(args)}\n(exit {result.returncode})\n{text}"
        return (result.stdout or "") if result.returncode == 0 else ""

    echo("== Versions and the machine")
    files["versions.txt"] = (
        f"synapsectl {__version__}\nimages {config.images.version}\n"
        f"{platform.platform()}\n{_os_release()}"
    )
    command("docker-version.txt", ["docker", "version"])
    command("docker-df.txt", ["docker", "system", "df"])
    files["disk.txt"] = _disk_use(config)

    echo("== Configuration, rendered files and secrets (names only)")
    files["synapse.toml"] = config_file.read_text(encoding="utf-8")
    for name in ("compose.yml", "manifest.json"):
        rendered = config.paths.render_dir / name
        if rendered.is_file():
            files[f"rendered/{name}"] = rendered.read_text(encoding="utf-8")
    files["secrets.txt"] = _secret_listing(config)
    backup_status = config.backup.staging_dir / "status.json"
    if backup_status.is_file():
        files["backup-status.json"] = backup_status.read_text(encoding="utf-8")

    echo("== Services and their logs")
    services = _services(command("services.json", [*compose, "ps", "--all", "--format", "json"]))
    logs = ["logs", "--no-color", "--timestamps", "--tail", str(LOG_LINES)]
    for service in services:
        command(f"logs/{service['name']}.log", [*compose, *logs, service["name"]])

    echo("== Checks")
    running = any(service["state"] == "running" for service in services)
    files["doctor.txt"] = "".join(
        f"{check.status:<4}  {check.name}: {check.detail}\n"
        for check in checks(config, stack_running=running)
    )

    redacted = {name: redact(text) for name, text in sorted(files.items())}
    redacted["README.txt"] = README.format(created=datetime.now(UTC).isoformat(timespec="seconds"))
    _write_tar(output, redacted)
    echo(f"== Wrote {output}: read it before you send it")
    return output


def default_output(config: SynapseConfig, now: datetime | None = None) -> Path:
    moment = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M")
    return Path(f"synapse-support-{config.instance.slug}-{moment}.tar.gz")


def read_secret(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _secret_values(config: SynapseConfig) -> dict[str, str]:
    """Every secret's value, so that none can leave in a log. A secret that cannot be read
    stops the bundle: its value could not be removed."""
    directory = config.paths.secrets_dir
    try:
        items = sorted(item for item in directory.iterdir() if item.is_file())
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise SupportError(f"cannot read {directory} (run as root): {error}") from error
    values = {}
    for item in items:
        try:
            values[item.name] = read_secret(item)
        except (OSError, UnicodeDecodeError) as error:
            raise SupportError(
                f"cannot read the secret {item.name} (run as root): its value could not be "
                "removed from the logs"
            ) from error
    return values


def _secret_listing(config: SynapseConfig) -> str:
    directory = config.paths.secrets_dir
    if not directory.is_dir():
        return f"{directory}: missing\n"
    rows = [f"{directory}: mode {directory.stat().st_mode & 0o777:o}"]
    for item in sorted(directory.iterdir()):
        stat = item.stat()
        mode = stat.st_mode & 0o777
        rows.append(f"{item.name}: mode {mode:o}, owner {stat.st_uid}, {stat.st_size} bytes")
    return "\n".join(rows) + "\n"


def _disk_use(config: SynapseConfig) -> str:
    rows = []
    for label, path in (
        ("root", Path("/")),
        ("secrets", config.paths.secrets_dir),
        ("models", config.models.dir),
        ("backup staging", config.backup.staging_dir),
        ("backup repository", config.backup.repository),
    ):
        if path is None or not path.exists():
            rows.append(f"{label}: {path} (missing)")
            continue
        usage = shutil.disk_usage(path)
        free, total = usage.free / 2**30, usage.total / 2**30
        rows.append(f"{label}: {path}, {free:.1f} GiB free of {total:.1f} GiB")
    return "\n".join(rows) + "\n"


def _os_release() -> str:
    try:
        return Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return "(no /etc/os-release)\n"


def _services(output: str) -> list[dict[str, str]]:
    """``docker compose ps --format json``: a JSON array, or one object a line."""
    text = output.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        found = parsed if isinstance(parsed, list) else [parsed]
    except ValueError:
        found = [json.loads(line) for line in text.splitlines() if line.strip()]
    return [
        {"name": str(item["Service"]), "state": str(item.get("State", ""))}
        for item in found
        if item.get("Service")
    ]


def _write_tar(output: Path, files: dict[str, str]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    root = output.name.removesuffix(".tar.gz")
    partial = output.with_name(output.name + ".partial")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle, tarfile.open(fileobj=handle, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode("utf-8")
            member = tarfile.TarInfo(f"{root}/{name}")
            member.size, member.mode, member.mtime = len(data), 0o600, int(time.time())
            tar.addfile(member, io.BytesIO(data))
    partial.replace(output)
    # run with sudo: the bundle belongs to the operator who asked for it
    user, group = os.environ.get("SUDO_UID", ""), os.environ.get("SUDO_GID", "")
    if os.geteuid() == 0 and user.isdigit():
        os.chown(output, int(user), int(group) if group.isdigit() else -1)
