"""Command line entry point.

One image runs in several roles (ADR 0002): ``synapse api`` starts a process role, while
``synapse db|tenant|user ...`` are administration commands run by the installer and operators.
Only roles that exist are listed here.
"""

import argparse
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from synapse import __version__, accounts_cli, audit_cli
from synapse.dbadmin import bootstrap, migrate
from synapse.identity.public import PasswordPolicyError
from synapse.kernel.config import get_settings
from synapse.kernel.logging import configure_logging
from synapse.kernel.secrets import read_secret


def build_parser() -> argparse.ArgumentParser:
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

    tenant = commands.add_parser("tenant", help="Tenant administration.")
    tenant_commands = tenant.add_subparsers(dest="tenant_command", required=True)
    new_tenant = tenant_commands.add_parser("create", help="Create a tenant and print its ID.")
    new_tenant.add_argument("--slug", required=True, help="Short lower-case name, e.g. acme")
    new_tenant.add_argument("--name", required=True, help="Display name of the organization")
    new_tenant.add_argument(
        "--id", type=uuid.UUID, help="Use this ID (the installer takes it from synapse.toml)"
    )
    new_tenant.add_argument(
        "--if-missing",
        action="store_true",
        help="Succeed without changes if a tenant with this ID and slug exists (needs --id)",
    )

    user = commands.add_parser("user", help="Account administration.")
    user_commands = user.add_subparsers(dest="user_command", required=True)
    new_user = user_commands.add_parser("create", help="Create an account in SYNAPSE_TENANT_ID.")
    new_user.add_argument("--email", required=True)
    new_user.add_argument("--name", required=True, help="Display name")
    new_user.add_argument("--role", required=True, choices=["admin", "editor", "member", "auditor"])
    new_user.add_argument("--locale", default="tr", choices=["tr", "en"])
    new_user.add_argument(
        "--password-file", type=Path, help="Read the password from a file instead of prompting"
    )
    new_user.add_argument(
        "--unless-admin-exists",
        action="store_true",
        help="Do nothing if the tenant already has an active administrator (for the installer)",
    )

    user_commands.add_parser(
        "admins", help="Print how many active administrators SYNAPSE_TENANT_ID has."
    )

    audit = commands.add_parser("audit", help="Audit log checks.")
    audit_commands = audit.add_subparsers(dest="audit_command", required=True)
    audit_commands.add_parser("verify", help="Recompute the whole hash chain; exit 1 if broken.")
    audit_commands.add_parser(
        "checkpoint", help="Print a signed checkpoint of the chain head, for export off the box."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "api":
        return _run_api()
    try:
        return _run_admin_command(args)
    except (accounts_cli.CommandError, audit_cli.AuditCommandError, PasswordPolicyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _run_admin_command(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)
    if args.command == "db":
        if args.db_command == "bootstrap":
            bootstrap.bootstrap(
                read_secret(args.admin_conninfo_file), settings.db_name, args.secrets_dir
            )
        else:
            migrate.upgrade(settings.database(application_name="synapse-migrate"))
    elif args.command == "audit":
        if args.audit_command == "verify":
            intact, report = audit_cli.verify(settings)
            print(report)
            return 0 if intact else 1
        print(audit_cli.checkpoint(settings))
    elif args.command == "tenant":
        if args.if_missing and args.id is None:
            raise accounts_cli.CommandError("--if-missing needs --id")
        print(
            accounts_cli.create_tenant(
                settings, args.slug, args.name, tenant_id=args.id, if_missing=args.if_missing
            )
        )
    elif args.user_command == "admins":
        print(accounts_cli.active_admins(settings))
    elif args.unless_admin_exists and accounts_cli.active_admins(settings) > 0:
        print("skipped: an active administrator exists")
    else:
        user_id = accounts_cli.create_user(
            settings,
            email=args.email,
            display_name=args.name,
            role=args.role,
            locale=args.locale,
            password=accounts_cli.read_new_password(args.password_file),
        )
        print(user_id)
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
