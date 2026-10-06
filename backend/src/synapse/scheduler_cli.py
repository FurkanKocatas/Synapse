"""``synapse scheduler``: the maintenance process (ADR 0002).

It runs the maintenance queue: the purge each delete queues, and the jobs it defers itself on a
schedule (``knowledge.maintenance``, and the audit checkpoints and verification below). It
connects as its own database role, and it alone may remove uploaded files: the workers only
read them. The nightly file sweep and audit verification are recorded for the operations page.
"""

import asyncio
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID

import structlog
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from synapse.audit import public as audit
from synapse.jobs.queue import Queue
from synapse.jobs.worker import Args, Task, build_app, register
from synapse.kernel.config import Settings
from synapse.kernel.database import Database
from synapse.kernel.secrets import SecretError
from synapse.knowledge.public import LocalBlobStore, Maintenance
from synapse.operations.public import RUN_KINDS, Operations, Run

log = structlog.get_logger(__name__)

CHECKPOINT_TASK = "audit.checkpoint"
# Every hour (UTC) the chain's head has moved: a backup, whenever it runs, carries a checkpoint
# at most an hour old (ADR 0008 asks for one a night).
CHECKPOINT_CRON = "5 * * * *"
AUDIT_VERIFY_TASK = "audit.verify"
# Every night (UTC): the whole chain recomputed and every checkpoint compared with it.
AUDIT_VERIFY_CRON = "20 1 * * *"

type Clock = Callable[[], datetime]


class SchedulerError(RuntimeError):
    pass


def tasks(
    database: Database,
    settings: Settings,
    key: Ed25519PrivateKey,
    now: Clock = lambda: datetime.now(UTC),
) -> list[Task]:
    """Every job the scheduler runs, the scheduled ones with their cron."""
    assert settings.tenant_id is not None  # noqa: S101  (checked by run)
    operations = Operations(
        database, tenant_id=settings.tenant_id, blob_dir=settings.blob_dir, servers=[]
    )

    async def record(
        _tenant_id: UUID,
        kind: str,
        *,
        ok: bool,
        started: datetime,
        details: Mapping[str, int | str],
    ) -> None:
        if kind not in RUN_KINDS:  # pragma: no cover  (the kinds are this module's own)
            raise ValueError(kind)
        await operations.record(Run(kind, ok, started, now(), details))

    maintenance = Maintenance(database, LocalBlobStore(settings.blob_dir), now, recorder=record)
    return [
        *maintenance.tasks(),
        checkpoint_task(database, key, now),
        audit_verify_task(database, key, operations, now),
    ]


def checkpoint_task(database: Database, key: Ed25519PrivateKey, now: Clock) -> Task:
    """Sign the audit chain's head and keep the checkpoint, unless the head has one already."""

    async def run(tenant_id: UUID, _args: Args) -> None:
        async with database.tenant_transaction(tenant_id) as connection:
            stored = await audit.store_checkpoint(connection, tenant_id, key, now())
        if stored is not None:
            log.info("audit.checkpointed", seq=json.loads(stored.payload)["seq"])

    return Task(CHECKPOINT_TASK, Queue.MAINTENANCE, run, cron=CHECKPOINT_CRON)


def audit_verify_task(
    database: Database, key: Ed25519PrivateKey, operations: Operations, now: Clock
) -> Task:
    """Recompute the chain and compare the checkpoints with it, as ``synapse audit verify``."""

    async def run(tenant_id: UUID, _args: Args) -> None:
        started = now()
        async with database.tenant_transaction(tenant_id) as connection:
            chain = await audit.verify(connection, tenant_id)
            kept = (
                await audit.verify_checkpoints(connection, tenant_id, key.public_key())
                if chain.ok
                else audit.CheckpointsChecked(0)
            )
        problem = chain.problem or kept.problem
        details: dict[str, int | str] = {
            "events_checked": chain.events_checked,
            "checkpoints_checked": kept.checked,
        }
        if problem:
            details["problem"] = problem
            log.error("audit.broken", problem=problem)
        await operations.record(Run("audit_verify", problem is None, started, now(), details))

    return Task(AUDIT_VERIFY_TASK, Queue.MAINTENANCE, run, cron=AUDIT_VERIFY_CRON)


async def run(settings: Settings, *, once: bool = False) -> None:
    """Run maintenance jobs until stopped. With ``once``, until the queue is empty, and nothing
    is deferred on a schedule (tests run the scheduled jobs themselves)."""
    tenant_id = settings.tenant_id
    if tenant_id is None:
        raise SchedulerError("SYNAPSE_TENANT_ID is not set")
    try:
        key = audit.load_signing_key(settings.audit_signing_key_file)
    except (SecretError, OSError) as error:
        raise SchedulerError(f"cannot read the audit signing key: {error}") from error
    connection = settings.database(application_name="synapse-scheduler")
    database = Database(connection, max_size=2)
    await database.open()
    app = build_app(connection.conninfo())
    jobs = tasks(database, settings, key)
    for task in jobs:
        register(app, task, scheduled_for=None if once else tenant_id)
    try:
        async with app.open_async():
            log.info(
                "scheduler.started",
                schedules={task.name: task.cron for task in jobs if task.cron and not once},
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
