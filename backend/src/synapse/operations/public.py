"""The operations package's public interface. Other packages import from here only."""

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from synapse.kernel.database import Database
from synapse.operations.overview import (
    PROBLEMS,
    Overview,
    Pages,
    QueueState,
    Server,
    Service,
    Storage,
    overview,
)
from synapse.operations.runs import RUN_KINDS, LatestRuns, Run, RunKind, latest_runs, record_run


class Operations:
    """The operations page's figures, and the record of maintenance runs."""

    def __init__(
        self, database: Database, *, tenant_id: UUID, blob_dir: Path, servers: Sequence[Server]
    ) -> None:
        self._db = database
        self._tenant_id = tenant_id
        self._blob_dir = blob_dir
        self._servers = servers

    async def overview(self) -> Overview:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            return await overview(connection, self._tenant_id, self._blob_dir, self._servers)

    async def record(self, run: Run) -> None:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            await record_run(connection, self._tenant_id, run)


__all__ = [
    "PROBLEMS",
    "RUN_KINDS",
    "LatestRuns",
    "Operations",
    "Overview",
    "Pages",
    "QueueState",
    "Run",
    "RunKind",
    "Server",
    "Service",
    "Storage",
    "latest_runs",
    "record_run",
]
