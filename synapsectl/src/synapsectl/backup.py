"""Backups and restores (ADR 0012): ``synapsectl backup``, ``backup verify``, ``restore``.

A backup is one restic snapshot of what the installation cannot rebuild:

- the database, dumped with ``pg_dump --format=custom`` while it runs (one consistent snapshot);
- the uploaded files (the ``blobs`` volume), copied after the dump: a file uploaded in between is
  extra, never missing, since a blob is never changed once written;
- synapse.toml and the secrets, so a new machine can be set up from the backup alone;
- a manifest: when, which installation, the image version, the schema revision, the rows of
  every table and the dump's SHA-256.

restic encrypts and deduplicates the snapshots in the repository (a directory: a mounted NAS or
disk) and keeps 7 daily, 4 weekly and 6 monthly ones by default. Model files are not backed up:
they come with the release.

Restoring needs the same image version that took the backup (upgrade afterwards), and replaces
the database and the files; ``synapsectl apply`` then starts the services. A verification
restores the latest dump into a scratch database, compares every table's rows with the
manifest, checks that the live audit log still holds the backup's last event unchanged (each
event's hash covers the one before it, so this one comparison covers the whole chain up to the
backup: a rewrite since is found with the backup as the witness), drops it, and has restic read
a sample of the repository's data back.

Docker is called through the same runner as ``apply``, so tests check the exact commands.
"""

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from synapsectl.apply import Runner, docker
from synapsectl.config import SynapseConfig, load
from synapsectl.render import BACKUP_BLOBS as BLOBS
from synapsectl.render import BACKUP_STAGING as STAGING
from synapsectl.render import RESTIC_IMAGE

DATABASE = "synapse"
DRILL_DATABASE = "synapse_drill"
TAG = "synapse"
# Inside the backup containers (render.backup_services): a snapshot holds DATA and BLOBS.
DATA = f"{STAGING}/data"
DUMP = "synapse.dump"
MANIFEST = "manifest.json"
MANIFEST_FORMAT = 1
# What a verification reads back of the repository's data, beyond its structure.
CHECK_SUBSET = "5%"
# Every table's rows in the dump itself, so the counts are of the same moment as the data: the
# rows between each table's COPY line and its end marker ("\." alone on a line; COPY's text
# format writes a row on one line, newlines escaped).
DUMP_ROWS = (
    f"pg_restore --data-only --file=- {DATA}/{DUMP} | awk "
    '\'/^COPY /{split($2, name, "."); table = name[2]; n = 0; inside = 1; next} '
    'inside && /^\\\\\\.$/{print table "|" n; inside = 0; next} inside{n++}\''
)
# Every table's rows in a database, counted exactly, in one statement (psql runs one per -c).
COUNT_ROWS = (
    "SELECT table_name, (xpath('/row/n/text()', query_to_xml(format("
    "'SELECT count(*) AS n FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text "
    "FROM information_schema.tables "
    "WHERE table_schema = 'synapse' AND table_type = 'BASE TABLE' ORDER BY table_name"
)


class BackupError(RuntimeError):
    """A step failed; the message says which, with its output."""


@dataclass(frozen=True)
class Manifest:
    created: str
    instance: str
    tenant: str
    images_version: str
    schema: str
    rows: dict[str, int]
    dump_bytes: int
    dump_sha256: str

    def to_json(self) -> str:
        return json.dumps({"format": MANIFEST_FORMAT, **asdict(self)}, indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> Manifest:
        data = json.loads(text)
        if data.pop("format", None) != MANIFEST_FORMAT:
            raise BackupError("the backup's manifest has a format this synapsectl does not read")
        return cls(**data)


class Stack:
    """The installation's backup containers, through Docker Compose."""

    def __init__(self, config: SynapseConfig, run: Runner, echo: Callable[[str], None]) -> None:
        self.run, self.echo = run, echo
        compose_file = config.paths.render_dir / "compose.yml"
        self.compose = ["docker", "compose", "-f", str(compose_file), "--profile", "backup"]

    def step(self, title: str, *args: str) -> str:
        self.echo(f"== {title}")
        result = self.run([*self.compose, *args])
        if result.returncode != 0:
            output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
            raise BackupError(f"{title}: failed (exit {result.returncode})\n{output}".rstrip())
        return result.stdout or ""

    def psql(self, title: str, database: str, statement: str) -> str:
        return self.step(
            title,
            *("run", "--rm", "-T", "pgtools", "psql", f"--dbname={database}"),
            *("--no-psqlrc", "--tuples-only", "--no-align", "--set=ON_ERROR_STOP=1"),
            *("--command", statement),
        )

    def restic(self, title: str, *args: str, restore: bool = False) -> str:
        service = "restic-restore" if restore else "restic"
        return self.step(title, "run", "--rm", "-T", service, *args)


def staging_dir(config: SynapseConfig) -> Path:
    return config.backup.staging_dir


def host(config: SynapseConfig) -> str:
    """How the installation's snapshots are told apart in a shared repository."""
    return f"synapse-{config.instance.id}"


# ----------------------------------------------------------------------------------------------
# backup


def backup(
    config: SynapseConfig,
    config_file: Path,
    *,
    run: Runner = docker,
    echo: Callable[[str], None] = print,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:
    """Take one backup and apply the retention; returns the snapshot's ID. The outcome is
    recorded either way (``status.json``), for ``doctor`` and the operations page."""
    started = now()
    _repository_dir(config)  # with no repository there is nowhere to record either
    try:
        snapshot, manifest = _backup(config, config_file, Stack(config, run, echo), started)
    except (BackupError, OSError) as error:
        # the failure is recorded if it can be, and never hides the error itself
        with suppress(OSError):
            record(config, "backup", started, ok=False, detail=str(error).splitlines()[0])
        raise
    rows = sum(manifest.rows.values())
    detail = f"snapshot {snapshot[:8]}, {rows} rows, {manifest.dump_bytes} bytes of dump"
    record(config, "backup", started, ok=True, detail=detail, snapshot=snapshot)
    echo(f"== Backed up: {detail}")
    return snapshot


def _backup(
    config: SynapseConfig, config_file: Path, stack: Stack, started: datetime
) -> tuple[str, Manifest]:
    _require_repository(config)
    if not stack.step("Look for the database", "ps", "--status", "running", "-q", "db").strip():
        raise BackupError("the database is not running (run: synapsectl apply)")
    data = _fresh_data_dir(config)
    _copy_configuration(config, config_file, data / "config")
    stack.step(
        "Dump the database",
        *("run", "--rm", "-T", "pgtools", "pg_dump", f"--dbname={DATABASE}"),
        *("--format=custom", f"--file={DATA}/{DUMP}"),
    )
    dump = data / DUMP
    manifest = Manifest(
        created=started.isoformat(),
        instance=str(config.instance.id),
        tenant=str(config.instance.tenant_id),
        images_version=config.images.version,
        schema=_schema(stack, DATABASE),
        rows=_dump_rows(stack),
        dump_bytes=dump.stat().st_size,
        dump_sha256=_sha256(dump),
    )
    (data / MANIFEST).write_text(manifest.to_json(), encoding="utf-8")
    output = stack.restic(
        "Copy the dump, the files and the configuration to the repository",
        *("backup", DATA, BLOBS, "--tag", TAG, "--host", host(config), "--json"),
    )
    snapshot = _snapshot_id(output)
    keep = config.backup
    stack.restic(
        f"Keep {keep.keep_daily} daily, {keep.keep_weekly} weekly, {keep.keep_monthly} monthly",
        *("forget", "--tag", TAG, "--host", host(config), "--prune"),
        *("--keep-daily", str(keep.keep_daily), "--keep-weekly", str(keep.keep_weekly)),
        *("--keep-monthly", str(keep.keep_monthly)),
    )
    shutil.rmtree(data)
    return snapshot, manifest


def init_repository(
    config: SynapseConfig, *, run: Runner = docker, echo: Callable[[str], None] = print
) -> None:
    """Create the repository, unless it exists; restic encrypts it with the backup password."""
    repository = _repository_dir(config)
    repository.mkdir(parents=True, exist_ok=True, mode=0o700)
    stack = Stack(config, run, echo)
    if run([*stack.compose, "run", "--rm", "-T", "restic", "cat", "config"]).returncode == 0:
        echo(f"== The repository in {repository} is set up already")
        return
    stack.restic("Set up the repository", "init")
    password = config.paths.secrets_dir / "backup_password"
    echo(
        f"== Keep a copy of {password} away from this machine (a password manager, a sealed "
        "envelope): without it no backup can be restored."
    )


def snapshots(
    config: SynapseConfig, *, run: Runner = docker, echo: Callable[[str], None] = print
) -> list[dict[str, Any]]:
    """The installation's snapshots, oldest first."""
    output = Stack(config, run, echo).restic(
        "List the snapshots", "snapshots", "--tag", TAG, "--host", host(config), "--json"
    )
    found: list[dict[str, Any]] = json.loads(output or "[]")
    return found


# ----------------------------------------------------------------------------------------------
# verify


def verify(
    config: SynapseConfig,
    *,
    snapshot: str = "latest",
    run: Runner = docker,
    echo: Callable[[str], None] = print,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Restore a snapshot's dump into a scratch database and compare every table's rows with
    its manifest; then have restic read a sample of the repository's data back."""
    started = now()
    stack = Stack(config, run, echo)
    try:
        _require_repository(config)
        manifest = _restore_data_dir(config, stack, _snapshot_of(stack, config, snapshot))
        stack.psql(
            "Make a scratch database",
            "postgres",
            f"DROP DATABASE IF EXISTS {DRILL_DATABASE} WITH (FORCE)",
        )
        stack.psql("Make a scratch database", "postgres", f"CREATE DATABASE {DRILL_DATABASE}")
        try:
            stack.step(
                "Restore the dump into it",
                *("run", "--rm", "-T", "pgtools", "pg_restore", f"--dbname={DRILL_DATABASE}"),
                *("--single-transaction", "--exit-on-error", f"{DATA}/{DUMP}"),
            )
            _compare_rows(manifest, _rows(stack, DRILL_DATABASE))
            _compare_audit(stack, config, manifest)
        finally:
            stack.psql(
                "Drop the scratch database",
                "postgres",
                f"DROP DATABASE IF EXISTS {DRILL_DATABASE} WITH (FORCE)",
            )
        stack.restic(
            "Read back a sample of the repository's data",
            *("check", f"--read-data-subset={CHECK_SUBSET}"),
        )
        shutil.rmtree(staging_dir(config) / "data", ignore_errors=True)
    except (BackupError, OSError) as error:
        with suppress(OSError):
            record(config, "verify", started, ok=False, detail=str(error).splitlines()[0])
        raise
    detail = f"{sum(manifest.rows.values())} rows of {manifest.created} restored and counted"
    record(config, "verify", started, ok=True, detail=detail)
    echo(f"== Verified: {detail}")


# ----------------------------------------------------------------------------------------------
# restore


def restore(
    config: SynapseConfig,
    *,
    snapshot: str = "latest",
    replace: bool = False,
    run: Runner = docker,
    echo: Callable[[str], None] = print,
) -> Manifest:
    """Replace this installation's database and files with a snapshot's. The services are left
    stopped (except the database); ``synapsectl apply`` starts them."""
    stack = Stack(config, run, echo)
    _require_repository(config)
    # resolved once, so the database and the files come from the same snapshot
    snapshot_id = _snapshot_of(stack, config, snapshot)
    manifest = _restore_data_dir(config, stack, snapshot_id)
    if manifest.instance != str(config.instance.id):
        raise BackupError(
            f"the backup is of installation {manifest.instance}, not this one "
            f"({config.instance.id}); on a new machine restore its configuration first "
            "(synapsectl restore --configuration-from REPOSITORY)"
        )
    if manifest.images_version != config.images.version:
        raise BackupError(
            f"the backup was taken with images {manifest.images_version}, this installation runs "
            f"{config.images.version}: set [images] version to {manifest.images_version}, run "
            "synapsectl render, restore, then upgrade"
        )
    for name in _changed_secrets(config, staging_dir(config) / "data" / "config" / "secrets"):
        echo(f"!! the secret {name} differs from the backup's; this machine's is kept")
    stack.step("Stop the services", "stop")
    stack.step("Start the database", "up", "-d", "--wait", "db")
    if _holds_data(stack) and not replace:
        raise BackupError(
            "the database holds an installation's data; restore over it with --replace"
        )
    stack.step("Create or repair the roles", "run", "--rm", "bootstrap")
    stack.psql("Drop the database", "postgres", f"DROP DATABASE IF EXISTS {DATABASE} WITH (FORCE)")
    stack.step(
        "Restore the database",
        *("run", "--rm", "-T", "pgtools", "pg_restore", "--dbname=postgres", "--create"),
        *("--exit-on-error", f"{DATA}/{DUMP}"),
    )
    _compare_rows(manifest, _rows(stack, DATABASE))
    stack.step(
        "Empty the uploaded files",
        *("run", "--rm", "-T", "--entrypoint", "find", "restic-restore", BLOBS),
        *("-mindepth", "1", "-delete"),
    )
    stack.restic(
        "Restore the uploaded files",
        *("restore", snapshot_id, "--target", "/", "--include", BLOBS),
        restore=True,
    )
    shutil.rmtree(staging_dir(config) / "data", ignore_errors=True)
    echo(f"== Restored the backup of {manifest.created}; next: synapsectl apply")
    return manifest


def restore_configuration(
    repository: Path,
    password_file: Path,
    config_file: Path,
    *,
    snapshot: str = "latest",
    run: Runner = docker,
    echo: Callable[[str], None] = print,
) -> SynapseConfig:
    """On a new machine: synapse.toml and the secrets from the repository, put where they were.
    Nothing existing is overwritten."""
    if config_file.exists():
        raise BackupError(f"{config_file} exists; this machine is set up already")
    with tempfile.TemporaryDirectory(prefix="synapse-restore-") as scratch:
        echo("== Restore the configuration and the secrets")
        result = run(
            [
                *("docker", "run", "--rm", "--network", "none"),
                *("-v", f"{repository.resolve()}:/repository"),
                *("-v", f"{password_file.resolve()}:/run/password:ro"),
                *("-v", f"{scratch}:/restore"),
                *(
                    "-e",
                    "RESTIC_REPOSITORY=/repository",
                    "-e",
                    "RESTIC_PASSWORD_FILE=/run/password",
                ),
                RESTIC_IMAGE,
                *("restore", snapshot, "--target", "/restore", "--include", f"{DATA}/config"),
            ]
        )
        if result.returncode != 0:
            raise BackupError(f"restic restore failed (exit {result.returncode})\n{result.stderr}")
        source = Path(scratch) / DATA.lstrip("/") / "config"
        restored = load(source / "synapse.toml")
        secrets = restored.paths.secrets_dir
        if secrets.exists() and any(secrets.iterdir()):
            raise BackupError(f"{secrets} holds files already; move them away first")
        config_file.parent.mkdir(parents=True, exist_ok=True)
        _copy_preserving(source / "synapse.toml", config_file)
        secrets.mkdir(parents=True, exist_ok=True, mode=0o700)
        for item in sorted((source / "secrets").iterdir()):
            _copy_preserving(item, secrets / item.name)
    echo(f"== Wrote {config_file} and {secrets}; next: synapsectl render, then restore")
    return restored


# ----------------------------------------------------------------------------------------------
# status


def status_file(config: SynapseConfig) -> Path:
    return staging_dir(config) / "status.json"


def read_status(config: SynapseConfig) -> dict[str, Any]:
    try:
        status: dict[str, Any] = json.loads(status_file(config).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    return status


def record(
    config: SynapseConfig,
    kind: str,
    when: datetime,
    *,
    ok: bool,
    detail: str,
    snapshot: str | None = None,
) -> None:
    """The outcome of a backup or a verification; the last good one is kept apart."""
    status = read_status(config)
    entry = {"time": when.isoformat(), "ok": ok, "detail": detail, "snapshot": snapshot}
    status[kind] = entry
    if ok:
        status[f"{kind}_ok"] = entry
    path = status_file(config)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    partial = path.with_suffix(".partial")
    partial.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    partial.chmod(0o600)
    partial.replace(path)


def last_good(config: SynapseConfig, kind: str = "backup") -> datetime | None:
    entry = read_status(config).get(f"{kind}_ok")
    return datetime.fromisoformat(entry["time"]) if entry else None


# ----------------------------------------------------------------------------------------------
# schedule

UNITS_DIR = Path("/etc/systemd/system")
VERIFY_DELAY = timedelta(hours=3)


def schedule_units(config: SynapseConfig, config_file: Path) -> dict[str, str]:
    """systemd units: a backup every night at backup.time, a verification on the first day of
    each quarter, three hours later."""
    hour, minute = (int(part) for part in config.backup.time.split(":"))
    later = hour * 60 + minute + VERIFY_DELAY // timedelta(minutes=1)
    verify_hour, verify_minute = divmod(later % (24 * 60), 60)
    units = {}
    for name, action, calendar, what in (
        ("synapse-backup", "backup run", f"*-*-* {hour:02d}:{minute:02d}:00", "backup"),
        (
            "synapse-backup-verify",
            "backup verify",
            f"*-01,04,07,10-01 {verify_hour:02d}:{verify_minute:02d}:00",
            "backup verification",
        ),
    ):
        units[f"{name}.service"] = (
            f"[Unit]\nDescription=Synapse {what}\nAfter=docker.service\nRequires=docker.service\n\n"
            f"[Service]\nType=oneshot\n"
            f"ExecStart=/usr/bin/env synapsectl --config {config_file} {action}\n"
        )
        units[f"{name}.timer"] = (
            f"[Unit]\nDescription=Synapse {what}, on schedule\n\n"
            f"[Timer]\nOnCalendar={calendar}\nPersistent=true\n\n"
            "[Install]\nWantedBy=timers.target\n"
        )
    return units


def install_schedule(
    config: SynapseConfig,
    config_file: Path,
    *,
    units_dir: Path = UNITS_DIR,
    run: Runner = docker,
    echo: Callable[[str], None] = print,
) -> None:
    """Write the units and enable their timers (needs root and systemd)."""
    for name, text in schedule_units(config, config_file).items():
        (units_dir / name).write_text(text, encoding="utf-8")
    for args in (
        ["systemctl", "daemon-reload"],
        ["systemctl", "enable", "--now", "synapse-backup.timer", "synapse-backup-verify.timer"],
    ):
        result = run(args)
        if result.returncode != 0:
            raise BackupError(f"{' '.join(args)} failed\n{result.stderr}")
    echo(f"== Backups every night at {config.backup.time}, verified every quarter")


# ----------------------------------------------------------------------------------------------
# helpers


def _repository_dir(config: SynapseConfig) -> Path:
    if config.backup.repository is None:
        raise BackupError("no backup repository is set ([backup] repository in synapse.toml)")
    return config.backup.repository


def _require_repository(config: SynapseConfig) -> None:
    repository = _repository_dir(config)
    if not (repository / "config").exists():
        raise BackupError(
            f"{repository} is not a backup repository (is the disk mounted? or run: "
            "synapsectl backup init)"
        )


def _fresh_data_dir(config: SynapseConfig) -> Path:
    data = staging_dir(config) / "data"
    shutil.rmtree(data, ignore_errors=True)
    data.mkdir(parents=True, mode=0o700)
    staging_dir(config).chmod(0o700)
    return data


def _copy_configuration(config: SynapseConfig, config_file: Path, target: Path) -> None:
    (target / "secrets").mkdir(parents=True, mode=0o700)
    _copy_preserving(config_file, target / "synapse.toml")
    for item in sorted(config.paths.secrets_dir.iterdir()):
        if item.is_file():
            _copy_preserving(item, target / "secrets" / item.name)


def _copy_preserving(source: Path, target: Path) -> None:
    """A copy with the source's mode and, as root, its owner (the containers' users)."""
    shutil.copy2(source, target)
    if os.geteuid() == 0:
        stat = source.stat()
        os.chown(target, stat.st_uid, stat.st_gid)


def _restore_data_dir(config: SynapseConfig, stack: Stack, snapshot_id: str) -> Manifest:
    data = staging_dir(config) / "data"
    shutil.rmtree(data, ignore_errors=True)
    staging_dir(config).mkdir(parents=True, exist_ok=True, mode=0o700)
    stack.restic(
        "Restore the dump and the configuration",
        *("restore", snapshot_id, "--target", "/", "--include", DATA),
        restore=True,
    )
    manifest = Manifest.from_json((data / MANIFEST).read_text(encoding="utf-8"))
    if _sha256(data / DUMP) != manifest.dump_sha256:
        raise BackupError("the restored dump differs from the one the backup recorded")
    return manifest


def _snapshot_of(stack: Stack, config: SynapseConfig, snapshot: str) -> str:
    """``latest`` as the installation's own latest snapshot, not the repository's."""
    if snapshot != "latest":
        return snapshot
    found = json.loads(
        stack.restic(
            "Find the latest snapshot",
            *("snapshots", "--tag", TAG, "--host", host(config), "--latest", "1", "--json"),
        )
        or "[]"
    )
    if not found:
        raise BackupError("the repository holds no snapshot of this installation")
    snapshot_id: str = found[-1]["id"]
    return snapshot_id


def _schema(stack: Stack, database: str) -> str:
    return stack.psql(
        "Read the schema revision", database, "SELECT version_num FROM synapse.alembic_version"
    ).strip()


def _dump_rows(stack: Stack) -> dict[str, int]:
    output = stack.step(
        "Count every table's rows in the dump",
        *("run", "--rm", "-T", "pgtools", "sh", "-c", DUMP_ROWS),
    )
    return _parse_rows(output)


def _rows(stack: Stack, database: str) -> dict[str, int]:
    return _parse_rows(stack.psql("Count every table's rows", database, COUNT_ROWS))


def _parse_rows(output: str) -> dict[str, int]:
    rows = {}
    for line in output.splitlines():
        if line.strip():
            table, count = line.rsplit("|", 1)
            rows[table] = int(count)
    return rows


def _compare_rows(manifest: Manifest, restored: dict[str, int]) -> None:
    differences = [
        f"{table}: {restored.get(table)} rows, expected {count}"
        for table, count in sorted(manifest.rows.items())
        if restored.get(table) != count
    ] + [f"{table}: not in the backup" for table in sorted(set(restored) - set(manifest.rows))]
    if differences:
        raise BackupError(
            "the restored database differs from the backup: " + "; ".join(differences)
        )


def _compare_audit(stack: Stack, config: SynapseConfig, manifest: Manifest) -> None:
    """The backup's last audit event must still be in the live chain, with the same hash."""
    tenant = config.instance.tenant_id  # a UUID: safe in the statement
    last = stack.psql(
        "Read the backup's last audit event",
        DRILL_DATABASE,
        "SELECT seq || '|' || encode(hash, 'hex') FROM synapse.audit_events "  # noqa: S608
        f"WHERE tenant_id = '{tenant}' ORDER BY seq DESC LIMIT 1",
    ).strip()
    if not last:
        return
    seq, digest = last.split("|")
    live = stack.psql(
        "Find it in the live audit log",
        DATABASE,
        "SELECT encode(hash, 'hex') FROM synapse.audit_events "  # noqa: S608
        f"WHERE tenant_id = '{tenant}' AND seq = {int(seq)}",
    ).strip()
    if live != digest:
        change = "is missing from" if not live else "differs in"
        raise BackupError(
            f"audit event {seq} of the backup of {manifest.created} {change} the live audit "
            "log: the log was rewritten since, or an older backup was restored"
        )


def _holds_data(stack: Stack) -> bool:
    exists = stack.psql(
        "Look for an existing database",
        "postgres",
        "SELECT count(*) FROM pg_database WHERE datname = 'synapse'",
    )
    if exists.strip() != "1":
        return False
    has_tenants = stack.psql(
        "Look for an installation in it",
        DATABASE,
        "SELECT to_regclass('synapse.tenants') IS NOT NULL",
    )
    if has_tenants.strip() != "t":
        return False
    tenants = stack.psql("Count its tenants", DATABASE, "SELECT count(*) FROM synapse.tenants")
    return tenants.strip() != "0"


def _changed_secrets(config: SynapseConfig, restored: Path) -> list[str]:
    if not restored.is_dir():
        return []
    return [
        item.name
        for item in sorted(restored.iterdir())
        if (config.paths.secrets_dir / item.name).is_file()
        and _sha256(item) != _sha256(config.paths.secrets_dir / item.name)
    ]


def _snapshot_id(output: str) -> str:
    for line in reversed(output.splitlines()):
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if isinstance(message, dict) and message.get("message_type") == "summary":
            snapshot: str = message["snapshot_id"]
            return snapshot
    raise BackupError("restic reported no snapshot")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
