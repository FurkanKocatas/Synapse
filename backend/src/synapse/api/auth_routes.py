"""Sign-in endpoints under ``/api/auth`` (ADR 0006).

The session token only ever travels in the ``__Host-`` cookie; response bodies carry the CSRF
token and what the client must do next (``auth_level``), never the session token.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from synapse.api.deps import (
    SESSION_COOKIE,
    AnySession,
    ApiError,
    EnrollmentSession,
    Identity,
    PendingSession,
    client_ip,
    require_client_header,
)
from synapse.identity.public import AuthLevel, CurrentSession, IssuedSession, LoginRejected

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)


class CodeRequest(BaseModel):
    code: str = Field(max_length=64)


class UserView(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    locale: str


class SessionView(BaseModel):
    auth_level: AuthLevel
    csrf_token: str
    user: UserView | None = None


class EnrollmentView(BaseModel):
    secret: str
    provisioning_uri: str


class EnrollmentConfirmedView(SessionView):
    recovery_codes: list[str]


def _set_session_cookie(response: Response, issued: IssuedSession) -> None:
    max_age = max(0, int((issued.expires_at - datetime.now(UTC)).total_seconds()))
    response.set_cookie(
        SESSION_COOKIE,
        issued.token,
        max_age=max_age,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def _reject(rejected: LoginRejected) -> ApiError:
    if rejected.reason == "throttled":
        seconds = max(1, int(rejected.retry_after.total_seconds())) if rejected.retry_after else 1
        return ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS, "too_many_attempts", {"Retry-After": str(seconds)}
        )
    return ApiError(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")


def _user_view(session: CurrentSession) -> UserView:
    return UserView(
        id=str(session.user_id),
        email=session.email,
        display_name=session.display_name,
        role=session.role,
        locale=session.locale,
    )


@router.post("/login", dependencies=[Depends(require_client_header)])
async def login(
    body: LoginRequest, request: Request, response: Response, identity: Identity
) -> SessionView:
    result = await identity.login(
        body.email,
        body.password,
        client_ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    if isinstance(result, LoginRejected):
        raise _reject(result)
    _set_session_cookie(response, result)
    return SessionView(auth_level=result.auth_level, csrf_token=result.csrf_token)


@router.get("/session")
async def current_session(session: AnySession, identity: Identity) -> SessionView:
    return SessionView(
        auth_level=session.auth_level,
        csrf_token=identity.csrf_token_for(session),
        user=_user_view(session) if session.auth_level == "full" else None,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(session: AnySession, identity: Identity, response: Response) -> None:
    await identity.logout(session)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")


@router.post("/mfa/verify")
async def verify_second_factor(
    body: CodeRequest,
    session: PendingSession,
    request: Request,
    response: Response,
    identity: Identity,
) -> SessionView:
    result = await identity.complete_mfa(
        session,
        body.code,
        client_ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    if isinstance(result, LoginRejected):
        raise _reject(result)
    _set_session_cookie(response, result)
    return SessionView(auth_level=result.auth_level, csrf_token=result.csrf_token)


@router.post("/mfa/totp/enroll")
async def start_totp_enrollment(session: EnrollmentSession, identity: Identity) -> EnrollmentView:
    enrollment = await identity.start_totp_enrollment(session)
    if enrollment is None:
        raise ApiError(status.HTTP_409_CONFLICT, "totp_already_enrolled")
    return EnrollmentView(secret=enrollment.secret, provisioning_uri=enrollment.provisioning_uri)


@router.post("/mfa/totp/confirm")
async def confirm_totp_enrollment(
    body: CodeRequest,
    session: EnrollmentSession,
    request: Request,
    response: Response,
    identity: Identity,
) -> EnrollmentConfirmedView:
    completed = await identity.confirm_totp_enrollment(
        session,
        body.code,
        client_ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    if completed is None:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_code")
    _set_session_cookie(response, completed.session)
    return EnrollmentConfirmedView(
        auth_level=completed.session.auth_level,
        csrf_token=completed.session.csrf_token,
        recovery_codes=completed.recovery_codes,
    )
