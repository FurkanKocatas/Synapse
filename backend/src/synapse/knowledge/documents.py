"""Documents and their versions: upload, list, read, delete (ADR 0003, ADR 0007).

Rules:

- Uploading needs ``write`` on the collection; a new version needs ``write`` on the document;
  reading needs ``read``. Access is decided only by ``accessible_collections`` and
  ``accessible_documents`` in the database.
- The bytes are stored once per tenant. Uploading a file whose content is already the current
  version of a live document in the same collection is refused as a duplicate.
- A document or version the user may not read answers "not found", the same as a missing one,
  so identifiers cannot be probed.
- Deleting marks the document; it leaves search at once. The delete queues the purge of its
  content, which the scheduler runs (``maintenance.py``).
- Reading a page in the viewer is audited (``kb.document.view``), as ADR 0008 asks of every
  document view.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import PurePath
from typing import Literal
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import class_row

from synapse.audit import public as audit
from synapse.audit.public import AuditEvent
from synapse.jobs.queue import enqueue
from synapse.kernel.database import Database
from synapse.knowledge.blobs import BlobStore, Incoming
from synapse.knowledge.filetypes import MediaType, detect
from synapse.knowledge.maintenance import lock_blob
from synapse.knowledge.metadata import SUGGESTED, checked
from synapse.knowledge.pipeline import parse_job, purge_job

VersionStatus = Literal["queued", "parsing", "ocr", "embedding", "ready", "failed"]

MAX_TITLE = 500
MAX_FILENAME = 255


class NotFoundError(LookupError):
    """Missing, deleted, or not visible to this user."""


class DuplicateError(ValueError):
    def __init__(self, document_id: UUID) -> None:
        super().__init__("identical file already in this collection")
        self.document_id = document_id


@dataclass(frozen=True)
class Uploader:
    user_id: UUID
    ip: str | None


@dataclass(frozen=True)
class Uploaded:
    document_id: UUID
    version_id: UUID
    version: int
    media_type: MediaType


@dataclass(frozen=True)
class DocumentSummary:
    id: UUID
    collection_id: UUID
    title: str
    latest_version: int
    status: VersionStatus
    failure: str | None
    media_type: str
    size_bytes: int
    updated_at: datetime
    # Suggested from the document when it is read, or set by a person (metadata.py).
    kind: str | None = None
    document_date: date | None = None
    reference: str | None = None
    tags: list[str] = field(default_factory=list)
    # Which of kind, document_date and reference a person set; the others were suggested.
    set_by_hand: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VersionInfo:
    id: UUID
    version: int
    filename: str
    media_type: str
    size_bytes: int
    status: VersionStatus
    failure: str | None
    created_at: datetime


@dataclass(frozen=True)
class CollectionAccess:
    id: UUID
    # None at the top level, and also when the parent is not visible to this user, so a
    # collection granted on its own still has a place in the tree.
    parent_id: UUID | None
    name: str
    can_write: bool
    # The documents directly in it that this user may read (not those of folders inside it).
    document_count: int = 0


@dataclass(frozen=True)
class PageChunk:
    ordinal: int
    text: str
    page_start: int
    page_end: int


@dataclass(frozen=True)
class PageView:
    """One page of a version as the viewer shows it: its text and the chunks on it."""

    document_id: UUID
    title: str
    version: int
    number: int
    # How many pages the version has.
    pages: int
    kind: str
    label: str | None
    text: str
    # ``layer`` (the file's own text) or ``ocr``.
    text_source: str
    media_type: str
    chunks: list[PageChunk]


@dataclass(frozen=True)
class StoredFile:
    sha256: bytes
    filename: str
    media_type: str
    size_bytes: int


def clean_filename(name: str) -> str:
    """The last path component, without control characters, at most 255 characters."""
    base = PurePath(name.replace("\\", "/")).name
    cleaned = "".join(ch for ch in base if ch.isprintable()).strip()
    return cleaned[:MAX_FILENAME] or "file"


def default_title(filename: str) -> str:
    stem = PurePath(filename).stem.strip()
    return (stem or filename)[:MAX_TITLE]


@dataclass(frozen=True)
class _NewVersion:
    document_id: UUID
    version: int
    sha256: bytes
    filename: str
    user_id: UUID


def _utc_now() -> datetime:
    return datetime.now(UTC)


_PAGE = (
    "SELECT v.id, d.title, b.media_type, "
    "(SELECT count(*) FROM document_pages c WHERE c.version_id = v.id), "
    "p.kind, p.label, p.text, p.text_source "
    "FROM document_versions v JOIN documents d ON d.id = v.document_id "
    "JOIN blobs b ON b.sha256 = v.blob_sha256 "
    "JOIN document_pages p ON p.version_id = v.id "
    "WHERE v.document_id = %s AND v.version = %s AND p.number = %s"
)


_READABLE_COLLECTIONS = (
    "WITH readable AS (SELECT collection_id FROM accessible_collections(%(user)s, 'read')), "
    "writable AS (SELECT collection_id FROM accessible_collections(%(user)s, 'write')), "
    "counted AS (SELECT d.collection_id, count(*) AS n "
    "  FROM accessible_documents(%(user)s, 'read') a JOIN documents d ON d.id = a.document_id "
    "  WHERE d.deleted_at IS NULL GROUP BY d.collection_id) "
    "SELECT c.id, CASE WHEN c.parent_id IN (SELECT collection_id FROM readable) "
    "THEN c.parent_id END AS parent_id, c.name, "
    "c.id IN (SELECT collection_id FROM writable) AS can_write, "
    "coalesce(counted.n, 0)::int AS document_count "
    "FROM collections c LEFT JOIN counted ON counted.collection_id = c.id "
    "WHERE c.id IN (SELECT collection_id FROM readable) "
    "ORDER BY lower(c.name), c.id"
)

_LIST_DOCUMENTS = (
    "SELECT d.id, d.collection_id, d.title, v.version AS latest_version, v.status, "
    "v.failure, b.media_type, b.size_bytes, v.created_at AS updated_at, d.kind, "
    "d.document_date, d.reference, d.tags, d.metadata_set_by_hand AS set_by_hand "
    "FROM documents d "
    "JOIN LATERAL (SELECT * FROM document_versions dv WHERE dv.document_id = d.id "
    "              ORDER BY dv.version DESC LIMIT 1) v ON true "
    "JOIN blobs b ON b.sha256 = v.blob_sha256 "
    "WHERE d.collection_id = %s AND d.deleted_at IS NULL "
    "AND d.id IN (SELECT document_id FROM accessible_documents(%s, 'read')) "
    "ORDER BY lower(d.title), d.id"
)


class DocumentService:
    def __init__(
        self,
        database: Database,
        blobs: BlobStore,
        *,
        tenant_id: UUID,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._db = database
        self._blobs = blobs
        self._tenant_id = tenant_id
        self._now = clock

    async def may_upload(self, user_id: UUID, collection_id: UUID) -> bool:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            return await _has_collection(connection, user_id, collection_id, "write")

    async def may_add_version(self, user_id: UUID, document_id: UUID) -> bool:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            return await _has_document(connection, user_id, document_id, "write")

    async def upload(
        self,
        uploader: Uploader,
        collection_id: UUID,
        incoming: Incoming,
        filename: str,
        title: str | None = None,
    ) -> Uploaded:
        """Store a new document. The caller checked ``may_upload`` before receiving the bytes;
        it is checked again here, in the transaction that writes."""
        media_type = detect(incoming.path)
        name = clean_filename(filename)
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            if not await _has_collection(connection, uploader.user_id, collection_id, "write"):
                raise NotFoundError
            duplicate = await _live_duplicate(connection, collection_id, incoming.sha256)
            if duplicate is not None:
                raise DuplicateError(duplicate)
            await self._store_blob(connection, incoming, media_type, now)
            cursor = await connection.execute(
                "INSERT INTO documents (tenant_id, collection_id, title, created_by, created_at) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (
                    self._tenant_id,
                    collection_id,
                    (title or "").strip()[:MAX_TITLE] or default_title(name),
                    uploader.user_id,
                    now,
                ),
            )
            document_id = _first(await cursor.fetchone())
            version_id = await self._insert_version(
                connection,
                _NewVersion(document_id, 1, incoming.sha256, name, uploader.user_id),
                now,
            )
            # In the same transaction: no document without its job, no job without its document.
            await enqueue(connection, self._tenant_id, parse_job(document_id, version_id))
            await self._audit(
                connection,
                "kb.document.create",
                uploader,
                document_id,
                now,
                {
                    "collection_id": str(collection_id),
                    "media_type": media_type.value,
                    "size_bytes": incoming.size_bytes,
                },
            )
        return Uploaded(document_id, version_id, 1, media_type)

    async def add_version(
        self, uploader: Uploader, document_id: UUID, incoming: Incoming, filename: str
    ) -> Uploaded:
        media_type = detect(incoming.path)
        name = clean_filename(filename)
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            if not await _has_document(connection, uploader.user_id, document_id, "write"):
                raise NotFoundError
            # The documents row is locked first, so two uploads cannot take the same number.
            await connection.execute(
                "SELECT 1 FROM documents WHERE id = %s FOR UPDATE", (document_id,)
            )
            cursor = await connection.execute(
                "SELECT coalesce(max(version), 0) + 1 FROM document_versions "
                "WHERE document_id = %s",
                (document_id,),
            )
            version = int(_first(await cursor.fetchone()))
            await self._store_blob(connection, incoming, media_type, now)
            version_id = await self._insert_version(
                connection,
                _NewVersion(document_id, version, incoming.sha256, name, uploader.user_id),
                now,
            )
            await enqueue(connection, self._tenant_id, parse_job(document_id, version_id))
            await self._audit(
                connection,
                "kb.document.version",
                uploader,
                document_id,
                now,
                {"version": version, "size_bytes": incoming.size_bytes},
            )
        return Uploaded(document_id, version_id, version, media_type)

    async def collections(self, user_id: UUID) -> list[CollectionAccess]:
        """The collections this user may read, and whether they may add to each."""
        async with (
            self._db.tenant_transaction(self._tenant_id) as connection,
            connection.cursor(row_factory=class_row(CollectionAccess)) as cursor,
        ):
            await cursor.execute(_READABLE_COLLECTIONS, {"user": user_id})
            return await cursor.fetchall()

    async def list_documents(self, user_id: UUID, collection_id: UUID) -> list[DocumentSummary]:
        async with (
            self._db.tenant_transaction(self._tenant_id) as connection,
            connection.cursor(row_factory=class_row(DocumentSummary)) as cursor,
        ):
            await cursor.execute(_LIST_DOCUMENTS, (collection_id, user_id))
            return await cursor.fetchall()

    async def versions(self, user_id: UUID, document_id: UUID) -> list[VersionInfo]:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            if not await _has_document(connection, user_id, document_id, "read"):
                raise NotFoundError
            async with connection.cursor(row_factory=class_row(VersionInfo)) as cursor:
                await cursor.execute(
                    "SELECT v.id, v.version, v.filename, b.media_type, b.size_bytes, v.status, "
                    "v.failure, v.created_at FROM document_versions v "
                    "JOIN blobs b ON b.sha256 = v.blob_sha256 "
                    "WHERE v.document_id = %s ORDER BY v.version DESC",
                    (document_id,),
                )
                return await cursor.fetchall()

    async def stored_file(self, user_id: UUID, document_id: UUID, version: int) -> StoredFile:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            if not await _has_document(connection, user_id, document_id, "read"):
                raise NotFoundError
            async with connection.cursor(row_factory=class_row(StoredFile)) as cursor:
                await cursor.execute(
                    "SELECT v.blob_sha256 AS sha256, v.filename, b.media_type, b.size_bytes "
                    "FROM document_versions v JOIN blobs b ON b.sha256 = v.blob_sha256 "
                    "WHERE v.document_id = %s AND v.version = %s",
                    (document_id, version),
                )
                found = await cursor.fetchone()
        if found is None:
            raise NotFoundError
        return found

    async def page(
        self, viewer: Uploader, document_id: UUID, version: int, number: int
    ) -> PageView:
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            if not await _has_document(connection, viewer.user_id, document_id, "read"):
                raise NotFoundError
            cursor = await connection.execute(_PAGE, (document_id, version, number))
            row = await cursor.fetchone()
            if row is None:
                raise NotFoundError
            version_id, title, media_type, pages, kind, label, text, text_source = row
            cursor = await connection.execute(
                "SELECT ordinal, text, page_start, page_end FROM document_chunks "
                "WHERE version_id = %s AND page_start <= %s AND page_end >= %s ORDER BY ordinal",
                (version_id, number, number),
            )
            chunks = [PageChunk(*chunk) for chunk in await cursor.fetchall()]
            await self._audit(
                connection,
                "kb.document.view",
                viewer,
                document_id,
                now,
                {"version": version, "page": number},
            )
        return PageView(
            document_id,
            title,
            version,
            number,
            pages,
            kind,
            label,
            text,
            text_source,
            media_type,
            chunks,
        )

    async def update_metadata(
        self, uploader: Uploader, document_id: UUID, changes: Mapping[str, object]
    ) -> None:
        """Set the given fields (``metadata.FIELDS``); ``None`` clears a kind, date or number.
        One set here is never replaced by a suggestion afterwards. Needs ``write``; a wrong
        field or value raises ``InvalidMetadataError`` (a ``ValueError``)."""
        values = checked(changes)
        now = self._now()
        names = list(values)
        assignments = ", ".join(f"{name} = %s" for name in names)
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            if not await _has_document(connection, uploader.user_id, document_id, "write"):
                raise NotFoundError
            await connection.execute(
                "UPDATE documents SET "  # noqa: S608  (names from metadata.FIELDS)
                + assignments
                + ", metadata_set_by_hand = ARRAY(SELECT DISTINCT unnest("
                "metadata_set_by_hand || %s::text[]) ORDER BY 1) WHERE id = %s",
                (
                    *values.values(),
                    [name for name in names if name in SUGGESTED],
                    document_id,
                ),
            )
            await self._audit(
                connection,
                "kb.document.metadata",
                uploader,
                document_id,
                now,
                {"fields": ",".join(names)},
            )

    async def delete(self, uploader: Uploader, document_id: UUID) -> None:
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            if not await _has_document(connection, uploader.user_id, document_id, "write"):
                raise NotFoundError
            cursor = await connection.execute(
                "UPDATE documents SET deleted_at = %s WHERE id = %s AND deleted_at IS NULL",
                (now, document_id),
            )
            if cursor.rowcount:
                await enqueue(connection, self._tenant_id, purge_job(document_id))
            await self._audit(connection, "kb.document.delete", uploader, document_id, now, {})

    async def _store_blob(
        self, connection: AsyncConnection, incoming: Incoming, media_type: MediaType, now: datetime
    ) -> None:
        # The row is written before the file is moved into place: if the move fails, the
        # transaction fails with it; a file without a row is swept by maintenance later. The
        # blob's lock keeps that sweep away until this transaction ends.
        await lock_blob(connection, incoming.sha256)
        await connection.execute(
            "INSERT INTO blobs (tenant_id, sha256, size_bytes, media_type, created_at) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (self._tenant_id, incoming.sha256, incoming.size_bytes, media_type.value, now),
        )
        self._blobs.put(self._tenant_id, incoming)

    async def _insert_version(
        self, connection: AsyncConnection, new: _NewVersion, now: datetime
    ) -> UUID:
        cursor = await connection.execute(
            "INSERT INTO document_versions (tenant_id, document_id, version, blob_sha256, "
            "filename, created_by, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                self._tenant_id,
                new.document_id,
                new.version,
                new.sha256,
                new.filename,
                new.user_id,
                now,
            ),
        )
        version_id: UUID = _first(await cursor.fetchone())
        return version_id

    async def _audit(
        self,
        connection: AsyncConnection,
        action: str,
        uploader: Uploader,
        document_id: UUID,
        now: datetime,
        details: dict[str, str | int],
    ) -> None:
        await audit.record(
            connection,
            self._tenant_id,
            AuditEvent(
                action,
                "success",
                actor_user_id=uploader.user_id,
                actor_ip=uploader.ip,
                target_type="document",
                target_id=str(document_id),
                details=details,
            ),
            now,
        )


def _first(row: tuple[object, ...] | None) -> UUID:
    if row is None:  # pragma: no cover  (INSERT ... RETURNING and aggregates always return)
        raise RuntimeError("expected a row")
    return row[0]  # type: ignore[return-value]


async def _has_collection(
    connection: AsyncConnection, user_id: UUID, collection_id: UUID, permission: str
) -> bool:
    cursor = await connection.execute(
        "SELECT EXISTS (SELECT 1 FROM accessible_collections(%s, %s) WHERE collection_id = %s)",
        (user_id, permission, collection_id),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


async def _has_document(
    connection: AsyncConnection, user_id: UUID, document_id: UUID, permission: str
) -> bool:
    cursor = await connection.execute(
        "SELECT EXISTS (SELECT 1 FROM accessible_documents(%s, %s) WHERE document_id = %s)",
        (user_id, permission, document_id),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


async def _live_duplicate(
    connection: AsyncConnection, collection_id: UUID, sha256: bytes
) -> UUID | None:
    cursor = await connection.execute(
        "SELECT d.id FROM documents d JOIN LATERAL ("
        "  SELECT blob_sha256 FROM document_versions dv WHERE dv.document_id = d.id "
        "  ORDER BY dv.version DESC LIMIT 1) v ON true "
        "WHERE d.collection_id = %s AND d.deleted_at IS NULL AND v.blob_sha256 = %s LIMIT 1",
        (collection_id, sha256),
    )
    row = await cursor.fetchone()
    return row[0] if row else None
