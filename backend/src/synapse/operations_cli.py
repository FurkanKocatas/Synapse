"""``synapse operations record``: synapsectl records a backup or its verification, which run on
the host (ADR 0021), for the operations page."""

import asyncio
import json
from datetime import datetime

from synapse.kernel.config import Settings
from synapse.kernel.database import Database
from synapse.operations.public import RUN_KINDS, Operations, Run


class OperationsCommandError(RuntimeError):
    """A problem the operator can fix; printed without a traceback."""


def run_from(kind: str, *, ok: bool, started: str, finished: str, details: str) -> Run:
    if kind not in RUN_KINDS:
        raise OperationsCommandError(f"unknown kind {kind!r}")
    try:
        parsed = json.loads(details)
        run = Run(
            kind,
            ok,
            datetime.fromisoformat(started),
            datetime.fromisoformat(finished),
            parsed,
        )
    except ValueError as error:
        raise OperationsCommandError(f"invalid run: {error}") from error
    if not isinstance(parsed, dict):
        raise OperationsCommandError("details must be a JSON object")
    if run.started_at.tzinfo is None or run.finished_at.tzinfo is None:
        raise OperationsCommandError("times must carry their offset from UTC")
    return run


def record(settings: Settings, run: Run) -> None:
    tenant_id = settings.tenant_id
    if tenant_id is None:
        raise OperationsCommandError("SYNAPSE_TENANT_ID is not set")

    async def write() -> None:
        database = Database(settings.database(application_name="synapse-operations"), max_size=1)
        await database.open()
        try:
            operations = Operations(
                database, tenant_id=tenant_id, blob_dir=settings.blob_dir, servers=[]
            )
            await operations.record(run)
        finally:
            await database.close()

    asyncio.run(write())
