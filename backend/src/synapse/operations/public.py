"""The operations package's public interface. Other packages import from here only."""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from uuid import UUID

from synapse.audit import public as audit
from synapse.kernel.database import Database
from synapse.knowledge.public import Retried, retry_failed
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
        self,
        database: Database,
        *,
        tenant_id: UUID,
        blob_dir: Path,
        servers: Sequence[Server],
        embeds: bool = False,
    ) -> None:
        self._db = database
        self._tenant_id = tenant_id
        self._blob_dir = blob_dir
        self._servers = servers
        # Whether an embedding model is configured, for retrying embedding.
        self._embeds = embeds

    async def overview(self) -> Overview:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            return await overview(connection, self._tenant_id, self._blob_dir, self._servers)

    async def record(self, run: Run) -> None:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            await record_run(connection, self._tenant_id, run)

    async def retry(self, user_id: UUID, ip: str | None, now: datetime) -> Retried:
        """Process again what stopped on an error that may not come again; audited."""
        retried = await retry_failed(self._db, self._tenant_id, embed=self._embeds)
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            await audit.record(
                connection,
                self._tenant_id,
                audit.AuditEvent(
                    "ops.documents.retry",
                    "success",
                    actor_user_id=user_id,
                    actor_ip=ip,
                    details={"reprocessing": retried.reprocessing, "embedding": retried.embedding},
                ),
                now,
            )
        return retried


__all__ = [
    "PROBLEMS",
    "RUN_KINDS",
    "LatestRuns",
    "Operations",
    "Overview",
    "Pages",
    "QueueState",
    "Retried",
    "Run",
    "RunKind",
    "Server",
    "Service",
    "Storage",
    "latest_runs",
    "record_run",
]
