"""``synapse scheduler``: the maintenance process (ADR 0002).

It runs the maintenance queue: the purge each delete queues, and the jobs it defers itself on a
schedule (``knowledge.maintenance``). It connects as its own database role, and it alone may
remove uploaded files: the workers only read them.
"""

import asyncio

import structlog

from synapse.jobs.queue import Queue
from synapse.jobs.worker import build_app, register
from synapse.kernel.config import Settings
from synapse.kernel.database import Database
from synapse.knowledge.public import LocalBlobStore, Maintenance

log = structlog.get_logger(__name__)


class SchedulerError(RuntimeError):
    pass


async def run(settings: Settings, *, once: bool = False) -> None:
    """Run maintenance jobs until stopped. With ``once``, until the queue is empty, and nothing
    is deferred on a schedule (tests run the scheduled jobs themselves)."""
    tenant_id = settings.tenant_id
    if tenant_id is None:
        raise SchedulerError("SYNAPSE_TENANT_ID is not set")
    connection = settings.database(application_name="synapse-scheduler")
    database = Database(connection, max_size=2)
    await database.open()
    app = build_app(connection.conninfo())
    tasks = Maintenance(database, LocalBlobStore(settings.blob_dir)).tasks()
    for task in tasks:
        register(app, task, scheduled_for=None if once else tenant_id)
    try:
        async with app.open_async():
            log.info(
                "scheduler.started",
                schedules={task.name: task.cron for task in tasks if task.cron and not once},
            )
            await app.run_worker_async(
                queues=[Queue.MAINTENANCE.value],
                concurrency=1,
                wait=not once,
                install_signal_handlers=not once,
            )
    finally:
        await database.close()


def main(settings: Settings) -> int:
    asyncio.run(run(settings))
    return 0
