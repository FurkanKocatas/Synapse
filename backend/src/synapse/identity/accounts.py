"""Account administration: listing accounts and changing their role or status (ADR 0006).

Changing a role or disabling an account ends the account's sessions at once, so new rights (or
the loss of them) apply to the very next request. The last active administrator cannot be
demoted or disabled, which would lock the organization out of its own installation.

An administrator can also reset another account's password or second factor, for a user who has
lost them. Both end the account's sessions. Neither works on the administrator's own account:
there the current password is required (see ``profile``), so a stolen session alone cannot take
the account over.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import class_row

from synapse.audit import public as audit
from synapse.audit.public import AuditEvent
from synapse.identity import passwords, repository
from synapse.identity.repository import Role
from synapse.identity.service import email_throttle_subject
from synapse.kernel.database import Database

Status = Literal["active", "disabled"]


@dataclass(frozen=True)
class Account:
    id: UUID
    email: str
    display_name: str
    role: Role
    status: Status
    locale: str
    has_mfa: bool
    created_at: datetime


class LastAdministratorError(RuntimeError):
    """The change would leave the installation without an active administrator."""


class OwnAccountError(ValueError):
    """Resets are for other accounts; one's own password is changed with the current one."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


_ACCOUNT_SELECT = (
    "SELECT u.id, u.email, u.display_name, u.role, u.status, u.locale, "
    "user_has_second_factor(u.id) AS has_mfa, u.created_at FROM users u "
)


class AccountService:
    def __init__(
        self, database: Database, *, tenant_id: UUID, clock: Callable[[], datetime] = _utc_now
    ) -> None:
        self._db = database
        self._tenant_id = tenant_id
        self._now = clock

    async def list_accounts(self) -> list[Account]:
        async with (
            self._db.tenant_transaction(self._tenant_id) as connection,
            connection.cursor(row_factory=class_row(Account)) as cursor,
        ):
            await cursor.execute(_ACCOUNT_SELECT + "ORDER BY lower(u.display_name), u.email")
            return await cursor.fetchall()

    async def update_account(
        self,
        user_id: UUID,
        *,
        actor_user_id: UUID,
        role: Role | None = None,
        status: Status | None = None,
    ) -> Account | None:
        """Apply the given changes; None if the account does not exist."""
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            current = await _account(connection, user_id, lock=True)
            if current is None:
                return None
            changes: dict[str, list[str]] = {}
            if role is not None and role != current.role:
                changes["role"] = [current.role, role]
            if status is not None and status != current.status:
                changes["status"] = [current.status, status]
            if not changes:
                return current
            await connection.execute(
                "UPDATE users SET role = coalesce(%s, role), status = coalesce(%s, status), "
                "updated_at = %s WHERE id = %s",
                (role, status, now, user_id),
            )
            await _ensure_an_administrator_remains(connection)
            await repository.revoke_user_sessions(connection, user_id, "account_changed", now)
            await audit.record(
                connection,
                self._tenant_id,
                AuditEvent(
                    "identity.user.update",
                    "success",
                    actor_user_id=actor_user_id,
                    target_type="user",
                    target_id=str(user_id),
                    details={"changes": changes},
                ),
                now,
            )
            return await _account(connection, user_id, lock=False)

    async def reset_password(self, user_id: UUID, password: str, *, actor_user_id: UUID) -> bool:
        """Set a new password chosen by the administrator; False if the account does not exist."""
        if user_id == actor_user_id:
            raise OwnAccountError
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            account = await _account(connection, user_id, lock=False)
            organization = await repository.organization_name(connection)
        if account is None:
            return False
        passwords.validate_password(
            password,
            mfa_enabled=account.has_mfa,
            context_words=[account.email.split("@")[0], account.display_name, organization],
        )
        password_hash = await asyncio.to_thread(passwords.hash_password, password)
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            if await _account(connection, user_id, lock=True) is None:  # pragma: no cover
                return False
            await repository.set_password_hash(connection, user_id, password_hash)
            await repository.clear_failures(connection, email_throttle_subject(account.email))
            await repository.clear_failures(connection, f"password:{user_id}")
            await repository.revoke_user_sessions(connection, user_id, "password_reset", now)
            await self._audit(connection, "identity.password.reset", actor_user_id, user_id, now)
        return True

    async def reset_mfa(self, user_id: UUID, *, actor_user_id: UUID) -> bool:
        """Remove every second factor and the recovery codes; False if the account does not exist.

        An account whose role requires a second factor has to enroll again at the next sign-in.
        """
        if user_id == actor_user_id:
            raise OwnAccountError
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            if await _account(connection, user_id, lock=True) is None:
                return False
            await repository.delete_second_factors(connection, user_id)
            await repository.clear_failures(connection, f"mfa:{user_id}")
            await repository.revoke_user_sessions(connection, user_id, "mfa_reset", now)
            await self._audit(connection, "identity.mfa.reset", actor_user_id, user_id, now)
        return True

    async def _audit(
        self,
        connection: AsyncConnection,
        action: str,
        actor_user_id: UUID,
        user_id: UUID,
        now: datetime,
    ) -> None:
        await audit.record(
            connection,
            self._tenant_id,
            AuditEvent(
                action,
                "success",
                actor_user_id=actor_user_id,
                target_type="user",
                target_id=str(user_id),
            ),
            now,
        )


async def _account(connection: AsyncConnection, user_id: UUID, *, lock: bool) -> Account | None:
    suffix = "WHERE u.id = %s FOR UPDATE OF u" if lock else "WHERE u.id = %s"
    async with connection.cursor(row_factory=class_row(Account)) as cursor:
        await cursor.execute(_ACCOUNT_SELECT + suffix, (user_id,))
        return await cursor.fetchone()


async def _ensure_an_administrator_remains(connection: AsyncConnection) -> None:
    # Runs inside the transaction after the update; raising rolls the change back. The admin
    # rows are locked so two concurrent demotions cannot both pass this check.
    cursor = await connection.execute(
        "SELECT count(*) FROM (SELECT 1 FROM users WHERE role = 'admin' AND status = 'active' "
        "FOR UPDATE) AS admins"
    )
    row = await cursor.fetchone()
    if not row or row[0] == 0:
        raise LastAdministratorError("at least one active administrator must remain")
