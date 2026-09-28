"""SQL for the identity tables. Every function runs inside a caller's tenant transaction."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import class_row

Role = Literal["admin", "editor", "member", "auditor"]
AuthLevel = Literal["pending_mfa", "enroll_mfa", "full"]


@dataclass(frozen=True)
class UserRecord:
    id: UUID
    email: str
    display_name: str
    role: Role
    status: str
    locale: str
    password_hash: str | None


@dataclass(frozen=True)
class SessionRecord:
    id: UUID
    user_id: UUID
    auth_level: AuthLevel
    last_seen_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None
    user_status: str
    user_role: Role
    user_email: str
    user_display_name: str
    user_locale: str


@dataclass(frozen=True)
class TotpRecord:
    secret_ciphertext: bytes
    confirmed_at: datetime | None
    last_used_step: int | None


@dataclass(frozen=True)
class NewUser:
    tenant_id: UUID
    email: str
    display_name: str
    role: Role
    locale: str
    password_hash: str | None


@dataclass(frozen=True)
class NewSession:
    tenant_id: UUID
    user_id: UUID
    token_hash: bytes
    auth_level: AuthLevel
    absolute_expires_at: datetime
    client_ip: str | None
    user_agent: str | None
    # From the application clock, like every expiry comparison, so that one clock decides.
    created_at: datetime


class RowMissingError(RuntimeError):
    """A statement that must return a row returned none: a bug or a concurrent deletion."""


def _required(row: tuple[object, ...] | None) -> tuple[object, ...]:
    if row is None:
        raise RowMissingError("expected a returned row")
    return row


# Users


async def user_by_email(connection: AsyncConnection, email: str) -> UserRecord | None:
    async with connection.cursor(row_factory=class_row(UserRecord)) as cursor:
        await cursor.execute(
            "SELECT id, email, display_name, role, status, locale, password_hash "
            "FROM users WHERE email = %s",
            (email,),
        )
        return await cursor.fetchone()


async def user_by_id(connection: AsyncConnection, user_id: UUID) -> UserRecord | None:
    async with connection.cursor(row_factory=class_row(UserRecord)) as cursor:
        await cursor.execute(
            "SELECT id, email, display_name, role, status, locale, password_hash "
            "FROM users WHERE id = %s",
            (user_id,),
        )
        return await cursor.fetchone()


async def insert_user(connection: AsyncConnection, user: NewUser) -> UUID:
    cursor = await connection.execute(
        "INSERT INTO users (tenant_id, email, display_name, role, locale, password_hash, "
        "password_changed_at) VALUES (%s, %s, %s, %s, %s, %s, "
        "CASE WHEN %s::text IS NULL THEN NULL ELSE now() END) RETURNING id",
        (
            user.tenant_id,
            user.email,
            user.display_name,
            user.role,
            user.locale,
            user.password_hash,
            user.password_hash,
        ),
    )
    return UUID(str(_required(await cursor.fetchone())[0]))


async def set_password_hash(connection: AsyncConnection, user_id: UUID, password_hash: str) -> None:
    await connection.execute(
        "UPDATE users SET password_hash = %s, password_changed_at = now(), updated_at = now() "
        "WHERE id = %s",
        (password_hash, user_id),
    )


# Throttling


async def blocked_subjects(
    connection: AsyncConnection, subjects: list[str], now: datetime
) -> datetime | None:
    """The latest time until which any of ``subjects`` is blocked, if one is blocked now."""
    cursor = await connection.execute(
        "SELECT max(blocked_until) FROM auth_throttle "
        "WHERE subject = ANY(%s) AND blocked_until > %s",
        (subjects, now),
    )
    row = await cursor.fetchone()
    return row[0] if row else None


async def record_failure(
    connection: AsyncConnection, tenant_id: UUID, subject: str, now: datetime
) -> int:
    """Count one more consecutive failure for ``subject``; returns the new count."""
    cursor = await connection.execute(
        "INSERT INTO auth_throttle (tenant_id, subject, failures, last_failure_at) "
        "VALUES (%s, %s, 1, %s) "
        "ON CONFLICT (tenant_id, subject) DO UPDATE "
        "SET failures = auth_throttle.failures + 1, last_failure_at = EXCLUDED.last_failure_at "
        "RETURNING failures",
        (tenant_id, subject, now),
    )
    return int(str(_required(await cursor.fetchone())[0]))


async def set_blocked_until(
    connection: AsyncConnection, subject: str, blocked_until: datetime | None
) -> None:
    await connection.execute(
        "UPDATE auth_throttle SET blocked_until = %s WHERE subject = %s", (blocked_until, subject)
    )


async def clear_failures(connection: AsyncConnection, subject: str) -> None:
    await connection.execute("DELETE FROM auth_throttle WHERE subject = %s", (subject,))


# Sessions


async def insert_session(connection: AsyncConnection, session: NewSession) -> UUID:
    cursor = await connection.execute(
        "INSERT INTO user_sessions (tenant_id, user_id, token_hash, auth_level, "
        "absolute_expires_at, client_ip, user_agent, created_at, last_seen_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            session.tenant_id,
            session.user_id,
            session.token_hash,
            session.auth_level,
            session.absolute_expires_at,
            session.client_ip,
            (session.user_agent or "")[:512] or None,
            session.created_at,
            session.created_at,
        ),
    )
    return UUID(str(_required(await cursor.fetchone())[0]))


async def session_by_token_hash(
    connection: AsyncConnection, token_hash: bytes
) -> SessionRecord | None:
    async with connection.cursor(row_factory=class_row(SessionRecord)) as cursor:
        await cursor.execute(
            "SELECT s.id, s.user_id, s.auth_level, s.last_seen_at, s.absolute_expires_at, "
            "s.revoked_at, u.status AS user_status, u.role AS user_role, "
            "u.email AS user_email, u.display_name AS user_display_name, "
            "u.locale AS user_locale "
            "FROM user_sessions s JOIN users u ON u.tenant_id = s.tenant_id AND u.id = s.user_id "
            "WHERE s.token_hash = %s",
            (token_hash,),
        )
        return await cursor.fetchone()


async def touch_session(connection: AsyncConnection, session_id: UUID, now: datetime) -> None:
    await connection.execute(
        "UPDATE user_sessions SET last_seen_at = %s WHERE id = %s", (now, session_id)
    )


async def revoke_session(
    connection: AsyncConnection, session_id: UUID, reason: str, now: datetime
) -> None:
    await connection.execute(
        "UPDATE user_sessions SET revoked_at = %s, revoked_reason = %s "
        "WHERE id = %s AND revoked_at IS NULL",
        (now, reason, session_id),
    )


async def revoke_user_sessions(
    connection: AsyncConnection, user_id: UUID, reason: str, now: datetime
) -> None:
    await connection.execute(
        "UPDATE user_sessions SET revoked_at = %s, revoked_reason = %s "
        "WHERE user_id = %s AND revoked_at IS NULL",
        (now, reason, user_id),
    )


# Second factors: TOTP, passkeys and recovery codes


async def has_second_factor(connection: AsyncConnection, user_id: UUID) -> bool:
    """A confirmed TOTP authenticator or a passkey (migration 0007)."""
    cursor = await connection.execute("SELECT user_has_second_factor(%s)", (user_id,))
    return bool(_required(await cursor.fetchone())[0])


async def has_passkey(connection: AsyncConnection, user_id: UUID) -> bool:
    cursor = await connection.execute(
        "SELECT EXISTS (SELECT 1 FROM passkeys WHERE user_id = %s)", (user_id,)
    )
    return bool(_required(await cursor.fetchone())[0])


async def delete_second_factors(connection: AsyncConnection, user_id: UUID) -> None:
    await connection.execute("DELETE FROM totp_credentials WHERE user_id = %s", (user_id,))
    await connection.execute("DELETE FROM passkeys WHERE user_id = %s", (user_id,))
    await connection.execute("DELETE FROM recovery_codes WHERE user_id = %s", (user_id,))


async def totp_for_user(connection: AsyncConnection, user_id: UUID) -> TotpRecord | None:
    async with connection.cursor(row_factory=class_row(TotpRecord)) as cursor:
        await cursor.execute(
            "SELECT secret_ciphertext, confirmed_at, last_used_step FROM totp_credentials "
            "WHERE user_id = %s",
            (user_id,),
        )
        return await cursor.fetchone()


async def store_pending_totp(
    connection: AsyncConnection, tenant_id: UUID, user_id: UUID, ciphertext: bytes
) -> None:
    """Start (or restart) enrollment. A confirmed credential is never overwritten here."""
    await connection.execute(
        "INSERT INTO totp_credentials (tenant_id, user_id, secret_ciphertext) VALUES (%s, %s, %s) "
        "ON CONFLICT (tenant_id, user_id) DO UPDATE "
        "SET secret_ciphertext = EXCLUDED.secret_ciphertext, last_used_step = NULL, "
        "created_at = now() WHERE totp_credentials.confirmed_at IS NULL",
        (tenant_id, user_id, ciphertext),
    )


async def claim_totp_step(
    connection: AsyncConnection, user_id: UUID, step: int, *, confirm: bool
) -> bool:
    """Record ``step`` as used. False if that step or a later one was already used.

    Doing the check in the UPDATE makes it atomic: of two requests with the same code, only
    one can succeed.
    """
    cursor = await connection.execute(
        "UPDATE totp_credentials SET last_used_step = %s, "
        "confirmed_at = CASE WHEN %s THEN coalesce(confirmed_at, now()) ELSE confirmed_at END "
        "WHERE user_id = %s AND (last_used_step IS NULL OR last_used_step < %s)",
        (step, confirm, user_id, step),
    )
    return cursor.rowcount == 1


async def replace_recovery_codes(
    connection: AsyncConnection, tenant_id: UUID, user_id: UUID, code_hashes: list[str]
) -> None:
    await connection.execute("DELETE FROM recovery_codes WHERE user_id = %s", (user_id,))
    async with connection.cursor() as cursor:
        await cursor.executemany(
            "INSERT INTO recovery_codes (tenant_id, user_id, code_hash) VALUES (%s, %s, %s)",
            [(tenant_id, user_id, code_hash) for code_hash in code_hashes],
        )


async def use_recovery_code(connection: AsyncConnection, user_id: UUID, code_hash: str) -> bool:
    cursor = await connection.execute(
        "UPDATE recovery_codes SET used_at = now() "
        "WHERE user_id = %s AND code_hash = %s AND used_at IS NULL",
        (user_id, code_hash),
    )
    return cursor.rowcount == 1
