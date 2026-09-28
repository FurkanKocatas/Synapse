"""Enqueueing jobs inside the caller's transaction (ADR 0004).

A job is inserted with Procrastinate's own SQL function on the connection the caller is already
using, so the job exists exactly when the rows it is about exist: a rolled-back upload leaves no
job, and a committed one always has its job.

Every job carries the tenant in its arguments. The worker sets the tenant from there before it
touches any data (see ``worker.py``).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

type JsonValue = str | int | float | bool | None


class Queue(StrEnum):
    INGEST = "ingest"
    OCR = "ocr"
    EMBED = "embed"
    MAINTENANCE = "maintenance"


@dataclass(frozen=True)
class Job:
    task: str
    queue: Queue
    args: Mapping[str, JsonValue] = field(default_factory=dict)
    # Jobs with the same lock never run at the same time, such as all jobs for one document.
    lock: str | None = None


async def enqueue(connection: AsyncConnection, tenant_id: UUID, job: Job) -> int:
    if "tenant_id" in job.args:
        raise ValueError("tenant_id is set by enqueue, not by the caller")
    cursor = await connection.execute(
        "SELECT unnest(procrastinate_defer_jobs_v1(ARRAY["
        "ROW(%s, %s, 0, %s, NULL, %s, NULL)::procrastinate_job_to_defer_v1]))",
        (job.queue.value, job.task, job.lock, Jsonb({"tenant_id": str(tenant_id), **job.args})),
    )
    row = await cursor.fetchone()
    if row is None:  # pragma: no cover  (the function returns one id per job)
        raise RuntimeError("no job id returned")
    job_id: int = row[0]
    return job_id
