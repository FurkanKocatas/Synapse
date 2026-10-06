"""Sign-in, sessions and second factors (ADR 0006).

Flow:

1. ``login`` checks the password. On success it creates a session whose level depends on the
   account: ``pending_mfa`` if a second factor is set up, ``enroll_mfa`` if the account's role
   must use one and it has none (administrators always; other roles when the organisation's
   settings ask it), otherwise ``full``.
2. ``complete_mfa`` or ``confirm_totp_enrollment`` raise the session to ``full``. The session
   token is replaced at that moment, so a token captured before the second factor is useless.
3. ``authenticate`` resolves the cookie token on every request and enforces expiry.

Every failure path returns the same generic outcome to the caller; reasons go to the log only,
so responses never reveal whether an account exists.
"""

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import psycopg
import structlog
from psycopg import AsyncConnection

from synapse.audit import public as audit
from synapse.audit.public import AuditEvent
from synapse.identity import passwords, recovery, repository, throttle, tokens, totp
from synapse.identity.repository import AuthLevel, Role
from synapse.kernel.database import Database

log = structlog.get_logger(__name__)

PENDING_MFA_LIFETIME = timedelta(minutes=5)
ENROLL_MFA_LIFETIME = timedelta(minutes=15)
# Writing last_seen_at on every request would turn every read into a write.
TOUCH_INTERVAL = timedelta(minutes=1)


@dataclass(frozen=True)
class SessionPolicy:
    idle_timeout: timedelta = timedelta(minutes=30)
    absolute_lifetime: timedelta = timedelta(hours=12)


@dataclass(frozen=True)
class IssuedSession:
    """What the HTTP layer needs to set the cookie and tell the client what comes next."""

    token: str
    auth_level: AuthLevel
    expires_at: datetime
    csrf_token: str


@dataclass(frozen=True)
class LoginRejected:
    reason: Literal["invalid", "throttled"]
    retry_after: timedelta | None = None


@dataclass(frozen=True)
class CurrentSession:
    session_id: UUID
    token_hash: bytes
    user_id: UUID
    auth_level: AuthLevel
    role: Role
    email: str
    display_name: str
    locale: str


@dataclass(frozen=True)
class TotpEnrollment:
    secret: str
    provisioning_uri: str


class AccountExistsError(ValueError):
    """An account with this email address already exists in the tenant."""


@dataclass(frozen=True)
class NewAccount:
    email: str
    display_name: str
    role: Role
    password: str | None
    locale: str = "tr"
    # Extra words the password must not contain, such as the organization's name.
    context_words: tuple[str, ...] = ()


@dataclass(frozen=True)
class EnrollmentCompleted:
    session: IssuedSession
    recovery_codes: list[str]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def email_throttle_subject(email: str) -> str:
    return "email:" + hashlib.sha256(email.encode("utf-8")).hexdigest()


class IdentityService:
    def __init__(
        self,
        database: Database,
        *,
        tenant_id: UUID,
        csrf_key: bytes,
        totp_cipher: totp.TotpCipher,
        policy: SessionPolicy | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._db = database
        self._tenant_id = tenant_id
        self._csrf_key = csrf_key
        self._totp = totp_cipher
        self._policy = policy or SessionPolicy()
        self._now = clock

    # Sign-in

    async def login(
        self, email: str, password: str, *, client_ip: str | None, user_agent: str | None
    ) -> IssuedSession | LoginRejected:
        email = normalize_email(email)
        email_subject = email_throttle_subject(email)
        subjects = [email_subject] + ([f"ip:{client_ip}"] if client_ip else [])
        now = self._now()

        async with self._db.tenant_transaction(self._tenant_id) as connection:
            blocked = await repository.blocked_subjects(connection, subjects, now)
            user = None if blocked else await repository.user_by_email(connection, email)
            if blocked:
                await audit.record(
                    connection,
                    self._tenant_id,
                    AuditEvent(
                        "identity.login",
                        "denied",
                        actor_ip=client_ip,
                        details={"reason": "throttled", "email_sha256": email_subject[6:]},
                    ),
                    now,
                )
        if blocked:
            log.info("identity.login.throttled")
            return LoginRejected("throttled", retry_after=blocked - now)

        # Argon2 is deliberately slow: run it off the event loop and outside any transaction.
        stored_hash = user.password_hash if user else None
        valid = await asyncio.to_thread(passwords.verify_password, stored_hash, password)
        if user is None or not valid or user.status != "active":
            # Known accounts are named in the audit log; for unknown ones only the hash of the
            # typed address is kept, so typos do not store other people's addresses.
            failure = AuditEvent(
                "identity.login",
                "failure",
                actor_user_id=user.id if user else None,
                actor_ip=client_ip,
                details={"reason": "invalid_credentials", "email_sha256": email_subject[6:]},
            )
            await self._record_failures(subjects, now, failure)
            log.info("identity.login.failed", known_account=user is not None)
            return LoginRejected("invalid")

        async with self._db.tenant_transaction(self._tenant_id) as connection:
            await repository.clear_failures(connection, email_subject)
            if passwords.needs_rehash(user.password_hash or ""):
                new_hash = await asyncio.to_thread(passwords.hash_password, password)
                await repository.set_password_hash(connection, user.id, new_hash)
            level: AuthLevel
            if await repository.has_second_factor(connection, user.id):
                level, lifetime = "pending_mfa", PENDING_MFA_LIFETIME
            elif user.role in await repository.mfa_roles(connection):
                level, lifetime = "enroll_mfa", ENROLL_MFA_LIFETIME
            else:
                level, lifetime = "full", self._policy.absolute_lifetime
            issued = await self._issue(
                connection, user.id, level, now + lifetime, client_ip, user_agent
            )
            await audit.record(
                connection,
                self._tenant_id,
                AuditEvent(
                    "identity.login",
                    "success",
                    actor_user_id=user.id,
                    actor_ip=client_ip,
                    details={"auth_level": level},
                ),
                now,
            )
        log.info("identity.login.succeeded", user_id=str(user.id), auth_level=level)
        return issued

    async def _record_failures(self, subjects: list[str], now: datetime, event: AuditEvent) -> None:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            await audit.record(connection, self._tenant_id, event, now)
            for subject in subjects:
                failures = await repository.record_failure(
                    connection, self._tenant_id, subject, now
                )
                free = (
                    throttle.FREE_ATTEMPTS_PER_IP
                    if subject.startswith("ip:")
                    else throttle.FREE_ATTEMPTS
                )
                until = throttle.blocked_until(failures, now, free_attempts=free)
                await repository.set_blocked_until(connection, subject, until)
                if subject.startswith("email:") and failures == throttle.NOTIFY_ADMINS_AT:
                    log.warning("identity.login.repeated_failures", failures=failures)

    async def _issue(
        self,
        connection: AsyncConnection,
        user_id: UUID,
        level: AuthLevel,
        expires_at: datetime,
        client_ip: str | None,
        user_agent: str | None,
    ) -> IssuedSession:
        token = tokens.new_session_token()
        token_hash = tokens.hash_session_token(token)
        await repository.insert_session(
            connection,
            repository.NewSession(
                tenant_id=self._tenant_id,
                user_id=user_id,
                token_hash=token_hash,
                auth_level=level,
                absolute_expires_at=expires_at,
                client_ip=client_ip,
                user_agent=user_agent,
                created_at=self._now(),
            ),
        )
        return IssuedSession(
            token=token,
            auth_level=level,
            expires_at=expires_at,
            csrf_token=tokens.csrf_token(self._csrf_key, token_hash),
        )

    # Sessions

    async def authenticate(self, token: str) -> CurrentSession | None:
        """The session behind a cookie token, or None if it is unknown, revoked or expired."""
        token_hash = tokens.hash_session_token(token)
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            record = await repository.session_by_token_hash(connection, token_hash)
            if record is None or record.revoked_at is not None:
                return None
            expired = now >= record.absolute_expires_at or (
                record.auth_level == "full"
                and now - record.last_seen_at >= self._policy.idle_timeout
            )
            if expired or record.user_status != "active":
                reason = "expired" if expired else "user_disabled"
                await repository.revoke_session(connection, record.id, reason, now)
                return None
            if now - record.last_seen_at >= TOUCH_INTERVAL:
                await repository.touch_session(connection, record.id, now)
        return CurrentSession(
            session_id=record.id,
            token_hash=token_hash,
            user_id=record.user_id,
            auth_level=record.auth_level,
            role=record.user_role,
            email=record.user_email,
            display_name=record.user_display_name,
            locale=record.user_locale,
        )

    def csrf_token_for(self, session: CurrentSession) -> str:
        return tokens.csrf_token(self._csrf_key, session.token_hash)

    def csrf_matches(self, session: CurrentSession, presented: str) -> bool:
        return tokens.csrf_token_matches(self._csrf_key, session.token_hash, presented)

    async def logout(self, session: CurrentSession, *, client_ip: str | None = None) -> None:
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            await repository.revoke_session(connection, session.session_id, "logout", now)
            await audit.record(
                connection,
                self._tenant_id,
                AuditEvent(
                    "identity.logout", "success", actor_user_id=session.user_id, actor_ip=client_ip
                ),
                now,
            )

    # Second factor

    async def complete_mfa(
        self, session: CurrentSession, code: str, *, client_ip: str | None, user_agent: str | None
    ) -> IssuedSession | LoginRejected:
        """Accept a TOTP code or a recovery code for a ``pending_mfa`` session."""
        if session.auth_level != "pending_mfa":
            return LoginRejected("invalid")
        subject = f"mfa:{session.user_id}"
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            blocked = await repository.blocked_subjects(connection, [subject], now)
            if blocked:
                await audit.record(
                    connection,
                    self._tenant_id,
                    AuditEvent(
                        "identity.mfa.verify",
                        "denied",
                        actor_user_id=session.user_id,
                        actor_ip=client_ip,
                        details={"reason": "throttled"},
                    ),
                    now,
                )
                return LoginRejected("throttled", retry_after=blocked - now)
            accepted = await self._accept_second_factor(connection, session.user_id, code)
            if accepted:
                await repository.clear_failures(connection, subject)
                issued = await self.upgrade_session(connection, session, now, client_ip, user_agent)
                await audit.record(
                    connection,
                    self._tenant_id,
                    AuditEvent(
                        "identity.mfa.verify",
                        "success",
                        actor_user_id=session.user_id,
                        actor_ip=client_ip,
                    ),
                    now,
                )
        if not accepted:
            failure = AuditEvent(
                "identity.mfa.verify",
                "failure",
                actor_user_id=session.user_id,
                actor_ip=client_ip,
                details={"reason": "invalid_code"},
            )
            await self._record_failures([subject], now, failure)
            log.info("identity.mfa.failed", user_id=str(session.user_id))
            return LoginRejected("invalid")
        log.info("identity.mfa.succeeded", user_id=str(session.user_id))
        return issued

    async def upgrade_session(
        self,
        connection: AsyncConnection,
        session: CurrentSession,
        now: datetime,
        client_ip: str | None,
        user_agent: str | None,
    ) -> IssuedSession:
        """Replace a session that has passed its second factor with a new, full one.

        The token changes at this moment, so a token captured before the second factor is
        useless. Runs in the caller's transaction, next to the check that allowed it.
        """
        await repository.revoke_session(connection, session.session_id, "upgraded", now)
        return await self._issue(
            connection,
            session.user_id,
            "full",
            now + self._policy.absolute_lifetime,
            client_ip,
            user_agent,
        )

    async def issue_recovery_codes(self, connection: AsyncConnection, user_id: UUID) -> list[str]:
        """New recovery codes, replacing any earlier ones. Only their hashes are stored."""
        codes = recovery.new_codes()
        await repository.replace_recovery_codes(
            connection, self._tenant_id, user_id, [recovery.hash_code(c) for c in codes]
        )
        return codes

    async def second_factors(self, session: CurrentSession) -> list[str]:
        """The kinds of second factor the account has: ``totp`` and/or ``passkey``."""
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            credential = await repository.totp_for_user(connection, session.user_id)
            passkey = await repository.has_passkey(connection, session.user_id)
        kinds = ["totp"] if credential is not None and credential.confirmed_at is not None else []
        return [*kinds, "passkey"] if passkey else kinds

    async def _accept_second_factor(
        self, connection: AsyncConnection, user_id: UUID, code: str
    ) -> bool:
        credential = await repository.totp_for_user(connection, user_id)
        if credential is not None and credential.confirmed_at is not None:
            secret = self._totp.decrypt(user_id, credential.secret_ciphertext)
            accepted = totp.verify_code(secret, code, last_used_step=credential.last_used_step)
            if accepted and await repository.claim_totp_step(
                connection, user_id, accepted.step, confirm=False
            ):
                return True
        return await repository.use_recovery_code(connection, user_id, recovery.hash_code(code))

    async def start_totp_enrollment(self, session: CurrentSession) -> TotpEnrollment | None:
        """Create a new, unconfirmed TOTP secret. None if a confirmed one already exists."""
        if session.auth_level not in ("enroll_mfa", "full"):
            return None
        secret = totp.new_secret()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            existing = await repository.totp_for_user(connection, session.user_id)
            if existing is not None and existing.confirmed_at is not None:
                return None
            await repository.store_pending_totp(
                connection,
                self._tenant_id,
                session.user_id,
                self._totp.encrypt(session.user_id, secret),
            )
        return TotpEnrollment(
            secret=secret, provisioning_uri=totp.provisioning_uri(secret, session.email)
        )

    async def confirm_totp_enrollment(
        self, session: CurrentSession, code: str, *, client_ip: str | None, user_agent: str | None
    ) -> EnrollmentCompleted | None:
        """Prove the authenticator works; returns fresh recovery codes and a full session."""
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            credential = await repository.totp_for_user(connection, session.user_id)
            if credential is None or credential.confirmed_at is not None:
                return None
            secret = self._totp.decrypt(session.user_id, credential.secret_ciphertext)
            accepted = totp.verify_code(secret, code, last_used_step=credential.last_used_step)
            if accepted is None or not await repository.claim_totp_step(
                connection, session.user_id, accepted.step, confirm=True
            ):
                await audit.record(
                    connection,
                    self._tenant_id,
                    AuditEvent(
                        "identity.mfa.enroll",
                        "failure",
                        actor_user_id=session.user_id,
                        actor_ip=client_ip,
                        details={"reason": "invalid_code"},
                    ),
                    now,
                )
                return None
            codes = await self.issue_recovery_codes(connection, session.user_id)
            issued = await self.upgrade_session(connection, session, now, client_ip, user_agent)
            await audit.record(
                connection,
                self._tenant_id,
                AuditEvent(
                    "identity.mfa.enroll",
                    "success",
                    actor_user_id=session.user_id,
                    actor_ip=client_ip,
                    details={"method": "totp"},
                ),
                now,
            )
        log.info("identity.mfa.enrolled", user_id=str(session.user_id))
        return EnrollmentCompleted(session=issued, recovery_codes=codes)

    # Accounts

    async def create_user(self, account: NewAccount, *, actor_user_id: UUID | None = None) -> UUID:
        """Create an account. The password must satisfy the policy for a single factor.

        ``actor_user_id`` is the administrator doing it; None means the command line on the
        server (``synapse user create``).
        """
        email = normalize_email(account.email)
        password_hash = None
        if account.password is not None:
            # An administrator's account refuses the organization's name too. The command line
            # is the operator's, on the server; its scripted installs keep to the words given.
            organization = ""
            if actor_user_id is not None:
                async with self._db.tenant_transaction(self._tenant_id) as connection:
                    organization = await repository.organization_name(connection)
            passwords.validate_password(
                account.password,
                mfa_enabled=False,
                context_words=[
                    email.split("@")[0],
                    account.display_name,
                    organization,
                    *account.context_words,
                ],
            )
            password_hash = await asyncio.to_thread(passwords.hash_password, account.password)
        try:
            return await self._insert_account(account, email, password_hash, actor_user_id)
        except psycopg.errors.UniqueViolation as error:
            raise AccountExistsError(email) from error

    async def _insert_account(
        self,
        account: NewAccount,
        email: str,
        password_hash: str | None,
        actor_user_id: UUID | None,
    ) -> UUID:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            user_id = await repository.insert_user(
                connection,
                repository.NewUser(
                    tenant_id=self._tenant_id,
                    email=email,
                    display_name=account.display_name,
                    role=account.role,
                    locale=account.locale,
                    password_hash=password_hash,
                ),
            )
            await audit.record(
                connection,
                self._tenant_id,
                AuditEvent(
                    "identity.user.create",
                    "success",
                    actor_user_id=actor_user_id,
                    target_type="user",
                    target_id=str(user_id),
                    details={
                        "role": account.role,
                        "via": "cli" if actor_user_id is None else "admin",
                    },
                ),
                self._now(),
            )
        return user_id
