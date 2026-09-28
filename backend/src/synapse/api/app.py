"""FastAPI application factory."""

import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel

from synapse import __version__
from synapse.kernel.config import Settings, get_settings
from synapse.kernel.logging import configure_logging

REQUEST_ID_HEADER = "X-Request-ID"

log = structlog.get_logger(__name__)


class HealthResponse(BaseModel):
    status: str
    version: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application.

    Settings are injectable so tests can run the app with explicit configuration.
    """
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="Synapse API",
        version=__version__,
        # The interactive docs are served only through the API prefix, never at the site root.
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )

    @app.middleware("http")
    async def bind_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Accept an upstream ID only if it looks like one of ours; otherwise mint a new one,
        # so a client cannot inject arbitrary text into every log line.
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _is_uuid(incoming) else str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @app.get("/healthz", response_model=HealthResponse, include_in_schema=False)
    async def healthz() -> HealthResponse:
        """Liveness: the process is up and serving requests."""
        return HealthResponse(status="ok", version=__version__)

    @app.get("/readyz", response_model=HealthResponse, include_in_schema=False)
    async def readyz() -> HealthResponse:
        """Readiness: dependencies are reachable.

        There are no dependencies yet. Database and model checks are added here as those
        components land, and this endpoint must then fail when any of them is unavailable.
        """
        return HealthResponse(status="ok", version=__version__)

    log.info("api.created", version=__version__)
    return app


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
