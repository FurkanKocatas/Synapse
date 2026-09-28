"""Command line entry point: ``synapse <role>``.

One image runs in several roles (ADR 0002). Each role is a subcommand; only roles that
exist are listed here.
"""

import argparse
from collections.abc import Sequence

import uvicorn

from synapse import __version__
from synapse.kernel.config import get_settings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synapse", description="Synapse process launcher.")
    parser.add_argument("--version", action="version", version=f"synapse {__version__}")
    roles = parser.add_subparsers(dest="role", required=True)
    roles.add_parser("api", help="Run the HTTP API.")

    args = parser.parse_args(argv)
    handlers = {"api": _run_api}
    return handlers[args.role]()


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
