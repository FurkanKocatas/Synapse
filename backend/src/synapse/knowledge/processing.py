"""Processing a document version in the worker (ADR 0003, ADR 0010).

``ingest.parse_version`` runs for every uploaded version:

1. In one short transaction: lock the version, skip it if the document was deleted or the
   version is no longer queued, and mark it ``parsing``.
2. Outside any transaction: extract the text (this can take a while).
3. In one transaction: lock again, re-check that the document still exists (a delete during
   parsing wins), replace the version's pages and mark it ``parsed``, or ``ocr`` with an
   ``ingest.ocr_version`` job when any page needs OCR.

``ingest.ocr_version`` reads those pages (knowledge/ocr.py). Each page is written in its own
transaction as soon as it is read, so a retry after a crash starts where the last run stopped
(pages already read carry their engine), and a delete stops the job at the next page. When
every page is done the version is ``parsed``. A page an engine fails on keeps its text.

A file that cannot be read marks the version ``failed`` with the parser's reason code, without
retries. Any other error is retried by the worker; after the last attempt the version is marked
``failed`` with ``internal_error``, so it never stays "in progress".
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import structlog
from psycopg import AsyncConnection

from synapse.jobs.queue import Queue, enqueue
from synapse.jobs.worker import Args, BadJobError, Task
from synapse.kernel.database import Database
from synapse.knowledge.blobs import LocalBlobStore
from synapse.knowledge.filetypes import MediaType
from synapse.knowledge.ocr import (
    OcrError,
    PageReader,
    PageReading,
    better_text,
    prepare_image,
    render_pdf_page,
    temporary_directory,
)
from synapse.knowledge.parsing import Page, Parsed, ParseError, Parser
from synapse.knowledge.pipeline import OCR_TASK, PARSE_TASK, ocr_job

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _Claimed:
    document_id: UUID
    sha256: bytes
    media_type: MediaType


class Processor:
    def __init__(
        self, database: Database, blobs: LocalBlobStore, parser: Parser, reader: PageReader
    ) -> None:
        self._db = database
        self._blobs = blobs
        self._parser = parser
        self._reader = reader

    def tasks(self) -> list[Task]:
        return [
            Task(PARSE_TASK, Queue.INGEST, self.parse, on_final_failure=self.give_up),
            Task(OCR_TASK, Queue.OCR, self.ocr, on_final_failure=self.give_up_ocr),
        ]

    async def parse(self, tenant_id: UUID, args: Args) -> None:
        version_id = _version_id(args)
        async with self._db.tenant_transaction(tenant_id) as connection:
            claimed = await _claim(connection, version_id, "queued", "parsing")
            if claimed is not None:
                await _set_status(connection, version_id, "parsing")
        if claimed is None:
            return
        path = self._blobs.path(tenant_id, claimed.sha256)
        try:
            parsed = await asyncio.to_thread(self._parser.parse, path, claimed.media_type)
        except ParseError as error:
            await self._fail(tenant_id, version_id, error.reason, ("queued", "parsing"))
            return
        needs_ocr = sum(page.needs_ocr for page in parsed.pages)
        async with self._db.tenant_transaction(tenant_id) as connection:
            if not await _still_wanted(connection, version_id, "parsing"):
                log.info("ingest.parse.dropped", version_id=str(version_id))
                return
            await _store_pages(connection, tenant_id, version_id, parsed)
            await _set_status(connection, version_id, "ocr" if needs_ocr else "parsed")
            if needs_ocr:
                await enqueue(connection, tenant_id, ocr_job(claimed.document_id, version_id))
        log.info(
            "ingest.parsed",
            version_id=str(version_id),
            pages=len(parsed.pages),
            needs_ocr=needs_ocr,
        )

    async def ocr(self, tenant_id: UUID, args: Args) -> None:
        version_id = _version_id(args)
        async with self._db.tenant_transaction(tenant_id) as connection:
            claimed = await _claim(connection, version_id, "ocr")
            pending = await _pages_to_read(connection, version_id) if claimed else []
        if claimed is None:
            return
        path = self._blobs.path(tenant_id, claimed.sha256)
        failed = 0
        with temporary_directory() as directory:
            for page in pending:
                try:
                    reading = await asyncio.to_thread(
                        self._read, path, claimed.media_type, page.number, Path(directory)
                    )
                except OcrError:
                    log.warning(
                        "ingest.ocr.page_failed", version_id=str(version_id), page=page.number
                    )
                    failed += 1
                    continue
                async with self._db.tenant_transaction(tenant_id) as connection:
                    if not await _still_wanted(connection, version_id, "ocr"):
                        log.info("ingest.ocr.dropped", version_id=str(version_id))
                        return
                    await _store_reading(connection, version_id, page, reading)
        async with self._db.tenant_transaction(tenant_id) as connection:
            if await _still_wanted(connection, version_id, "ocr"):
                await _set_status(connection, version_id, "parsed")
        log.info("ingest.ocr.done", version_id=str(version_id), pages=len(pending), failed=failed)

    def _read(self, path: Path, media_type: MediaType, number: int, directory: Path) -> PageReading:
        if media_type is MediaType.PDF:
            image = render_pdf_page(path, number, directory)
        else:
            image = prepare_image(path, directory)
        try:
            return self._reader.read(image)
        finally:
            image.unlink()

    async def give_up(self, tenant_id: UUID, args: Args, error: str) -> None:
        log.error("ingest.parse.gave_up", error=error)
        await self._fail(tenant_id, _version_id(args), "internal_error", ("queued", "parsing"))

    async def give_up_ocr(self, tenant_id: UUID, args: Args, error: str) -> None:
        log.error("ingest.ocr.gave_up", error=error)
        await self._fail(tenant_id, _version_id(args), "internal_error", ("ocr",))

    async def _fail(
        self, tenant_id: UUID, version_id: UUID, reason: str, statuses: tuple[str, ...]
    ) -> None:
        async with self._db.tenant_transaction(tenant_id) as connection:
            await connection.execute(
                "UPDATE document_versions SET status = 'failed', failure = %s "
                "WHERE id = %s AND status = ANY(%s)",
                (reason, version_id, list(statuses)),
            )


def _version_id(args: Args) -> UUID:
    try:
        return UUID(str(args["version_id"]))
    except (KeyError, ValueError) as error:
        raise BadJobError("job has no valid version_id") from error


async def _claim(connection: AsyncConnection, version_id: UUID, *statuses: str) -> _Claimed | None:
    """Lock the version; None if its document is deleted or it is in none of ``statuses``.

    A retry after a crash finds the version in the status its last run set, so the status a
    job moves the version to is always one of the statuses it accepts.
    """
    cursor = await connection.execute(
        "SELECT v.status, v.blob_sha256, b.media_type, d.deleted_at IS NOT NULL, d.id "
        "FROM document_versions v JOIN documents d ON d.id = v.document_id "
        "JOIN blobs b ON b.sha256 = v.blob_sha256 "
        "WHERE v.id = %s FOR UPDATE OF v",
        (version_id,),
    )
    row = await cursor.fetchone()
    if row is None or row[3] or row[0] not in statuses:
        return None
    return _Claimed(document_id=row[4], sha256=row[1], media_type=MediaType(row[2]))


async def _set_status(connection: AsyncConnection, version_id: UUID, status: str) -> None:
    await connection.execute(
        "UPDATE document_versions SET status = %s WHERE id = %s", (status, version_id)
    )


async def _still_wanted(connection: AsyncConnection, version_id: UUID, status: str) -> bool:
    cursor = await connection.execute(
        "SELECT v.status = %s AND d.deleted_at IS NULL "
        "FROM document_versions v JOIN documents d ON d.id = v.document_id "
        "WHERE v.id = %s FOR UPDATE OF v, d",
        (status, version_id),
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
            "needs_ocr, quality_issue, char_score, artefacts) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    tenant_id,
                    version_id,
                    p.number,
                    p.kind,
                    p.label,
                    p.text,
                    p.needs_ocr,
                    p.issue,
                    p.char_score,
                    p.artefacts,
                )
                for p in parsed.pages
            ],
        )


async def _pages_to_read(connection: AsyncConnection, version_id: UUID) -> list[Page]:
    cursor = await connection.execute(
        "SELECT number, kind, text, quality_issue, char_score, artefacts FROM document_pages "
        "WHERE version_id = %s AND needs_ocr AND ocr_engine IS NULL ORDER BY number",
        (version_id,),
    )
    return [
        Page(number, kind, text, issue=issue, char_score=score, artefacts=artefacts)
        for number, kind, text, issue, score, artefacts in await cursor.fetchall()
    ]


@dataclass(frozen=True)
class PageUpdate:
    text: str
    text_source: str
    ocr_engine: str
    extra_identifiers: list[str]
    uncertain_identifiers: list[str]


def page_update(page: Page, reading: PageReading) -> PageUpdate:
    text, from_ocr = better_text(page, reading.text)
    return PageUpdate(
        text=text,
        text_source="ocr" if from_ocr else "layer",
        ocr_engine=reading.engine,
        # The identifiers describe the OCR text; kept only when the page keeps that text.
        extra_identifiers=list(reading.extra_identifiers) if from_ocr else [],
        uncertain_identifiers=list(reading.uncertain_identifiers) if from_ocr else [],
    )


async def _store_reading(
    connection: AsyncConnection, version_id: UUID, page: Page, reading: PageReading
) -> None:
    update = page_update(page, reading)
    await connection.execute(
        "UPDATE document_pages SET text = %s, text_source = %s, ocr_engine = %s, "
        "extra_identifiers = %s, uncertain_identifiers = %s "
        "WHERE version_id = %s AND number = %s",
        (
            update.text,
            update.text_source,
            update.ocr_engine,
            update.extra_identifiers,
            update.uncertain_identifiers,
            version_id,
            page.number,
        ),
    )
