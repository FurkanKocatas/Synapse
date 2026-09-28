"""``synapse worker``: the background job process (ADR 0002, ADR 0004).

The worker connects as its own database role and runs only the queues it is given, so OCR and
embedding can get processes of their own on bigger machines while a small box runs one worker
for everything.
"""

import asyncio
from collections.abc import Sequence

import structlog

from synapse.jobs.queue import Queue
from synapse.jobs.worker import build_app, register
from synapse.kernel.config import Settings
from synapse.kernel.database import Database
from synapse.knowledge.public import LightParser, LocalBlobStore, Processor

log = structlog.get_logger(__name__)


async def run(settings: Settings, queues: Sequence[Queue], *, concurrency: int, once: bool) -> None:
    """Process jobs until stopped; with ``once``, until the queues are empty."""
    connection = settings.database(application_name="synapse-worker")
    database = Database(connection, max_size=concurrency + 1)
    await database.open()
    app = build_app(connection.conninfo())
    processor = Processor(database, LocalBlobStore(settings.blob_dir), LightParser())
    for task in processor.tasks():
        register(app, task)
    try:
        async with app.open_async():
            log.info("worker.started", queues=[q.value for q in queues], concurrency=concurrency)
            await app.run_worker_async(
                queues=[q.value for q in queues],
                concurrency=concurrency,
                wait=not once,
                install_signal_handlers=not once,
            )
    finally:
        await database.close()


def main(settings: Settings, queues: Sequence[Queue], *, concurrency: int, once: bool) -> int:
    asyncio.run(run(settings, queues, concurrency=concurrency, once=once))
    return 0
