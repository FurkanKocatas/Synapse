"""The operations page's figures, read in one tenant transaction (ADR 0014).

Everything comes from the database the page's own request already uses, the blob volume the
API mounts, and the model servers' ``/health``: nothing needs an observability stack. The
consistency checks are those of ADR 0003, run live: each must be zero.
"""

import asyncio
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from psycopg import AsyncConnection

from synapse.knowledge.public import retryable
from synapse.operations.runs import LatestRuns, latest_runs

# The processes that connect with these names (worker_cli.py, scheduler_cli.py).
PROCESSES = {"worker": "synapse-worker", "scheduler": "synapse-scheduler"}

DOCUMENTS = """
    SELECT latest.status, count(*) FROM documents d
    JOIN LATERAL (
        SELECT v.status FROM document_versions v WHERE v.document_id = d.id
        ORDER BY v.version DESC LIMIT 1
    ) latest ON true
    WHERE d.deleted_at IS NULL GROUP BY latest.status
"""
# The pages of each live document's latest version: read by OCR, waiting for it, needing it
# but not read (the engines failed on them), with identifiers OCR was unsure of.
PAGES = """
    SELECT count(p.*),
           count(*) FILTER (WHERE p.text_source = 'ocr'),
           count(*) FILTER (WHERE p.needs_ocr AND p.text_source = 'layer'
                            AND latest.status IN ('queued', 'parsing', 'ocr')),
           count(*) FILTER (WHERE p.needs_ocr AND p.text_source = 'layer'
                            AND latest.status NOT IN ('queued', 'parsing', 'ocr')),
           count(*) FILTER (WHERE cardinality(p.uncertain_identifiers) > 0)
    FROM documents d
    JOIN LATERAL (
        SELECT v.id, v.status FROM document_versions v WHERE v.document_id = d.id
        ORDER BY v.version DESC LIMIT 1
    ) latest ON true
    JOIN document_pages p ON p.version_id = latest.id
    WHERE d.deleted_at IS NULL
"""
QUEUES = """
    SELECT queue_name, status, count(*) FROM procrastinate_jobs
    WHERE args->>'tenant_id' = %s AND status IN ('todo', 'doing', 'failed')
    GROUP BY queue_name, status
"""
PROBLEMS = {
    # A version marked ready has its chunks, each with its vector.
    "ready_without_chunks": """
        SELECT count(*) FROM document_versions v WHERE v.status = 'ready'
        AND NOT EXISTS (SELECT 1 FROM document_chunks c WHERE c.version_id = v.id)
    """,
    "ready_chunks_without_vectors": """
        SELECT count(*) FROM document_chunks c JOIN document_versions v ON v.id = c.version_id
        WHERE v.status = 'ready' AND c.embedding IS NULL
    """,
    # A deleted document is purged within minutes (knowledge/maintenance.py).
    "deleted_not_purged": """
        SELECT count(*) FROM documents WHERE deleted_at < now() - interval '1 day'
    """,
    # A purge removes the blob rows no version names.
    "files_no_version_names": """
        SELECT count(*) FROM blobs b
        WHERE NOT EXISTS (SELECT 1 FROM document_versions v WHERE v.blob_sha256 = b.sha256)
    """,
}


class Server(Protocol):
    service: str

    async def healthy(self) -> bool: ...


@dataclass(frozen=True)
class Service:
    name: str
    ok: bool
    # Connections of a process, where that is what tells it is running.
    connections: int | None = None


@dataclass(frozen=True)
class QueueState:
    queue: str
    waiting: int
    running: int
    failed: int


@dataclass(frozen=True)
class Pages:
    total: int
    read_by_ocr: int
    waiting_for_ocr: int
    not_read: int
    with_uncertain_identifiers: int


@dataclass(frozen=True)
class Storage:
    files_bytes: int
    database_bytes: int
    disk_free_bytes: int
    disk_total_bytes: int


@dataclass(frozen=True)
class Overview:
    services: list[Service]
    queues: list[QueueState]
    # Live documents by the status of their latest version.
    documents: dict[str, int]
    deleted_waiting: int
    # Documents whose processing stopped on an error that may not come again (retry_failed).
    retryable: int
    pages: Pages
    storage: Storage
    runs: LatestRuns
    # The consistency checks that are not zero.
    problems: dict[str, int]


async def overview(
    connection: AsyncConnection, tenant_id: UUID, blob_dir: Path, servers: Sequence[Server]
) -> Overview:
    health = asyncio.gather(*(server.healthy() for server in servers))
    processes = await _processes(connection)
    services = [
        Service("database", ok=True),
        *(
            Service(
                name,
                ok=processes.get(application, 0) > 0,
                connections=processes.get(application, 0),
            )
            for name, application in PROCESSES.items()
        ),
    ]
    services += [
        Service(server.service, ok=ok) for server, ok in zip(servers, await health, strict=True)
    ]
    return Overview(
        services=services,
        queues=await _queues(connection, tenant_id),
        documents=await _documents(connection),
        deleted_waiting=await _count(
            connection, "SELECT count(*) FROM documents WHERE deleted_at IS NOT NULL"
        ),
        retryable=len(await retryable(connection)),
        pages=await _pages(connection),
        storage=await _storage(connection, blob_dir),
        runs=await latest_runs(connection),
        problems={
            name: found
            for name, query in PROBLEMS.items()
            if (found := await _count(connection, query))
        },
    )


async def _processes(connection: AsyncConnection) -> dict[str, int]:
    # Other roles' sessions show their application name, though not their queries.
    cursor = await connection.execute(
        "SELECT application_name, count(*) FROM pg_stat_activity "
        "WHERE datname = current_database() AND application_name = ANY(%s) "
        "GROUP BY application_name",
        (list(PROCESSES.values()),),
    )
    return dict(await cursor.fetchall())


async def _queues(connection: AsyncConnection, tenant_id: UUID) -> list[QueueState]:
    cursor = await connection.execute(QUEUES, (str(tenant_id),))
    counts: dict[str, dict[str, int]] = {}
    for queue, status, count in await cursor.fetchall():
        counts.setdefault(queue, {})[status] = count
    return [
        QueueState(queue, found.get("todo", 0), found.get("doing", 0), found.get("failed", 0))
        for queue, found in sorted(counts.items())
    ]


async def _documents(connection: AsyncConnection) -> dict[str, int]:
    cursor = await connection.execute(DOCUMENTS)
    return dict(await cursor.fetchall())


async def _pages(connection: AsyncConnection) -> Pages:
    cursor = await connection.execute(PAGES)
    row = await cursor.fetchone()
    assert row is not None  # noqa: S101  (an aggregate always has a row)
    return Pages(*row)


async def _storage(connection: AsyncConnection, blob_dir: Path) -> Storage:
    files = await _count(connection, "SELECT coalesce(sum(size_bytes), 0) FROM blobs")
    database = await _count(connection, "SELECT pg_database_size(current_database())")
    disk = await asyncio.to_thread(shutil.disk_usage, blob_dir)
    return Storage(files, database, disk.free, disk.total)


async def _count(connection: AsyncConnection, query: str) -> int:
    cursor = await connection.execute(query)
    row = await cursor.fetchone()
    return int(row[0]) if row else 0
