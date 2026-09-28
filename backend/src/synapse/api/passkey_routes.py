"""Passkey endpoints (ADR 0006, docs/design/identity.md).

Registration lives under ``/api/auth`` because it also completes a mandatory enrollment, before
the session is full. Listing and removing are account pages and live under ``/api/account``.
The browser's WebAuthn JSON is passed through as it is; the ``webauthn`` package parses it.
"""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field, field_validator

from synapse.api.auth_routes import SessionView, reject, set_session_cookie
from synapse.api.deps import ApiError, EnrollmentSession, FullSession, PendingSession, client_ip
from synapse.identity.public import (
    LastSecondFactorError,
    LoginRejected,
    PasskeyError,
    PasskeyService,
)

router = APIRouter(tags=["passkeys"])

# A registration response is a few kilobytes; anything far larger is not one.
MAX_CREDENTIAL_BYTES = 16_384


def _passkeys(request: Request) -> PasskeyService:
    service: PasskeyService | None = request.app.state.passkeys
    if service is None:
        # SYNAPSE_PUBLIC_URL is not set, so there is no site to bind passkeys to.
        raise ApiError(status.HTTP_409_CONFLICT, "passkeys_unavailable")
    return service


class CredentialBody(BaseModel):
    credential: dict[str, Any]

    @field_validator("credential")
    @classmethod
    def _bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value)) > MAX_CREDENTIAL_BYTES:
            raise ValueError("credential too large")
        return value


class Registration(CredentialBody):
    name: str = Field(min_length=1, max_length=100)


class RegisteredView(BaseModel):
    id: UUID
    recovery_codes: list[str] | None
    # Present when the registration completed a mandatory enrollment; the cookie changes too.
    session: SessionView | None


class PasskeyView(BaseModel):
    id: UUID
    name: str
    synced: bool
    created_at: datetime
    last_used_at: datetime | None


@router.post("/api/auth/passkeys/registration-options")
async def registration_options(session: EnrollmentSession, request: Request) -> dict[str, Any]:
    try:
        return await _passkeys(request).registration_options(session)
    except PasskeyError as error:  # pragma: no cover  (the dependency checks the level first)
        raise ApiError(status.HTTP_409_CONFLICT, "passkey_failed") from error


@router.post("/api/auth/passkeys", status_code=status.HTTP_201_CREATED)
async def register(
    body: Registration, session: EnrollmentSession, request: Request, response: Response
) -> RegisteredView:
    try:
        registered = await _passkeys(request).register(
            session,
            body.credential,
            body.name.strip() or "Passkey",
            client_ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except PasskeyError as error:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "passkey_failed") from error
    upgraded = None
    if registered.session is not None:
        set_session_cookie(response, registered.session)
        upgraded = SessionView(
            auth_level=registered.session.auth_level, csrf_token=registered.session.csrf_token
        )
    return RegisteredView(
        id=registered.passkey_id, recovery_codes=registered.recovery_codes, session=upgraded
    )


@router.post("/api/auth/mfa/passkey/options")
async def authentication_options(session: PendingSession, request: Request) -> dict[str, Any]:
    try:
        return await _passkeys(request).authentication_options(session)
    except PasskeyError as error:
        raise ApiError(status.HTTP_409_CONFLICT, "no_passkey") from error


@router.post("/api/auth/mfa/passkey")
async def authenticate(
    body: CredentialBody, session: PendingSession, request: Request, response: Response
) -> SessionView:
    result = await _passkeys(request).authenticate(
        session,
        body.credential,
        client_ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    if isinstance(result, LoginRejected):
        raise reject(result, invalid="passkey_failed")
    set_session_cookie(response, result)
    return SessionView(auth_level=result.auth_level, csrf_token=result.csrf_token)


@router.get("/api/account/passkeys")
async def list_passkeys(session: FullSession, request: Request) -> list[PasskeyView]:
    return [
        PasskeyView(
            id=passkey.id,
            name=passkey.name,
            synced=passkey.backed_up,
            created_at=passkey.created_at,
            last_used_at=passkey.last_used_at,
        )
        for passkey in await _passkeys(request).list_passkeys(session)
    ]


@router.delete("/api/account/passkeys/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_passkey(passkey_id: UUID, session: FullSession, request: Request) -> None:
    try:
        removed = await _passkeys(request).remove(session, passkey_id, client_ip=client_ip(request))
    except LastSecondFactorError as error:
        raise ApiError(status.HTTP_409_CONFLICT, "last_second_factor") from error
    if not removed:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found")
