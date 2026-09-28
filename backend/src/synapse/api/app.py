"""FastAPI application factory."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta

import structlog
from alembic.script import ScriptDirectory
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from synapse import __version__
from synapse.api import auth_routes
from synapse.api.deps import ApiError
from synapse.dbadmin import migrate
from synapse.identity.public import IdentityService, SessionPolicy, TotpCipher
from synapse.kernel.config import Settings, get_settings
from synapse.kernel.database import Database
from synapse.kernel.logging import configure_logging
from synapse.kernel.secrets import read_key

REQUEST_ID_HEADER = "X-Request-ID"

log = structlog.get_logger(__name__)


class HealthResponse(BaseModel):
    status: str
    version: str


class StartupError(RuntimeError):
    """The API cannot start with this configuration."""


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application.

    Settings are injectable so tests can run the app with explicit configuration.
    """
    settings = settings or get_settings()
    configure_logging(settings)
    expected_revision = _expected_revision()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.tenant_id is None:
            raise StartupError("SYNAPSE_TENANT_ID is not set; the installer writes it")
        database = Database(settings.database(application_name="synapse-api"))
        await database.open()
        app.state.database = database
        app.state.identity = IdentityService(
            database,
            tenant_id=settings.tenant_id,
            csrf_key=read_key(settings.csrf_key_file),
            totp_cipher=TotpCipher(read_key(settings.totp_key_file)),
            policy=SessionPolicy(
                idle_timeout=timedelta(minutes=settings.session_idle_minutes),
                absolute_lifetime=timedelta(hours=settings.session_absolute_hours),
            ),
        )
        log.info("api.started", version=__version__, schema_revision=expected_revision)
        try:
            yield
        finally:
            await database.close()

    app = FastAPI(
        title="Synapse API",
        version=__version__,
        lifespan=lifespan,
        # The interactive docs are served only through the API prefix, never at the site root.
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.include_router(auth_routes.router)

    @app.exception_handler(ApiError)
    async def api_error(_: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(
            {"error": error.code}, status_code=error.status_code, headers=error.headers
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
    async def readyz(request: Request) -> Response:
        """Readiness: the database answers and its schema is the revision this code expects."""
        database: Database = request.app.state.database
        try:
            async with database.system_transaction() as connection:
                cursor = await connection.execute("SELECT version_num FROM alembic_version")
                row = await cursor.fetchone()
        except Exception:
            log.exception("api.not_ready.database")
            return _not_ready()
        if row is None or row[0] != expected_revision:
            log.error("api.not_ready.schema", found=row[0] if row else None)
            return _not_ready()
        return JSONResponse({"status": "ok", "version": __version__})

    return app


def _not_ready() -> JSONResponse:
    return JSONResponse({"status": "not_ready", "version": __version__}, status_code=503)


def _expected_revision() -> str:
    """The newest migration shipped with this code; the database must be at exactly this one."""
    head = ScriptDirectory.from_config(migrate.script_config()).get_current_head()
    if head is None:
        raise StartupError("no migrations found")
    return head


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
