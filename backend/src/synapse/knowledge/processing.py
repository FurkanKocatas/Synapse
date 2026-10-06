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

Chunks are stored when the text is final, with the document's context (``document_context``).
With an embedding model configured, ``ingest.embed_version`` follows: the version is
``embedding`` while batches of its chunks are embedded (context in front) and each batch is
written in its own transaction, so a retry embeds only what is left; then it is ``ready``. If
the model stays unreachable, the version goes back to ``parsed`` with ``embedding_failure`` set
(``model_unavailable``, for example), not ``failed``: its text stays readable and searchable by
words, only without vectors, and a later embedding job picks it up again.

A file that cannot be read marks the version ``failed`` with the parser's reason code, without
retries. Any other error is retried by the worker; after the last attempt the version is marked
``failed`` with ``internal_error``, so it never stays "in progress".
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from synapse.jobs.queue import Queue, enqueue
from synapse.jobs.worker import Args, BadJobError, Task
from synapse.kernel.database import Database
from synapse.knowledge.blobs import LocalBlobStore
from synapse.knowledge.chunking import chunk, contextual_text, document_context, indexed_text
from synapse.knowledge.dedup import content_hash, simhash
from synapse.knowledge.entities import extract
from synapse.knowledge.filetypes import MediaType
from synapse.knowledge.headings import blocks_from_text
from synapse.knowledge.metadata import apply_suggestions
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
from synapse.knowledge.pipeline import (
    EMBED_TASK,
    OCR_TASK,
    PARSE_TASK,
    embed_job,
    ocr_job,
    parse_job,
)
from synapse.knowledge.search import lexical_text
from synapse.knowledge.structure import Block
from synapse.models.public import (
    Embedder,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
)

log = structlog.get_logger(__name__)

# Texts per embedding request: the embedding server's slots (synapsectl renders 16).
EMBED_BATCH = 16
# document_versions.context's limit (migration 0014); a context is a name and 30 words.
MAX_CONTEXT = 2000
# The reason codes of document_versions.embedding_failure, by the error the last attempt raised.
EMBEDDING_FAILURES = {
    ModelUnavailableError.__name__: "model_unavailable",
    ModelTimeoutError.__name__: "model_timeout",
    ModelResponseError.__name__: "model_response",
}


@dataclass(frozen=True)
class _Claimed:
    document_id: UUID
    sha256: bytes
    media_type: MediaType


class Processor:
    def __init__(
        self,
        database: Database,
        blobs: LocalBlobStore,
        parser: Parser,
        reader: PageReader,
        embedder: Embedder | None = None,
    ) -> None:
        self._db = database
        self._blobs = blobs
        self._parser = parser
        self._reader = reader
        self._embedder = embedder

    @property
    def embeds(self) -> bool:
        return self._embedder is not None

    def tasks(self) -> list[Task]:
        return [
            Task(PARSE_TASK, Queue.INGEST, self.parse, on_final_failure=self.give_up),
            Task(OCR_TASK, Queue.OCR, self.ocr, on_final_failure=self.give_up_ocr),
            Task(EMBED_TASK, Queue.EMBED, self.embed, on_final_failure=self.give_up_embed),
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
            chunks = 0
            if needs_ocr:
                await enqueue(connection, tenant_id, ocr_job(claimed.document_id, version_id))
            else:
                chunks = await self._chunk(connection, tenant_id, claimed.document_id, version_id)
            await _set_status(connection, version_id, "ocr" if needs_ocr else "parsed")
        log.info(
            "ingest.parsed",
            version_id=str(version_id),
            pages=len(parsed.pages),
            needs_ocr=needs_ocr,
            chunks=chunks,
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
                except OcrError as error:
                    log.warning(
                        "ingest.ocr.page_failed",
                        version_id=str(version_id),
                        page=page.number,
                        error=str(error),
                    )
                    failed += 1
                    continue
                async with self._db.tenant_transaction(tenant_id) as connection:
                    if not await _still_wanted(connection, version_id, "ocr"):
                        log.info("ingest.ocr.dropped", version_id=str(version_id))
                        return
                    await _store_reading(connection, version_id, page, reading)
        chunks = 0
        async with self._db.tenant_transaction(tenant_id) as connection:
            if await _still_wanted(connection, version_id, "ocr"):
                chunks = await self._chunk(connection, tenant_id, claimed.document_id, version_id)
                await _set_status(connection, version_id, "parsed")
        log.info(
            "ingest.ocr.done",
            version_id=str(version_id),
            pages=len(pending),
            failed=failed,
            chunks=chunks,
        )

    async def embed(self, tenant_id: UUID, args: Args) -> None:
        version_id = _version_id(args)
        if self._embedder is None:
            raise BadJobError("no embedding model is configured for this worker")
        pending: list[_Pending] = []
        async with self._db.tenant_transaction(tenant_id) as connection:
            claimed = await _claim(connection, version_id, "parsed", "embedding")
            if claimed is not None:
                await connection.execute(
                    "UPDATE document_versions SET status = 'embedding', embedding_failure = NULL "
                    "WHERE id = %s",
                    (version_id,),
                )
                pending = await _chunks_to_embed(connection, version_id)
        if claimed is None:
            return
        for start in range(0, len(pending), EMBED_BATCH):
            batch = pending[start : start + EMBED_BATCH]
            vectors = await self._embedder.embed([text for _, _, text in batch])
            async with self._db.tenant_transaction(tenant_id) as connection:
                if not await _still_wanted(connection, version_id, "embedding"):
                    log.info("ingest.embed.dropped", version_id=str(version_id))
                    return
                await _store_vectors(connection, version_id, batch, vectors)
        async with self._db.tenant_transaction(tenant_id) as connection:
            if await _still_wanted(connection, version_id, "embedding"):
                await connection.execute(
                    "UPDATE document_versions SET status = 'ready', embedded_with = %s "
                    "WHERE id = %s",
                    (self._embedder.model, version_id),
                )
        log.info("ingest.embedded", version_id=str(version_id), chunks=len(pending))

    async def _chunk(
        self, connection: AsyncConnection, tenant_id: UUID, document_id: UUID, version_id: UUID
    ) -> int:
        """Store the version's chunks and, with a model to embed them, the job that will; and
        suggest the document's kind, date and number from it."""
        chunks = await _store_chunks(connection, tenant_id, version_id)
        await apply_suggestions(connection, document_id, version_id)
        if self._embedder is not None and chunks:
            await enqueue(connection, tenant_id, embed_job(document_id, version_id))
        return chunks

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

    async def give_up_embed(self, tenant_id: UUID, args: Args, error: str) -> None:
        # Not failed: the text is fine and stays searchable by words; vectors are missing.
        log.error("ingest.embed.gave_up", error=error)
        async with self._db.tenant_transaction(tenant_id) as connection:
            await connection.execute(
                "UPDATE document_versions SET status = 'parsed', embedding_failure = %s "
                "WHERE id = %s AND status IN ('parsed', 'embedding')",
                (EMBEDDING_FAILURES.get(error, "internal_error"), _version_id(args)),
            )

    async def _fail(
        self, tenant_id: UUID, version_id: UUID, reason: str, statuses: tuple[str, ...]
    ) -> None:
        async with self._db.tenant_transaction(tenant_id) as connection:
            await connection.execute(
                "UPDATE document_versions SET status = 'failed', failure = %s "
                "WHERE id = %s AND status = ANY(%s)",
                (reason, version_id, list(statuses)),
            )


@dataclass(frozen=True)
class Reindexed:
    terms_written: int
    embedding_queued: int


async def reindex(database: Database, tenant_id: UUID, *, embed: bool) -> Reindexed:
    """Index again what search would miss (``synapse knowledge reindex``).

    Chunks without lexical terms (stored before migration 0016 emptied the column, or before
    0015 added it) get them written in place, from their text and their version's context, so
    chunks and vectors stay. With ``embed`` (an embedding model is configured), every version
    with chunks still lacking a vector (models installed later, or ``embedding_failure``) gets
    an embedding job. Each version is locked as the jobs lock it, and only ``parsed`` or
    ``ready`` ones are touched, so a running job is never raced.
    """
    async with database.tenant_transaction(tenant_id) as connection:
        cursor = await connection.execute(
            "SELECT v.id, bool_or(c.search IS NULL), bool_or(c.embedding IS NULL) "
            "FROM document_versions v JOIN documents d ON d.id = v.document_id "
            "JOIN document_chunks c ON c.version_id = v.id "
            "WHERE d.deleted_at IS NULL AND v.status IN ('parsed', 'ready') GROUP BY v.id"
        )
        candidates = [row for row in await cursor.fetchall() if row[1] or (embed and row[2])]
    written = queued = 0
    for version_id, without_terms, without_vectors in candidates:
        async with database.tenant_transaction(tenant_id) as connection:
            claimed = await _claim(connection, version_id, "parsed", "ready")
            if claimed is None:
                continue
            if without_terms:
                await _write_terms(connection, version_id)
                written += 1
            if embed and without_vectors:
                await enqueue(connection, tenant_id, embed_job(claimed.document_id, version_id))
                queued += 1
    log.info("ingest.reindexed", terms_written=written, embedding_queued=queued)
    return Reindexed(written, queued)


# The newest version of each live document that stopped on an error that may not come again:
# a crash after every retry (``internal_error``), or the embedding model failing.
_RETRYABLE = """
    SELECT latest.id, latest.status FROM documents d
    JOIN LATERAL (
        SELECT v.id, v.status, v.failure, v.embedding_failure FROM document_versions v
        WHERE v.document_id = d.id ORDER BY v.version DESC LIMIT 1
    ) latest ON true
    WHERE d.deleted_at IS NULL
      AND ((latest.status = 'failed' AND latest.failure = 'internal_error')
           OR (latest.status = 'parsed' AND latest.embedding_failure IS NOT NULL))
    ORDER BY latest.id
"""


@dataclass(frozen=True)
class Retried:
    reprocessing: int
    embedding: int


async def retryable(connection: AsyncConnection) -> list[tuple[UUID, str]]:
    """The versions ``retry_failed`` would process again, with their status."""
    cursor = await connection.execute(_RETRYABLE)
    return [(version_id, status) for version_id, status in await cursor.fetchall()]


async def retry_failed(database: Database, tenant_id: UUID, *, embed: bool) -> Retried:
    """Process again what stopped on an error that may not come again (the operations page).

    A version that failed with ``internal_error`` is parsed again from the start, its pages and
    chunks removed first; one left without vectors when the embedding model failed gets an
    embedding job, when a model is configured. A file the parser could not read (``unreadable``,
    ``encrypted``, ...) would fail the same way, and is left as it is. Each version is locked as
    the jobs lock it, and only those statuses are touched, so a running job is never raced.
    """
    async with database.tenant_transaction(tenant_id) as connection:
        found = await retryable(connection)
    reprocessing = embedding = 0
    for version_id, status in found:
        async with database.tenant_transaction(tenant_id) as connection:
            if status == "failed":
                claimed = await _claim(connection, version_id, "failed")
                if claimed is None:
                    continue
                await connection.execute(
                    "DELETE FROM document_chunks WHERE version_id = %s", (version_id,)
                )
                await connection.execute(
                    "DELETE FROM document_pages WHERE version_id = %s", (version_id,)
                )
                cursor = await connection.execute(
                    "UPDATE document_versions SET status = 'queued', failure = NULL "
                    "WHERE id = %s AND failure = 'internal_error'",
                    (version_id,),
                )
                if cursor.rowcount:
                    await enqueue(connection, tenant_id, parse_job(claimed.document_id, version_id))
                    reprocessing += 1
            elif embed:
                claimed = await _claim(connection, version_id, "parsed")
                if claimed is None:
                    continue
                await enqueue(connection, tenant_id, embed_job(claimed.document_id, version_id))
                embedding += 1
    log.info("ingest.retried", reprocessing=reprocessing, embedding=embedding)
    return Retried(reprocessing, embedding)


async def _write_terms(connection: AsyncConnection, version_id: UUID) -> None:
    cursor = await connection.execute(
        "SELECT c.ordinal, coalesce(v.context, ''), c.heading_path, c.text, "
        "array(SELECT i FROM document_pages p CROSS JOIN unnest(p.extra_identifiers) i "
        "WHERE p.version_id = c.version_id AND p.number BETWEEN c.page_start AND c.page_end "
        "ORDER BY p.number) "
        "FROM document_chunks c JOIN document_versions v ON v.id = c.version_id "
        "WHERE c.version_id = %s AND c.search IS NULL",
        (version_id,),
    )
    rows = await cursor.fetchall()
    async with connection.cursor() as update:
        await update.executemany(
            "UPDATE document_chunks SET search = %s WHERE version_id = %s AND ordinal = %s",
            [
                (_terms(context, headings, text, extra), version_id, ordinal)
                for ordinal, context, headings, text, extra in rows
            ],
        )


def _terms(context: str, headings: Sequence[str], text: str, extra: Sequence[str]) -> str:
    """What lexical search reads of a chunk (migration 0016): the terms of its document's
    context, its headings and its text, and the identifiers OCR's second reading found on its
    pages that the text lacks (``extra_identifiers``): search terms only, never shown, so a
    number OCR misread in the text is still found by the reading that got it right."""
    return lexical_text("\n".join([contextual_text(context, headings, text), *extra]))


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
            "needs_ocr, quality_issue, char_score, artefacts, blocks) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
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
                    Jsonb([block.to_json() for block in p.blocks]),
                )
                for p in parsed.pages
            ],
        )


async def _store_chunks(connection: AsyncConnection, tenant_id: UUID, version_id: UUID) -> int:
    """Chunk the version's pages, as they are now, and store the chunks and their entities."""
    cursor = await connection.execute(
        "SELECT number, text_source, blocks, extra_identifiers FROM document_pages "
        "WHERE version_id = %s ORDER BY number",
        (version_id,),
    )
    pages = await cursor.fetchall()
    blocks = [Block.from_json(data) for _, _, page, _ in pages for data in page]
    extra = {number: identifiers for number, _, _, identifiers in pages}
    chunks = chunk(blocks)
    cursor = await connection.execute(
        "SELECT filename FROM document_versions WHERE id = %s", (version_id,)
    )
    row = await cursor.fetchone()
    # The opening words come from pages with a text layer when the document has any: a cover
    # page sent to OCR reads its logo as noise ("il ll \ WW"), which then stood in front of
    # every chunk of 17 of the corpus's 97 documents. A scan has only OCR pages.
    read = {number for number, source, _, _ in pages if source == "ocr"}
    layered = [b for b in blocks if b.page not in read]
    opening = chunk(layered) if layered and read else chunks
    context = document_context(row[0] if row else "", opening)[:MAX_CONTEXT]
    # New chunks have no vectors yet, whatever the old ones had.
    await connection.execute(
        "UPDATE document_versions SET context = %s, embedded_with = NULL WHERE id = %s",
        (context, version_id),
    )
    await connection.execute("DELETE FROM document_chunks WHERE version_id = %s", (version_id,))
    async with connection.cursor() as insert:
        await insert.executemany(
            "INSERT INTO document_chunks (tenant_id, version_id, ordinal, kind, text, "
            "heading_path, page_start, page_end, tokens, content_hash, simhash, search) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    tenant_id,
                    version_id,
                    c.ordinal,
                    c.kind,
                    c.text,
                    list(c.heading_path),
                    c.page_start,
                    c.page_end,
                    c.tokens,
                    content_hash(c.text),
                    simhash(c.text),
                    _terms(
                        context,
                        c.heading_path,
                        c.text,
                        [
                            identifier
                            for number in range(c.page_start, c.page_end + 1)
                            for identifier in extra.get(number, [])
                        ],
                    ),
                )
                for c in chunks
            ],
        )
        await insert.executemany(
            "INSERT INTO chunk_entities (tenant_id, version_id, ordinal, char_start, kind, value, "
            "written) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [
                (tenant_id, version_id, c.ordinal, e.start, e.kind, e.value[:200], e.text[:400])
                for c in chunks
                for e in extract(indexed_text(c))
            ],
        )
    return len(chunks)


type _Pending = tuple[int, bytes, str]  # ordinal, content hash, the text to embed


async def _chunks_to_embed(connection: AsyncConnection, version_id: UUID) -> list[_Pending]:
    cursor = await connection.execute(
        "SELECT c.ordinal, c.content_hash, coalesce(v.context, ''), c.heading_path, c.text "
        "FROM document_chunks c JOIN document_versions v ON v.id = c.version_id "
        "WHERE c.version_id = %s AND c.embedding IS NULL ORDER BY c.ordinal",
        (version_id,),
    )
    return [
        (ordinal, digest, contextual_text(context, headings, text))
        for ordinal, digest, context, headings, text in await cursor.fetchall()
    ]


async def _store_vectors(
    connection: AsyncConnection,
    version_id: UUID,
    batch: list[_Pending],
    vectors: list[list[float]],
) -> None:
    # The content hash guards against a chunk replaced since it was read; under the document's
    # lock that cannot happen, so this is a second line, not the first.
    async with connection.cursor() as cursor:
        await cursor.executemany(
            "UPDATE document_chunks SET embedding = %s::halfvec "
            "WHERE version_id = %s AND ordinal = %s AND content_hash = %s",
            [
                (_vector_literal(vector), version_id, ordinal, digest)
                for (ordinal, digest, _), vector in zip(batch, vectors, strict=True)
            ],
        )


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.6g}" for value in vector) + "]"


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
    # The blocks of the OCR text; None when the page keeps its text layer and its blocks.
    blocks: list[dict[str, Any]] | None


def page_update(page: Page, reading: PageReading) -> PageUpdate:
    text, from_ocr = better_text(page, reading.text)
    return PageUpdate(
        text=text,
        text_source="ocr" if from_ocr else "layer",
        ocr_engine=reading.engine,
        # The identifiers describe the OCR text; kept only when the page keeps that text.
        extra_identifiers=list(reading.extra_identifiers) if from_ocr else [],
        uncertain_identifiers=list(reading.uncertain_identifiers) if from_ocr else [],
        blocks=[b.to_json() for b in blocks_from_text(text, page.number)] if from_ocr else None,
    )


async def _store_reading(
    connection: AsyncConnection, version_id: UUID, page: Page, reading: PageReading
) -> None:
    update = page_update(page, reading)
    await connection.execute(
        "UPDATE document_pages SET text = %s, text_source = %s, ocr_engine = %s, "
        "extra_identifiers = %s, uncertain_identifiers = %s, blocks = COALESCE(%s, blocks) "
        "WHERE version_id = %s AND number = %s",
        (
            update.text,
            update.text_source,
            update.ocr_engine,
            update.extra_identifiers,
            update.uncertain_identifiers,
            None if update.blocks is None else Jsonb(update.blocks),
            version_id,
            page.number,
        ),
    )
