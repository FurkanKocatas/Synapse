"""``synapsectl upgrade``: move an installation to another release (ADR 0012).

1. The release's images must be on the machine (from the release's bundle, or pulled).
2. A release on another PostgreSQL major version is refused: its server would not start on this
   one's data directory.
3. A backup is taken with the running release: migrations only go forward, so restoring this
   backup with the old release is the way back.
4. ``[images] version`` is changed in synapse.toml, and only that line, so hand edits and
   comments stay.
5. ``apply`` renders the files, checks the machine, migrates the database and starts the new
   release. If it stops, the error says how to go on or go back.
"""

import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from synapsectl import backup
from synapsectl.apply import ApplyError, Runner, apply, docker
from synapsectl.config import SynapseConfig, load

IMAGES = ("synapse-app", "synapse-web", "synapse-postgres")
# An image's environment, one variable a line (PostgreSQL's image sets PG_MAJOR).
ENVIRONMENT = "{{range .Config.Env}}{{println .}}{{end}}"
IMAGES_TABLE = re.compile(r"^\[images\][ \t]*(#.*)?$", re.MULTILINE)
# The version line of the [images] table: its header, the lines up to the version (none starts
# a table), and the line itself.
VERSION_LINE = re.compile(
    r'(^\[images\][^\n]*\n(?:[^\[\n][^\n]*\n|\n)*?[ \t]*version[ \t]*=[ \t]*)"[^"\n]*"',
    re.MULTILINE,
)


class UpgradeError(RuntimeError):
    """The upgrade was refused or stopped; the message says why and what to do."""


def upgrade(  # noqa: PLR0913  (the backup and apply steps are passed in by the tests)
    config: SynapseConfig,
    config_file: Path,
    version: str,
    *,
    run: Runner = docker,
    echo: Callable[[str], None] = print,
    take_backup: Callable[..., str] = backup.backup,
    bring_up: Callable[..., None] = apply,
) -> SynapseConfig:
    """Upgrade to ``version``; returns the configuration it now runs with."""
    current = config.images.version
    if version == current:
        raise UpgradeError(f"the installation runs {version} already")
    missing = [image for image in IMAGES if _inspect(run, f"{image}:{version}") is None]
    if missing:
        raise UpgradeError(
            f"the images of {version} are not on this machine ({', '.join(missing)}): "
            "load the release first"
        )
    running_major = _postgres_major(run, current)
    new_major = _postgres_major(run, version)
    if new_major != running_major:
        raise UpgradeError(
            f"{version} runs PostgreSQL {new_major}, this installation {running_major}: an "
            "upgrade across PostgreSQL major versions is not supported yet"
        )
    if config.backup.repository is None:
        raise UpgradeError(
            "an upgrade takes a backup first, and backups are not set up: set [backup] "
            "repository in synapse.toml, then run synapsectl backup init"
        )

    echo(f"== Back up with {current}: the way back if the upgrade fails")
    snapshot = take_backup(config, config_file, run=run, echo=echo)
    upgraded = set_version(config_file, version)
    try:
        bring_up(upgraded, run=run, echo=echo)
    except ApplyError as error:
        raise UpgradeError(
            f"{error}\n\n"
            f"The upgrade to {version} stopped. Once the cause is fixed, run synapsectl apply "
            f"again; or go back to {current} with the backup just taken:\n"
            f'  set [images] version = "{current}" in {config_file}\n'
            "  synapsectl render\n"
            f"  synapsectl restore --snapshot {snapshot[:8]} --replace --yes\n"
            "  synapsectl apply"
        ) from error
    echo(f"== Upgraded from {current} to {version}")
    return upgraded


def set_version(config_file: Path, version: str) -> SynapseConfig:
    """Change ``[images] version`` in the file and nothing else; returns the new configuration.
    The file is replaced only once the new text is a valid configuration with that version."""
    text = config_file.read_text(encoding="utf-8")
    line = f'version = "{version}"'
    changed, found = VERSION_LINE.subn(lambda match: f'{match.group(1)}"{version}"', text, count=1)
    if not found:
        table = IMAGES_TABLE.search(text)
        if table:  # the table without the key
            changed = f"{text[: table.end()]}\n{line}{text[table.end() :]}"
        else:
            changed = text.rstrip("\n") + f"\n\n[images]\n{line}\n"
    partial = config_file.with_name(config_file.name + ".partial")
    partial.write_text(changed, encoding="utf-8")
    try:
        shutil.copymode(config_file, partial)
        upgraded = load(partial)
    except ValueError as error:  # TOML and validation errors alike
        partial.unlink(missing_ok=True)
        raise UpgradeError(f"cannot set version {version!r} in {config_file}: {error}") from error
    if upgraded.images.version != version:
        partial.unlink(missing_ok=True)
        raise UpgradeError(f"cannot find [images] version in {config_file}")
    if os.geteuid() == 0:
        stat = config_file.stat()
        os.chown(partial, stat.st_uid, stat.st_gid)
    partial.replace(config_file)
    return upgraded


def _inspect(run: Runner, image: str) -> str | None:
    """An image's environment, one variable a line; None when the image is not here."""
    result = run(["docker", "image", "inspect", "--format", ENVIRONMENT, image])
    return (result.stdout or "") if result.returncode == 0 else None


def _postgres_major(run: Runner, version: str) -> str:
    environment = _inspect(run, f"synapse-postgres:{version}") or ""
    for line in environment.splitlines():
        if line.startswith("PG_MAJOR="):
            return line.removeprefix("PG_MAJOR=")
    raise UpgradeError(f"cannot read the PostgreSQL version of synapse-postgres:{version}")
