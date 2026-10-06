"""FastAPI application factory."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta

import structlog
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from synapse import __version__
from synapse.api import (
    account_routes,
    admin_routes,
    audit_routes,
    auth_routes,
    chat_routes,
    document_routes,
    operations_routes,
    passkey_routes,
    search_routes,
    settings_routes,
)
from synapse.api.deps import ApiError, public_endpoint
from synapse.chat.public import Answerer, Conversations
from synapse.dbadmin import migrate
from synapse.identity.public import (
    AccountService,
    IdentityService,
    PasskeyService,
    ProfileService,
    RelyingParty,
    SessionPolicy,
    TotpCipher,
)
from synapse.kernel.config import Settings, get_settings
from synapse.kernel.database import Database
from synapse.kernel.logging import configure_logging
from synapse.kernel.secrets import read_key
from synapse.knowledge.public import DocumentService, LocalBlobStore, Search
from synapse.models.public import Models, models_from
from synapse.operations.public import Operations
from synapse.organization.public import SettingsService

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
        models = models_from(settings)
        _attach_services(app, settings, database, models)
        log.info(
            "api.started",
            version=__version__,
            schema_revision=expected_revision,
            models=[server.service for server in models.servers],
        )
        try:
            yield
        finally:
            await models.close()
            await database.close()

    app = FastAPI(
        title="Synapse API",
        version=__version__,
        lifespan=lifespan,
        # The interactive docs are off unless enabled, and never served at the site root.
        docs_url="/api/docs" if settings.api_docs else None,
        openapi_url="/api/openapi.json" if settings.api_docs else None,
        redoc_url=None,
    )
    app.include_router(auth_routes.router)
    app.include_router(audit_routes.router)
    app.include_router(admin_routes.router)
    app.include_router(account_routes.router)
    app.include_router(passkey_routes.router)
    app.include_router(document_routes.router)
    app.include_router(search_routes.router)
    app.include_router(chat_routes.router)
    app.include_router(operations_routes.router)
    app.include_router(settings_routes.router)

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

    @app.get(
        "/healthz",
        response_model=HealthResponse,
        include_in_schema=False,
        dependencies=[Depends(public_endpoint)],
    )
    async def healthz() -> HealthResponse:
        """Liveness: the process is up and serving requests."""
        return HealthResponse(status="ok", version=__version__)

    @app.get(
        "/readyz",
        response_model=HealthResponse,
        include_in_schema=False,
        dependencies=[Depends(public_endpoint)],
    )
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


def _attach_services(app: FastAPI, settings: Settings, database: Database, models: Models) -> None:
    """The services every request uses, built once at startup."""
    tenant_id = settings.tenant_id
    if tenant_id is None:  # pragma: no cover  (checked by the caller)
        raise StartupError("SYNAPSE_TENANT_ID is not set")
    app.state.database = database
    app.state.tenant_id = tenant_id
    # Read when a signed export or a checkpoint check needs it (api/audit_routes.py).
    app.state.audit_signing_key_file = settings.audit_signing_key_file
    identity = IdentityService(
        database,
        tenant_id=tenant_id,
        csrf_key=read_key(settings.csrf_key_file),
        totp_cipher=TotpCipher(read_key(settings.totp_key_file)),
        policy=SessionPolicy(
            idle_timeout=timedelta(minutes=settings.session_idle_minutes),
            absolute_lifetime=timedelta(hours=settings.session_absolute_hours),
        ),
    )
    app.state.identity = identity
    app.state.passkeys = (
        PasskeyService(
            database,
            tenant_id=tenant_id,
            identity=identity,
            relying_party=RelyingParty.from_url(settings.public_url),
        )
        if settings.public_url
        else None
    )
    blobs = LocalBlobStore(settings.blob_dir)
    app.state.blobs = blobs
    app.state.upload_max_bytes = settings.upload_max_mb * 1024 * 1024
    app.state.documents = DocumentService(database, blobs, tenant_id=tenant_id)
    search = Search(
        database, tenant_id=tenant_id, embedder=models.embedder, reranker=models.reranker
    )
    app.state.search = search
    app.state.conversations = Conversations(
        database,
        tenant_id=tenant_id,
        answerer=Answerer(
            search,
            models.chat,
            refuse_below=settings.chat_refuse_below,
            general=settings.chat_general_answers,
        ),
        classic=settings.chat_classic,
    )
    app.state.classic_chat = settings.chat_classic
    app.state.accounts = AccountService(database, tenant_id=tenant_id)
    app.state.profile = ProfileService(database, tenant_id=tenant_id)
    app.state.organization = SettingsService(database, tenant_id=tenant_id)
    app.state.operations = Operations(
        database,
        tenant_id=tenant_id,
        blob_dir=settings.blob_dir,
        servers=models.servers,
        embeds=models.embedder is not None,
    )


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
