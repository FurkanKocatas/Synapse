"""The worker process: Procrastinate tasks wrapped with the tenancy rules (ADR 0002, 0004).

Each task is registered through ``register``, which:

- takes the tenant from the job's arguments, refusing a job without one;
- retries with exponential backoff, and calls the task's ``on_final_failure`` when the last
  attempt fails, so the thing the job was about (a document version) never stays "in progress";
- never accepts a user identity from anywhere but the job row (ADR 0002, rule 1).
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from procrastinate import App, JobContext, PsycopgConnector, RetryStrategy

from synapse.jobs.queue import JsonValue, Queue

log = structlog.get_logger(__name__)

# Runs in total, the first one included.
MAX_ATTEMPTS = 5

type Args = Mapping[str, JsonValue]
type Handler = Callable[[UUID, Args], Awaitable[None]]


@dataclass(frozen=True)
class Task:
    name: str
    queue: Queue
    run: Handler
    # Called once when the last attempt has failed, with the error's type name.
    on_final_failure: Callable[[UUID, Args, str], Awaitable[None]] | None = None


class BadJobError(ValueError):
    """The job's arguments are malformed; retrying cannot help."""


def tenant_of(args: Mapping[str, Any]) -> UUID:
    try:
        return UUID(str(args["tenant_id"]))
    except (KeyError, ValueError) as error:
        raise BadJobError("job has no valid tenant_id") from error


def build_app(conninfo: str) -> App:
    return App(connector=PsycopgConnector(conninfo=conninfo, min_size=1, max_size=4))


def register(app: App, task: Task) -> None:
    # Procrastinate counts retries: the first run plus max_attempts more.
    retry = RetryStrategy(
        max_attempts=MAX_ATTEMPTS - 1, exponential_wait=5, retry_exceptions=[Exception]
    )

    async def run(context: JobContext, /, **kwargs: JsonValue) -> None:
        try:
            tenant_id = tenant_of(kwargs)
        except BadJobError:
            log.exception("job.bad_arguments", task=task.name)
            return  # nothing to retry
        args = {key: value for key, value in kwargs.items() if key != "tenant_id"}
        try:
            await task.run(tenant_id, args)
        except BadJobError:
            log.exception("job.bad_arguments", task=task.name)
            return
        except Exception as error:
            attempts = context.job.attempts  # earlier runs of this job
            final = attempts + 1 >= MAX_ATTEMPTS
            log.warning("job.failed", task=task.name, attempt=attempts + 1, final=final)
            if final and task.on_final_failure is not None:
                await task.on_final_failure(tenant_id, args, type(error).__name__)
            raise

    app.task(name=task.name, queue=task.queue.value, retry=retry, pass_context=True)(run)
