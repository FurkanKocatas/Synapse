"""Processing a document version in the worker (ADR 0003, ADR 0010).

``ingest.parse_version`` runs for every uploaded version:

1. In one short transaction: lock the version, skip it if the document was deleted or the
   version is no longer queued, and mark it ``parsing``.
2. Outside any transaction: extract the text (this can take a while).
3. In one transaction: lock again, re-check that the document still exists (a delete during
   parsing wins), replace the version's pages and mark it ``parsed``.

A file that cannot be read marks the version ``failed`` with the parser's reason code, without
retries. Any other error is retried by the worker; after the last attempt the version is marked
``failed`` with ``internal_error``, so it never stays "in progress".
"""

import asyncio
from dataclasses import dataclass
from uuid import UUID

import structlog
from psycopg import AsyncConnection

from synapse.jobs.queue import Queue
from synapse.jobs.worker import Args, BadJobError, Task
from synapse.kernel.database import Database
from synapse.knowledge.blobs import LocalBlobStore
from synapse.knowledge.filetypes import MediaType
from synapse.knowledge.parsing import Parsed, ParseError, Parser
from synapse.knowledge.pipeline import PARSE_TASK

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _Claimed:
    sha256: bytes
    media_type: MediaType


class Processor:
    def __init__(self, database: Database, blobs: LocalBlobStore, parser: Parser) -> None:
        self._db = database
        self._blobs = blobs
        self._parser = parser

    def tasks(self) -> list[Task]:
        return [Task(PARSE_TASK, Queue.INGEST, self.parse, on_final_failure=self.give_up)]

    async def parse(self, tenant_id: UUID, args: Args) -> None:
        version_id = _version_id(args)
        async with self._db.tenant_transaction(tenant_id) as connection:
            claimed = await _claim(connection, version_id)
        if claimed is None:
            return
        path = self._blobs.path(tenant_id, claimed.sha256)
        try:
            parsed = await asyncio.to_thread(self._parser.parse, path, claimed.media_type)
        except ParseError as error:
            await self._fail(tenant_id, version_id, error.reason)
            return
        async with self._db.tenant_transaction(tenant_id) as connection:
            if not await _still_wanted(connection, version_id):
                log.info("ingest.parse.dropped", version_id=str(version_id))
                return
            await _store_pages(connection, tenant_id, version_id, parsed)
            await connection.execute(
                "UPDATE document_versions SET status = 'parsed' WHERE id = %s", (version_id,)
            )
        log.info(
            "ingest.parsed",
            version_id=str(version_id),
            pages=len(parsed.pages),
            needs_ocr=sum(page.needs_ocr for page in parsed.pages),
        )

    async def give_up(self, tenant_id: UUID, args: Args, error: str) -> None:
        log.error("ingest.parse.gave_up", error=error)
        await self._fail(tenant_id, _version_id(args), "internal_error")

    async def _fail(self, tenant_id: UUID, version_id: UUID, reason: str) -> None:
        async with self._db.tenant_transaction(tenant_id) as connection:
            await connection.execute(
                "UPDATE document_versions SET status = 'failed', failure = %s "
                "WHERE id = %s AND status IN ('queued', 'parsing')",
                (reason, version_id),
            )


def _version_id(args: Args) -> UUID:
    try:
        return UUID(str(args["version_id"]))
    except (KeyError, ValueError) as error:
        raise BadJobError("job has no valid version_id") from error


async def _claim(connection: AsyncConnection, version_id: UUID) -> _Claimed | None:
    cursor = await connection.execute(
        "SELECT v.status, v.blob_sha256, b.media_type, d.deleted_at IS NOT NULL "
        "FROM document_versions v JOIN documents d ON d.id = v.document_id "
        "JOIN blobs b ON b.sha256 = v.blob_sha256 "
        "WHERE v.id = %s FOR UPDATE OF v",
        (version_id,),
    )
    row = await cursor.fetchone()
    # A retry after a crash finds the version in 'parsing' and takes it again.
    if row is None or row[3] or row[0] not in ("queued", "parsing"):
        return None
    await connection.execute(
        "UPDATE document_versions SET status = 'parsing' WHERE id = %s", (version_id,)
    )
    return _Claimed(sha256=row[1], media_type=MediaType(row[2]))


async def _still_wanted(connection: AsyncConnection, version_id: UUID) -> bool:
    cursor = await connection.execute(
        "SELECT v.status = 'parsing' AND d.deleted_at IS NULL "
        "FROM document_versions v JOIN documents d ON d.id = v.document_id "
        "WHERE v.id = %s FOR UPDATE OF v, d",
        (version_id,),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


async def _store_pages(
    connection: AsyncConnection, tenant_id: UUID, version_id: UUID, parsed: Parsed
) -> None:
    await connection.execute("DELETE FROM document_pages WHERE version_id = %s", (version_id,))
    async with connection.cursor() as cursor:
        await cursor.executemany(
            "INSERT INTO document_pages (tenant_id, version_id, number, kind, label, text, "
            "needs_ocr) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [
                (tenant_id, version_id, p.number, p.kind, p.label, p.text, p.needs_ocr)
                for p in parsed.pages
            ],
        )
