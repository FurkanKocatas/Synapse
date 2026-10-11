"""Audit retention from the host (ADR 0022): ``synapsectl audit prune`` runs the one-shot
``retention`` container, the only one that holds the ``synapse_retention`` password, which runs
``synapse audit prune``: the events and the chat questions' texts past ``[audit]``'s periods go,
recorded in the chain. A systemd timer runs it every night, an hour after the backup; each
outcome is kept in status.json beside the backups', for ``doctor``.
"""

import json
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from synapsectl import backup
from synapsectl.apply import Runner, docker
from synapsectl.config import SynapseConfig

KIND = "audit_prune"
UNIT = "synapse-audit-prune"
AFTER_BACKUP = timedelta(hours=1)


def prune(
    config: SynapseConfig,
    *,
    run: Runner = docker,
    echo: Callable[[str], None] = print,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Remove what is past its period; returns what ``audit_prune()`` reported. The outcome is
    recorded either way."""
    started = now()
    stack = backup.Stack(config, run, echo)
    try:
        output = stack.step(
            "Remove the audit events and question texts past their periods",
            *("run", "--rm", "-T", "retention"),
        )
        removed: dict[str, Any] = json.loads(output.strip().splitlines()[-1])
    except (backup.BackupError, ValueError, IndexError) as error:
        detail = str(error).splitlines()[0] if str(error) else "no report from the container"
        with suppress(OSError):
            backup.record(config, KIND, started, ok=False, detail=detail)
        raise backup.BackupError(f"audit retention: {detail}") from error
    detail = f"{removed.get('events', 0)} events, {removed.get('texts', 0)} question texts removed"
    backup.record(config, KIND, started, ok=True, detail=detail)
    echo(f"== {detail}")
    return removed


def schedule_units(config: SynapseConfig, config_file: Path) -> dict[str, str]:
    """systemd units: every night, an hour after the backup's time."""
    hour, minute = (int(part) for part in config.backup.time.split(":"))
    later = hour * 60 + minute + AFTER_BACKUP // timedelta(minutes=1)
    at_hour, at_minute = divmod(later % (24 * 60), 60)
    return {
        f"{UNIT}.service": (
            "[Unit]\nDescription=Synapse audit retention\nAfter=docker.service\n"
            "Requires=docker.service\n\n[Service]\nType=oneshot\n"
            f"ExecStart=/usr/bin/env synapsectl --config {config_file} audit prune\n"
        ),
        f"{UNIT}.timer": (
            "[Unit]\nDescription=Synapse audit retention, on schedule\n\n"
            f"[Timer]\nOnCalendar=*-*-* {at_hour:02d}:{at_minute:02d}:00\nPersistent=true\n\n"
            "[Install]\nWantedBy=timers.target\n"
        ),
    }


def install_schedule(
    config: SynapseConfig,
    config_file: Path,
    *,
    units_dir: Path = backup.UNITS_DIR,
    run: Runner = docker,
    echo: Callable[[str], None] = print,
) -> None:
    """Write the units and enable the timer (needs root and systemd)."""
    for name, text in schedule_units(config, config_file).items():
        (units_dir / name).write_text(text, encoding="utf-8")
    for args in (["systemctl", "daemon-reload"], ["systemctl", "enable", "--now", f"{UNIT}.timer"]):
        result = run(args)
        if result.returncode != 0:
            raise backup.BackupError(f"{' '.join(args)} failed\n{result.stderr}")
    audit = config.audit
    echo(
        f"== Audit retention every night: events kept {audit.keep_events_days} days, "
        f"question texts {audit.keep_question_days}"
    )
