"""What the user's documents are, for the chat to answer questions about the collection itself
("what is in the documents", "how many are there", "what was added last"; docs/design/answers.md):
the folders the user may read with how many documents each holds, how many are ready, and the
newest documents with their first words. Access is decided by ``accessible_collections`` and
``accessible_documents``, as everywhere else.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from psycopg import AsyncConnection

# The newest documents listed for the model: enough to name what the collection is about,
# few enough to keep the prompt short on a CPU (about 25 tokens each).
LISTED = 60
# The first words of a document (its context, after the file name), as the model sees it.
OPENING_CHARS = 140
_READY = ("parsed", "embedding", "ready")

# The statements are built from constant fragments; every value is a parameter.
_LATEST = (
    "JOIN LATERAL (SELECT * FROM document_versions dv WHERE dv.document_id = d.id "
    "ORDER BY dv.version DESC LIMIT 1) v ON true "
)
_VISIBLE = (
    "WHERE d.deleted_at IS NULL "
    "AND d.id IN (SELECT document_id FROM accessible_documents(%(user)s, 'read')) "
)
_READABLE = "WITH readable AS (SELECT collection_id FROM accessible_collections(%(user)s, 'read')) "
_FOLDERS = (
    _READABLE + "SELECT c.id, c.parent_id, c.name, "  # noqa: S608
    "(SELECT count(*) FROM documents d " + _VISIBLE + "AND d.collection_id = c.id) "
    "FROM collections c WHERE c.id IN (SELECT collection_id FROM readable) "
    "ORDER BY lower(c.name), c.id"
)
_STATUSES = (
    "SELECT v.status, count(*) FROM documents d "  # noqa: S608
    + _LATEST
    + _VISIBLE
    + "GROUP BY v.status"
)
_NEWEST = (
    "SELECT d.title, d.collection_id, b.media_type, v.status, v.created_at, "  # noqa: S608
    "coalesce(v.context, ''), (SELECT count(*) FROM document_pages p WHERE p.version_id = v.id) "
    "FROM documents d "
    + _LATEST
    + "JOIN blobs b ON b.sha256 = v.blob_sha256 "
    + _VISIBLE
    + "ORDER BY v.created_at DESC, d.id LIMIT %(limit)s"
)


@dataclass(frozen=True)
class Folder:
    # With the folders above it the user may read: "Mali İşler / Bütçe 2026".
    path: str
    documents: int


@dataclass(frozen=True)
class Listed:
    title: str
    folder: str
    media_type: str
    status: str
    added: datetime
    pages: int
    opening: str


@dataclass(frozen=True)
class Overview:
    folders: list[Folder]
    # The newest first, at most LISTED.
    newest: list[Listed]
    total: int
    ready: int
    failed: int

    @property
    def working(self) -> int:
        return self.total - self.ready - self.failed


async def overview(connection: AsyncConnection, user_id: UUID, *, listed: int = LISTED) -> Overview:
    """The collection as ``user_id`` may see it."""
    parameters = {"user": user_id, "limit": listed}
    rows = await (await connection.execute(_FOLDERS, parameters)).fetchall()
    names = {row[0]: (row[1], row[2]) for row in rows}

    def path(collection_id: UUID) -> str:
        parts: list[str] = []
        current: UUID | None = collection_id
        while current in names:
            parent, name = names[current]
            parts.append(name)
            current = parent
        return " / ".join(reversed(parts))

    folders = [Folder(path(row[0]), row[3]) for row in rows]
    folders.sort(key=lambda folder: folder.path.lower())
    counts: dict[str, int] = dict(
        await (await connection.execute(_STATUSES, parameters)).fetchall()
    )
    newest = [
        Listed(title, path(folder), media, status, added, pages, _opening(context))
        for title, folder, media, status, added, context, pages in await (
            await connection.execute(_NEWEST, parameters)
        ).fetchall()
    ]
    return Overview(
        folders,
        newest,
        total=sum(counts.values()),
        ready=sum(counts.get(status, 0) for status in _READY),
        failed=counts.get("failed", 0),
    )


def _opening(context: str) -> str:
    """The document's first words: its context (chunking.document_context) without the file
    name on its first line."""
    _, _, words = context.partition(chr(10))
    text = " ".join((words or context).split())
    return text if len(text) <= OPENING_CHARS else text[:OPENING_CHARS].rsplit(" ", 1)[0]
