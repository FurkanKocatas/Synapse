"""Request dependencies shared by all routes: the current session and CSRF protection.

Routes declare what they need (``FullSession``, ``PendingSession``...) and FastAPI resolves it.
Anything that fails here denies the request; there is no fallback path (ADR 0006, ADR 0007).
"""

import ipaddress
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.params import Depends as DependsMarker

from synapse.authz import public as authz
from synapse.identity.public import CurrentSession, IdentityService
from synapse.kernel.database import Database

SESSION_COOKIE = "__Host-synapse_session"
CSRF_HEADER = "X-Synapse-CSRF"
# Required on requests made before there is a session (login). A custom header cannot be sent
# cross-site without a CORS preflight, which this API never grants, so a hostile page cannot
# submit the login form in the user's browser.
CLIENT_HEADER = "X-Synapse-Client"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

log = structlog.get_logger(__name__)


class ApiError(HTTPException):
    """An error with a stable, translatable code in the body: ``{"error": "<code>"}``."""

    def __init__(self, status_code: int, code: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(status_code=status_code, detail=code, headers=headers)
        self.code = code


def identity_service(request: Request) -> IdentityService:
    service: IdentityService = request.app.state.identity
    return service


Identity = Annotated[IdentityService, Depends(identity_service)]


def client_ip(request: Request) -> str | None:
    """The client's IP address, or None when the transport does not provide a valid one.

    Uvicorn has already applied X-Forwarded-For, but only from the trusted proxy addresses.
    Anything that is not an IP address (a Unix socket, a test client name) is discarded rather
    than stored, because it would be meaningless in the audit log and throttle keys.
    """
    host = request.client.host if request.client else None
    if host is None:
        return None
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


async def _current_session(request: Request, identity: Identity) -> CurrentSession:
    token = request.cookies.get(SESSION_COOKIE)
    session = await identity.authenticate(token) if token else None
    if session is None:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "not_authenticated")
    # Every later line of this request says whose it is (ADR 0014).
    structlog.contextvars.bind_contextvars(user_id=str(session.user_id))
    if request.method not in _SAFE_METHODS:
        presented = request.headers.get(CSRF_HEADER, "")
        if not identity.csrf_matches(session, presented):
            log.warning("api.csrf_failed", method=request.method, path=request.url.path)
            raise ApiError(status.HTTP_403_FORBIDDEN, "csrf_failed")
    return session


async def _full_session(
    session: Annotated[CurrentSession, Depends(_current_session)],
) -> CurrentSession:
    if session.auth_level != "full":
        raise ApiError(status.HTTP_403_FORBIDDEN, "second_factor_required")
    return session


async def _pending_session(
    session: Annotated[CurrentSession, Depends(_current_session)],
) -> CurrentSession:
    if session.auth_level != "pending_mfa":
        raise ApiError(status.HTTP_409_CONFLICT, "no_second_factor_pending")
    return session


async def _enrollment_session(
    session: Annotated[CurrentSession, Depends(_current_session)],
) -> CurrentSession:
    if session.auth_level not in ("enroll_mfa", "full"):
        raise ApiError(status.HTTP_403_FORBIDDEN, "second_factor_required")
    return session


def require_client_header(request: Request) -> None:
    if request.headers.get(CLIENT_HEADER) != "web":
        raise ApiError(status.HTTP_403_FORBIDDEN, "client_header_missing")


AnySession = Annotated[CurrentSession, Depends(_current_session)]
FullSession = Annotated[CurrentSession, Depends(_full_session)]
PendingSession = Annotated[CurrentSession, Depends(_pending_session)]
EnrollmentSession = Annotated[CurrentSession, Depends(_enrollment_session)]


def public_endpoint() -> None:
    """Marks a route as reachable without a session, on purpose.

    Every route must either depend on a session or carry this marker; a test enforces it, so a
    route cannot become public by forgetting a dependency (ADR 0007).
    """


def require(permission: str) -> DependsMarker:
    """A dependency that allows the request only if the user's role has ``permission``.

    Unknown permission names fail when the route is defined, not at request time.
    """
    authz.check_known(permission)

    async def check(session: FullSession, request: Request) -> CurrentSession:
        database: Database = request.app.state.database
        async with database.tenant_transaction(request.app.state.tenant_id) as connection:
            allowed = await authz.role_has_permission(connection, session.role, permission)
        if not allowed:
            log.warning(
                "api.forbidden", permission=permission, role=session.role, path=request.url.path
            )
            raise ApiError(status.HTTP_403_FORBIDDEN, "forbidden")
        return session

    check.__name__ = f"require_{permission.replace('.', '_')}"
    return DependsMarker(check)
