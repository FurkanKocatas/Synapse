"""Purging deleted documents and sweeping stray files: the scheduler's jobs (ADR 0002).

- A deleted document's rows go soon after the delete: the delete queues a purge job under the
  document's lock, and Procrastinate starts no job while an earlier one with the same lock is
  waiting or running, so the purge comes after every processing job of the document. It removes
  the versions with their pages, chunks and entities, the document with its grants, and the
  blob rows no other version names; the audit log records the purge.
- Files go only in the nightly sweep, once no blob row has named them for a day. An upload of
  the same bytes takes the blob's advisory lock before it writes the row, as the sweep does
  before it removes a file, and storing bytes again renews their file's time: the sweep never
  removes a file that is being stored again.
- The sweep also removes uploads left half-received for a day, and counts blob rows whose file
  is missing, which only a lost disk or a hand-made change can cause.
- Every hour, deleted documents still waiting for a purge (deleted before purges existed, or
  whose purge failed) get a purge job.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from psycopg import AsyncConnection

from synapse.audit import public as audit
from synapse.audit.public import AuditEvent
from synapse.jobs.queue import Queue, enqueue
from synapse.jobs.worker import Args, BadJobError, Task
from synapse.kernel.database import Database
from synapse.knowledge.blobs import LocalBlobStore
from synapse.knowledge.pipeline import PURGE_DELETED_TASK, PURGE_TASK, SWEEP_TASK, purge_job

log = structlog.get_logger(__name__)

# A file no blob row names is removed after this long.
FILE_GRACE = timedelta(days=1)
# A deleted document's own purge job normally runs within minutes; the hourly check queues one
# for documents deleted longer ago than this.
PURGE_LATE = timedelta(hours=1)
# Schedules, in UTC (Procrastinate's cron).
PURGE_DELETED_CRON = "17 * * * *"
SWEEP_CRON = "40 0 * * *"
# pg_advisory_xact_lock's first key for blobs; the second is a hash of the SHA-256.
BLOB_LOCK = 0x626C6F62


async def lock_blob(connection: AsyncConnection, sha256: bytes) -> None:
    """The blob's advisory lock, held until the transaction ends: uploads take it before they
    write a blob row, the sweep before it removes a file."""
    await connection.execute(
        "SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (BLOB_LOCK, sha256.hex())
    )


class Maintenance:
    def __init__(
        self,
        db: Database,
        blobs: LocalBlobStore,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._db = db
        self._blobs = blobs
        self._now = now

    def tasks(self) -> list[Task]:
        return [
            Task(PURGE_TASK, Queue.MAINTENANCE, self.purge),
            Task(PURGE_DELETED_TASK, Queue.MAINTENANCE, self.purge_late, cron=PURGE_DELETED_CRON),
            Task(SWEEP_TASK, Queue.MAINTENANCE, self.sweep, cron=SWEEP_CRON),
        ]

    async def purge(self, tenant_id: UUID, args: Args) -> None:
        document_id = _document_id(args)
        async with self._db.tenant_transaction(tenant_id) as connection:
            cursor = await connection.execute(
                "SELECT deleted_at IS NOT NULL FROM documents WHERE id = %s FOR UPDATE",
                (document_id,),
            )
            row = await cursor.fetchone()
            if row is None or not row[0]:
                return  # purged already, or not deleted
            await connection.execute(
                "UPDATE documents SET current_version_id = NULL WHERE id = %s", (document_id,)
            )
            cursor = await connection.execute(
                "DELETE FROM document_versions WHERE document_id = %s RETURNING blob_sha256",
                (document_id,),
            )
            named = [bytes(sha256) for (sha256,) in await cursor.fetchall()]
            await connection.execute("DELETE FROM documents WHERE id = %s", (document_id,))
            cursor = await connection.execute(
                "DELETE FROM blobs b WHERE b.sha256 = ANY(%s) AND NOT EXISTS ("
                "SELECT 1 FROM document_versions v WHERE v.blob_sha256 = b.sha256) "
                "RETURNING b.sha256",
                (list(set(named)),),
            )
            released = len(await cursor.fetchall())
            details = {"versions": len(named), "files_released": released}
            await audit.record(
                connection,
                tenant_id,
                AuditEvent(
                    "kb.document.purge",
                    "success",
                    target_type="document",
                    target_id=str(document_id),
                    details=details,
                ),
                self._now(),
            )
        log.info("knowledge.purged", document_id=str(document_id), **details)

    async def purge_late(self, tenant_id: UUID, _args: Args) -> None:
        """Queue a purge for deleted documents that have none waiting."""
        async with self._db.tenant_transaction(tenant_id) as connection:
            cursor = await connection.execute(
                "SELECT d.id FROM documents d WHERE d.deleted_at < %s AND NOT EXISTS ("
                "SELECT 1 FROM procrastinate_jobs j WHERE j.task_name = %s "
                "AND j.status IN ('todo', 'doing') AND j.args->>'document_id' = d.id::text) "
                "ORDER BY d.deleted_at",
                (self._now() - PURGE_LATE, PURGE_TASK),
            )
            late = [document_id for (document_id,) in await cursor.fetchall()]
            for document_id in late:
                await enqueue(connection, tenant_id, purge_job(document_id))
        if late:
            log.warning("knowledge.purge_late", documents=len(late))

    async def sweep(self, tenant_id: UUID, _args: Args) -> None:
        cutoff = self._now() - FILE_GRACE
        on_disk = {blob.sha256: blob.modified for blob in self._blobs.stored(tenant_id)}
        async with self._db.tenant_transaction(tenant_id) as connection:
            cursor = await connection.execute("SELECT sha256 FROM blobs")
            named = {bytes(sha256) for (sha256,) in await cursor.fetchall()}
        stray = [sha256 for sha256 in on_disk if sha256 not in named]
        removed = 0
        for sha256 in sorted(stray):
            if await self._remove_stray(tenant_id, sha256, cutoff):
                removed += 1
        incoming = self._blobs.remove_incoming(cutoff)
        missing = len(named - on_disk.keys())
        report = {"removed": removed, "incoming_removed": incoming, "rows_without_file": missing}
        if missing:
            log.error("knowledge.files_missing", **report)
        else:
            log.info("knowledge.files_swept", **report)

    async def _remove_stray(self, tenant_id: UUID, sha256: bytes, cutoff: datetime) -> bool:
        """Remove one file no row named, unless a row names it now or it was stored lately."""
        async with self._db.tenant_transaction(tenant_id) as connection:
            await lock_blob(connection, sha256)
            cursor = await connection.execute("SELECT 1 FROM blobs WHERE sha256 = %s", (sha256,))
            if await cursor.fetchone() is not None:
                return False
            modified = self._blobs.modified(tenant_id, sha256)
            if modified is None or modified >= cutoff:
                return False
            self._blobs.delete(tenant_id, sha256)
            return True


def _document_id(args: Args) -> UUID:
    try:
        return UUID(str(args["document_id"]))
    except (KeyError, ValueError) as error:
        raise BadJobError("job has no valid document_id") from error
