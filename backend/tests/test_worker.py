"""The task wrapper: tenancy from the job, no retries for bad jobs, a hook after the last try."""

import uuid

from procrastinate import App, RetryStrategy
from procrastinate.testing import InMemoryConnector

from synapse.jobs import worker
from synapse.jobs.queue import Queue
from synapse.jobs.worker import Args, BadJobError, Task, register


def in_memory_app() -> tuple[App, InMemoryConnector]:
    connector = InMemoryConnector()
    return App(connector=connector), connector


async def drain(app: App) -> None:
    async with app.open_async():
        await app.run_worker_async(queues=["ingest"], wait=False, install_signal_handlers=False)


def statuses(connector: InMemoryConnector) -> list[str]:
    return [job["status"] for job in connector.jobs.values()]


async def test_the_task_gets_the_tenant_and_its_own_arguments() -> None:
    app, _ = in_memory_app()
    seen: list[tuple[uuid.UUID, Args]] = []

    async def run(tenant_id: uuid.UUID, args: Args) -> None:
        seen.append((tenant_id, args))

    register(app, Task("t.ok", Queue.INGEST, run))
    tenant = uuid.uuid4()
    await app.configure_task("t.ok").defer_async(tenant_id=str(tenant), version_id="v1")
    await drain(app)
    assert seen == [(tenant, {"version_id": "v1"})]


async def test_a_job_without_a_tenant_is_dropped_not_retried() -> None:
    app, connector = in_memory_app()
    calls: list[Args] = []

    async def run(tenant_id: uuid.UUID, args: Args) -> None:
        calls.append(args)

    register(app, Task("t.no_tenant", Queue.INGEST, run))
    await app.configure_task("t.no_tenant").defer_async(version_id="v1")
    await app.configure_task("t.no_tenant").defer_async(tenant_id="not-a-uuid")
    await drain(app)
    assert calls == []
    assert statuses(connector) == ["succeeded", "succeeded"]  # finished, nothing to retry


async def test_bad_arguments_found_by_the_task_are_not_retried() -> None:
    app, connector = in_memory_app()

    async def run(tenant_id: uuid.UUID, args: Args) -> None:
        raise BadJobError("no version")

    register(app, Task("t.bad", Queue.INGEST, run))
    await app.configure_task("t.bad").defer_async(tenant_id=str(uuid.uuid4()))
    await drain(app)
    assert statuses(connector) == ["succeeded"]


async def test_the_last_failed_attempt_calls_the_give_up_hook(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # No waiting between attempts, so the test runs every retry at once.
    monkeypatch.setattr(worker, "RetryStrategy", _no_wait_retry)
    app, connector = in_memory_app()
    attempts: list[int] = []
    gave_up: list[tuple[uuid.UUID, Args, str]] = []

    async def run(tenant_id: uuid.UUID, args: Args) -> None:
        attempts.append(1)
        raise OSError("disk trouble")

    async def give_up(tenant_id: uuid.UUID, args: Args, error: str) -> None:
        gave_up.append((tenant_id, args, error))

    register(app, Task("t.flaky", Queue.INGEST, run, on_final_failure=give_up))
    tenant = uuid.uuid4()
    await app.configure_task("t.flaky").defer_async(tenant_id=str(tenant), version_id="v9")
    # Drain more often than needed, so an extra attempt would show.
    for _ in range(worker.MAX_ATTEMPTS + 3):
        await drain(app)
    assert len(attempts) == worker.MAX_ATTEMPTS
    assert gave_up == [(tenant, {"version_id": "v9"}, "OSError")]
    assert statuses(connector) == ["failed"]


def _no_wait_retry(**kwargs: object) -> RetryStrategy:
    kwargs["exponential_wait"] = 0
    return RetryStrategy(**kwargs)  # type: ignore[arg-type]


async def test_a_task_with_a_schedule_is_deferred_for_the_tenant_it_runs_for() -> None:
    app, _ = in_memory_app()
    tenant = uuid.uuid4()
    seen: list[tuple[uuid.UUID, Args]] = []

    async def run(tenant_id: uuid.UUID, args: Args) -> None:
        seen.append((tenant_id, args))

    register(app, Task("t.nightly", Queue.INGEST, run, cron="40 0 * * *"), scheduled_for=tenant)
    # without a tenant to run for, a scheduled task is only a task
    register(app, Task("t.unscheduled", Queue.INGEST, run, cron="40 0 * * *"))
    periodic = app.periodic_registry.periodic_tasks
    assert list(periodic) == [("t.nightly", str(tenant))]
    nightly = periodic[("t.nightly", str(tenant))]
    assert nightly.cron == "40 0 * * *"
    assert nightly.configure_kwargs["task_kwargs"] == {"tenant_id": str(tenant)}
    # deferred on schedule, it gets the tenant and the time it was due
    await app.configure_task("t.nightly").defer_async(tenant_id=str(tenant), timestamp=1791270000)
    await drain(app)
    assert seen == [(tenant, {"timestamp": 1791270000})]
