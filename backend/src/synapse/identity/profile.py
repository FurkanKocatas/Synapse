"""What a signed-in user can change about their own account (ADR 0006).

- Password: the current password must be given (throttled like sign-in); the new one follows
  the policy for the account's factors. Every other session of the account ends, so a leaked
  password stops working everywhere except where the user is changing it.
- Sessions: the user sees their own active sessions and can end any of them.
- Language: stored on the account, so it follows the user to every browser.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from psycopg.rows import class_row

from synapse.audit import public as audit
from synapse.audit.public import AuditEvent
from synapse.identity import passwords, repository, throttle
from synapse.identity.service import CurrentSession
from synapse.kernel.database import Database

Locale = Literal["tr", "en"]


class WrongPasswordError(ValueError):
    """The current password was not correct."""


class TooManyAttemptsError(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("too many attempts")
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class SessionInfo:
    id: UUID
    created_at: datetime
    last_seen_at: datetime
    client_ip: str | None
    user_agent: str | None
    current: bool


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ProfileService:
    def __init__(
        self, database: Database, *, tenant_id: UUID, clock: Callable[[], datetime] = _utc_now
    ) -> None:
        self._db = database
        self._tenant_id = tenant_id
        self._now = clock

    async def change_password(
        self, session: CurrentSession, current: str, new: str, *, client_ip: str | None
    ) -> None:
        subject = f"password:{session.user_id}"
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            blocked = await repository.blocked_subjects(connection, [subject], now)
            user = await repository.user_by_id(connection, session.user_id)
            mfa_enabled = await repository.has_second_factor(connection, session.user_id)
            organization = await repository.organization_name(connection)
        if blocked:
            raise TooManyAttemptsError(max(1, int((blocked - now).total_seconds())))
        if user is None:  # pragma: no cover  (the session exists, so the user does)
            raise WrongPasswordError
        if not await asyncio.to_thread(passwords.verify_password, user.password_hash, current):
            await self._record_failure(subject, session, client_ip, now)
            raise WrongPasswordError
        passwords.validate_password(
            new,
            mfa_enabled=mfa_enabled,
            context_words=[user.email.split("@")[0], user.display_name, organization],
        )
        new_hash = await asyncio.to_thread(passwords.hash_password, new)
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            await repository.set_password_hash(connection, session.user_id, new_hash)
            await repository.clear_failures(connection, subject)
            await connection.execute(
                "UPDATE user_sessions SET revoked_at = %s, revoked_reason = 'password_changed' "
                "WHERE user_id = %s AND id <> %s AND revoked_at IS NULL",
                (now, session.user_id, session.session_id),
            )
            await audit.record(
                connection,
                self._tenant_id,
                AuditEvent(
                    "identity.password.change",
                    "success",
                    actor_user_id=session.user_id,
                    actor_ip=client_ip,
                ),
                now,
            )

    async def _record_failure(
        self, subject: str, session: CurrentSession, client_ip: str | None, now: datetime
    ) -> None:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            failures = await repository.record_failure(connection, self._tenant_id, subject, now)
            await repository.set_blocked_until(
                connection, subject, throttle.blocked_until(failures, now)
            )
            await audit.record(
                connection,
                self._tenant_id,
                AuditEvent(
                    "identity.password.change",
                    "failure",
                    actor_user_id=session.user_id,
                    actor_ip=client_ip,
                    details={"reason": "wrong_current_password"},
                ),
                now,
            )

    async def sessions(self, session: CurrentSession) -> list[SessionInfo]:
        now = self._now()
        async with (
            self._db.tenant_transaction(self._tenant_id) as connection,
            connection.cursor(row_factory=class_row(SessionInfo)) as cursor,
        ):
            await cursor.execute(
                "SELECT id, created_at, last_seen_at, host(client_ip) AS client_ip, user_agent, "
                "id = %s AS current FROM user_sessions "
                "WHERE user_id = %s AND revoked_at IS NULL AND absolute_expires_at > %s "
                "ORDER BY last_seen_at DESC",
                (session.session_id, session.user_id, now),
            )
            return await cursor.fetchall()

    async def end_session(
        self, session: CurrentSession, session_id: UUID, *, client_ip: str | None
    ) -> bool:
        """End one of the user's own sessions; False if it is not theirs or already ended."""
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            cursor = await connection.execute(
                "UPDATE user_sessions SET revoked_at = %s, revoked_reason = 'ended_by_user' "
                "WHERE id = %s AND user_id = %s AND revoked_at IS NULL",
                (now, session_id, session.user_id),
            )
            if cursor.rowcount == 0:
                return False
            await audit.record(
                connection,
                self._tenant_id,
                AuditEvent(
                    "identity.session.end",
                    "success",
                    actor_user_id=session.user_id,
                    actor_ip=client_ip,
                    target_type="session",
                    target_id=str(session_id),
                ),
                now,
            )
        return True

    async def set_locale(self, session: CurrentSession, locale: Locale) -> None:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            await connection.execute(
                "UPDATE users SET locale = %s, updated_at = %s WHERE id = %s",
                (locale, self._now(), session.user_id),
            )
