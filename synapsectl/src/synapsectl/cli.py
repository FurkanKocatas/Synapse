"""``synapsectl``: init, render and doctor (ADR 0012)."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from synapsectl import __version__, config, doctor, render, secrets, wizard

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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            return _init(args.config, args.source)
        loaded = config.load(args.config)
    except FileNotFoundError as error:
        print(f"error: {error.filename} not found (run: synapsectl init)", file=sys.stderr)
        return 1
    except ValidationError as error:
        print(f"error: invalid configuration:\n{error}", file=sys.stderr)
        return 1
    if args.command == "render":
        for path in render.write(loaded, render.render(loaded)):
            print(f"rendered {path}")
        return 0
    results = doctor.run_checks(loaded, stack_running=args.running)
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
    print("next: synapsectl doctor")
    return 0
