"""Command line entry point: ``synapse <role>`` and ``synapse db <command>``.

One image runs in several roles (ADR 0002). Each role is a subcommand; only roles that exist are
listed here. The ``db`` commands are run by the installer and by operators.
"""

import argparse
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from synapse import __version__
from synapse.dbadmin import bootstrap, migrate
from synapse.kernel.config import get_settings
from synapse.kernel.logging import configure_logging
from synapse.kernel.secrets import read_secret


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synapse", description="Synapse process launcher.")
    parser.add_argument("--version", action="version", version=f"synapse {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("api", help="Run the HTTP API.")

    database = commands.add_parser("db", help="Database administration.")
    database_commands = database.add_subparsers(dest="db_command", required=True)
    setup = database_commands.add_parser(
        "bootstrap", help="Create or repair the database, roles and schema (needs a superuser)."
    )
    setup.add_argument(
        "--admin-conninfo-file",
        type=Path,
        required=True,
        help="File with a superuser connection string, e.g. postgresql://postgres:...@host/postgres",
    )
    setup.add_argument(
        "--secrets-dir",
        type=Path,
        required=True,
        help="Directory with one password file per role (db_synapse_migrator, db_synapse_api, ...)",
    )
    database_commands.add_parser("migrate", help="Apply migrations (connects as the migrator).")

    args = parser.parse_args(argv)
    if args.command == "api":
        return _run_api()
    settings = get_settings()
    configure_logging(settings)
    if args.db_command == "bootstrap":
        bootstrap.bootstrap(
            read_secret(args.admin_conninfo_file), settings.db_name, args.secrets_dir
        )
    else:
        migrate.upgrade(settings.database(application_name="synapse-migrate"))
    return 0


def _run_api() -> int:
    settings = get_settings()
    uvicorn.run(
        "synapse.api.app:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        # Our own logging configuration is applied in create_app; keep uvicorn's out of the way.
        log_config=None,
        proxy_headers=True,
        forwarded_allow_ips=settings.trusted_proxy_ips,
    )
    return 0
