"""What maintenance did, kept for the operations page (ADR 0014).

Backups and their verifications run on the host (ADR 0021) and are recorded by synapsectl
through ``synapse operations record``; the scheduler records its nightly file sweep and audit
verification. A run is one row; the page shows the latest of each kind, and the latest that
succeeded.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, get_args
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

type JsonValue = str | int | float | bool | None
RunKind = Literal["backup", "backup_verify", "files_sweep", "audit_verify"]
RUN_KINDS: tuple[RunKind, ...] = get_args(RunKind)
# Details longer than this, as JSON, are cut to their first entries (the column allows 4000).
MAX_DETAILS = 3000


@dataclass(frozen=True)
class Run:
    kind: RunKind
    ok: bool
    started_at: datetime
    finished_at: datetime
    details: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class LatestRuns:
    """The latest run of each kind, and the latest that succeeded; a kind never run is absent."""

    latest: dict[RunKind, Run]
    latest_ok: dict[RunKind, Run]


async def record_run(connection: AsyncConnection, tenant_id: UUID, run: Run) -> None:
    details = dict(run.details)
    while details and len(json.dumps(details)) > MAX_DETAILS:
        details.popitem()
    await connection.execute(
        "INSERT INTO operation_runs (tenant_id, kind, ok, started_at, finished_at, details) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (tenant_id, run.kind, run.ok, run.started_at, run.finished_at, Jsonb(details)),
    )


LATEST = (
    "SELECT DISTINCT ON (kind) kind, ok, started_at, finished_at, details FROM operation_runs "
    "ORDER BY kind, finished_at DESC"
)
LATEST_OK = (
    "SELECT DISTINCT ON (kind) kind, ok, started_at, finished_at, details FROM operation_runs "
    "WHERE ok ORDER BY kind, finished_at DESC"
)


async def latest_runs(connection: AsyncConnection) -> LatestRuns:
    return LatestRuns(await _runs(connection, LATEST), await _runs(connection, LATEST_OK))


async def _runs(connection: AsyncConnection, query: str) -> dict[RunKind, Run]:
    cursor = await connection.execute(query)
    return {
        kind: Run(kind, ok, started_at, finished_at, details)
        for kind, ok, started_at, finished_at, details in await cursor.fetchall()
    }
