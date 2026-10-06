"""``synapsectl``: init, render, doctor, apply, backup, restore, upgrade and support-bundle
(ADR 0012)."""

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import ValidationError

from synapsectl import (
    __version__,
    backup,
    config,
    doctor,
    models,
    render,
    secrets,
    support,
    upgrade,
    wizard,
)
from synapsectl.apply import ApplyError, FirstAdmin, apply

DEFAULT_CONFIG = Path("/etc/synapse/synapse.toml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synapsectl", description="Install and check Synapse.")
    parser.add_argument("--version", action="version", version=f"synapsectl {__version__}")
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG, help=f"default: {DEFAULT_CONFIG}"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser(
        "init", help="Create synapse.toml (interactively) and the secrets, then render."
    )
    init.add_argument(
        "--from", dest="source", type=Path, help="Use this synapse.toml instead of asking"
    )
    commands.add_parser("render", help="Render the installation files from synapse.toml.")
    check = commands.add_parser("doctor", help="Check that the installation can run.")
    check.add_argument(
        "--running", action="store_true", help="The stack is running, so its ports are in use"
    )
    up = commands.add_parser(
        "apply", help="Install, repair or upgrade: run every setup step, then start the services."
    )
    up.add_argument("--admin-email", help="First administrator (needed only on the first run)")
    up.add_argument("--admin-name", help="First administrator's display name")
    up.add_argument(
        "--admin-password-file", type=Path, help="Read its password from this file, not a prompt"
    )
    files = commands.add_parser(
        "models", help="Get or check the model files (default: as synapse.toml sets them)."
    )
    files.add_argument("action", choices=["fetch", "check"])
    files.add_argument("--dir", type=Path, help="Model directory (default: models.dir)")
    files.add_argument(
        "--accelerator",
        choices=[a.value for a in models.Accelerator],
        help="Files for this accelerator (default: models.accelerator)",
    )
    files.add_argument(
        "--verify", action="store_true", help="check: also compare every file's SHA-256 (slow)"
    )
    saving = commands.add_parser(
        "backup", help="Take a backup (run), or set up, list or verify the backups."
    )
    saving.add_argument(
        "action", nargs="?", default="run", choices=["run", "init", "list", "verify"]
    )
    saving.add_argument("--snapshot", default="latest", help="verify: this snapshot")
    back = commands.add_parser(
        "restore", help="Replace this installation's data with a backup's (then run apply)."
    )
    back.add_argument("--snapshot", default="latest", help="default: the latest")
    back.add_argument(
        "--replace", action="store_true", help="Restore over a database that holds data"
    )
    back.add_argument("--yes", action="store_true", help="Do not ask for confirmation")
    back.add_argument(
        "--configuration-from",
        type=Path,
        metavar="REPOSITORY",
        help="On a new machine: first restore synapse.toml and the secrets from this repository",
    )
    back.add_argument(
        "--password-file", type=Path, help="With --configuration-from: the backup password"
    )
    release = commands.add_parser(
        "upgrade", help="Move to another release: take a backup, then apply the release."
    )
    release.add_argument("--to", required=True, metavar="VERSION", help="The release's version")
    bundle = commands.add_parser(
        "support-bundle", help="Write the versions, checks and recent logs, redacted, to one file."
    )
    bundle.add_argument(
        "--output", type=Path, help="default: synapse-support-SLUG-TIME.tar.gz in this directory"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            return _init(args.config, args.source)
        if args.command == "restore" and args.configuration_from:
            return _restore_configuration(args)
        if args.command == "models" and args.dir and args.accelerator:
            accelerator = models.Accelerator(args.accelerator)
            return _models(args.action, args.dir, accelerator, verify=args.verify)
        loaded = config.load(args.config)
    except FileNotFoundError as error:
        print(f"error: {error.filename} not found (run: synapsectl init)", file=sys.stderr)
        return 1
    except ValidationError as error:
        print(f"error: invalid configuration:\n{error}", file=sys.stderr)
        return 1
    commands: dict[str, Callable[[], int]] = {
        "apply": lambda: _apply(loaded, args),
        "models": lambda: _models(
            args.action,
            args.dir or loaded.models.dir,
            models.Accelerator(args.accelerator or loaded.models.accelerator),
            verify=args.verify,
        ),
        "render": lambda: _render(loaded),
        "doctor": lambda: _doctor(loaded, running=args.running),
        "backup": lambda: _backup(loaded, args),
        "restore": lambda: _restore(loaded, args),
        "upgrade": lambda: _upgrade(loaded, args),
        "support-bundle": lambda: _support_bundle(loaded, args),
    }
    return commands[args.command]()


def _render(loaded: config.SynapseConfig) -> int:
    for path in render.write(loaded, render.render(loaded)):
        print(f"rendered {path}")
    return 0


def _doctor(loaded: config.SynapseConfig, *, running: bool) -> int:
    results = doctor.run_checks(loaded, stack_running=running)
    for result in results:
        print(f"{result.status:<4}  {result.name}: {result.detail}")
    return 1 if any(result.status is doctor.Status.FAIL for result in results) else 0


def _init(path: Path, source: Path | None) -> int:
    if path.exists():
        print(f"error: {path} exists; edit it and run: synapsectl render", file=sys.stderr)
        return 1
    chosen = config.load(source) if source else wizard.run()
    config.save(chosen, path)
    created = secrets.generate(chosen)
    render.write(chosen, render.render(chosen))
    print(f"\nwrote {path}")
    print(f"secrets in {chosen.paths.secrets_dir}: {len(created)} created")
    print(f"rendered files in {chosen.paths.render_dir}")
    print("next: synapsectl doctor, then synapsectl apply --admin-email ... --admin-name ...")
    return 0


def _models(action: str, directory: Path, accelerator: models.Accelerator, *, verify: bool) -> int:
    if action == "fetch":
        try:
            models.fetch(directory, accelerator)
        except (models.FetchError, OSError, subprocess.CalledProcessError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        return 0
    found = models.problems(directory, accelerator, verify=verify)
    for problem in found:
        print(f"error: {problem}", file=sys.stderr)
    if not found:
        print(f"model files for {accelerator}: all present in {directory}")
    return 1 if found else 0


def _apply(loaded: config.SynapseConfig, args: argparse.Namespace) -> int:
    if bool(args.admin_email) != bool(args.admin_name):
        print("error: give --admin-email and --admin-name together", file=sys.stderr)
        return 1
    admin = (
        FirstAdmin(args.admin_email, args.admin_name, args.admin_password_file)
        if args.admin_email
        else None
    )
    try:
        apply(loaded, admin=admin)
        if loaded.backup.repository is not None:
            _schedule_backups(loaded, args.config)
    except (ApplyError, backup.BackupError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


# Present when systemd runs the machine.
SYSTEMD_RUNTIME = Path("/run/systemd/system")


def _schedule_backups(loaded: config.SynapseConfig, config_file: Path) -> None:
    if os.geteuid() == 0 and SYSTEMD_RUNTIME.is_dir():
        backup.install_schedule(loaded, config_file.resolve())
    else:
        print(
            "== Backups are not scheduled (needs root and systemd): run "
            "synapsectl backup every night and synapsectl backup verify every quarter"
        )


def _backup(loaded: config.SynapseConfig, args: argparse.Namespace) -> int:
    try:
        if args.action == "init":
            # [backup] added to an installation: its password, and the files with the containers
            if "backup_password" in secrets.generate(loaded):
                print(f"== Created {loaded.paths.secrets_dir / 'backup_password'}")
            render.write(loaded, render.render(loaded))
            backup.init_repository(loaded)
        elif args.action == "list":
            for snapshot in backup.snapshots(loaded):
                print(f"{snapshot['short_id']}  {snapshot['time'][:19]}")
        elif args.action == "verify":
            backup.verify(loaded, snapshot=args.snapshot)
        else:
            backup.backup(loaded, args.config.resolve())
    except (backup.BackupError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def _restore(loaded: config.SynapseConfig, args: argparse.Namespace) -> int:
    if not args.yes:
        print(
            f"This replaces the database and the uploaded files of {loaded.instance.organization} "
            f"with the backup's ({args.snapshot})."
        )
        answer = input(f"Type the installation's slug ({loaded.instance.slug}) to go on: ")
        if answer.strip() != loaded.instance.slug:
            print("error: not confirmed; nothing was changed", file=sys.stderr)
            return 1
    try:
        backup.restore(loaded, snapshot=args.snapshot, replace=args.replace)
    except (backup.BackupError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def _upgrade(loaded: config.SynapseConfig, args: argparse.Namespace) -> int:
    try:
        upgrade.upgrade(loaded, args.config.resolve(), args.to)
    except (upgrade.UpgradeError, backup.BackupError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def _support_bundle(loaded: config.SynapseConfig, args: argparse.Namespace) -> int:
    try:
        support.write_bundle(
            loaded, args.config.resolve(), args.output or support.default_output(loaded)
        )
    except (support.SupportError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def _restore_configuration(args: argparse.Namespace) -> int:
    if args.password_file is None:
        print("error: --configuration-from needs --password-file", file=sys.stderr)
        return 1
    try:
        backup.restore_configuration(
            args.configuration_from, args.password_file, args.config, snapshot=args.snapshot
        )
    except (backup.BackupError, OSError, ValidationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0
