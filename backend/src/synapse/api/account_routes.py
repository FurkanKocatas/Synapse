"""The signed-in user's own account under ``/api/account`` (ADR 0006)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from synapse.api.deps import ApiError, FullSession, client_ip
from synapse.identity.public import (
    PasswordPolicyError,
    ProfileService,
    TooManyAttemptsError,
    WrongPasswordError,
)

router = APIRouter(prefix="/api/account", tags=["account"])


def _profile(request: Request) -> ProfileService:
    service: ProfileService = request.app.state.profile
    return service


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)


class SessionView(BaseModel):
    id: UUID
    created_at: datetime
    last_seen_at: datetime
    client_ip: str | None
    user_agent: str | None
    current: bool


class Preferences(BaseModel):
    locale: Literal["tr", "en"]


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(body: PasswordChange, session: FullSession, request: Request) -> None:
    try:
        await _profile(request).change_password(
            session, body.current_password, body.new_password, client_ip=client_ip(request)
        )
    except WrongPasswordError as error:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "wrong_password") from error
    except TooManyAttemptsError as error:
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too_many_attempts",
            {"Retry-After": str(error.retry_after_seconds)},
        ) from error
    except PasswordPolicyError as error:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code) from error


@router.get("/sessions")
async def list_sessions(session: FullSession, request: Request) -> list[SessionView]:
    return [SessionView(**vars(info)) for info in await _profile(request).sessions(session)]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def end_session(session_id: UUID, session: FullSession, request: Request) -> None:
    ended = await _profile(request).end_session(session, session_id, client_ip=client_ip(request))
    if not ended:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found")


@router.put("/preferences", status_code=status.HTTP_204_NO_CONTENT)
async def set_preferences(body: Preferences, session: FullSession, request: Request) -> None:
    await _profile(request).set_locale(session, body.locale)
