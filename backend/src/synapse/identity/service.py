"""Sign-in, sessions and second factors (ADR 0006).

Flow:

1. ``login`` checks the password. On success it creates a session whose level depends on the
   account: ``pending_mfa`` if a second factor is set up, ``enroll_mfa`` if the account is an
   admin without one (admins must have MFA), otherwise ``full``.
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

import structlog
from psycopg import AsyncConnection

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


@dataclass(frozen=True)
class EnrollmentCompleted:
    session: IssuedSession
    recovery_codes: list[str]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _email_subject(email: str) -> str:
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
        email_subject = _email_subject(email)
        subjects = [email_subject] + ([f"ip:{client_ip}"] if client_ip else [])
        now = self._now()

        async with self._db.tenant_transaction(self._tenant_id) as connection:
            blocked = await repository.blocked_subjects(connection, subjects, now)
            user = None if blocked else await repository.user_by_email(connection, email)
        if blocked:
            log.info("identity.login.throttled")
            return LoginRejected("throttled", retry_after=blocked - now)

        # Argon2 is deliberately slow: run it off the event loop and outside any transaction.
        stored_hash = user.password_hash if user else None
        valid = await asyncio.to_thread(passwords.verify_password, stored_hash, password)
        if user is None or not valid or user.status != "active":
            await self._record_failures(subjects, now)
            log.info("identity.login.failed", known_account=user is not None)
            return LoginRejected("invalid")

        async with self._db.tenant_transaction(self._tenant_id) as connection:
            await repository.clear_failures(connection, email_subject)
            if passwords.needs_rehash(user.password_hash or ""):
                new_hash = await asyncio.to_thread(passwords.hash_password, password)
                await repository.set_password_hash(connection, user.id, new_hash)
            credential = await repository.totp_for_user(connection, user.id)
            has_mfa = credential is not None and credential.confirmed_at is not None
            level: AuthLevel
            if has_mfa:
                level, lifetime = "pending_mfa", PENDING_MFA_LIFETIME
            elif user.role == "admin":
                level, lifetime = "enroll_mfa", ENROLL_MFA_LIFETIME
            else:
                level, lifetime = "full", self._policy.absolute_lifetime
            issued = await self._issue(
                connection, user.id, level, now + lifetime, client_ip, user_agent
            )
        log.info("identity.login.succeeded", user_id=str(user.id), auth_level=level)
        return issued

    async def _record_failures(self, subjects: list[str], now: datetime) -> None:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
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

    async def logout(self, session: CurrentSession) -> None:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            await repository.revoke_session(connection, session.session_id, "logout", self._now())

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
                return LoginRejected("throttled", retry_after=blocked - now)
            accepted = await self._accept_second_factor(connection, session.user_id, code)
            if accepted:
                await repository.clear_failures(connection, subject)
                await repository.revoke_session(connection, session.session_id, "upgraded", now)
                issued = await self._issue(
                    connection,
                    session.user_id,
                    "full",
                    now + self._policy.absolute_lifetime,
                    client_ip,
                    user_agent,
                )
        if not accepted:
            await self._record_failures([subject], now)
            log.info("identity.mfa.failed", user_id=str(session.user_id))
            return LoginRejected("invalid")
        log.info("identity.mfa.succeeded", user_id=str(session.user_id))
        return issued

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
                return None
            codes = recovery.new_codes()
            await repository.replace_recovery_codes(
                connection, self._tenant_id, session.user_id, [recovery.hash_code(c) for c in codes]
            )
            await repository.revoke_session(connection, session.session_id, "upgraded", now)
            issued = await self._issue(
                connection,
                session.user_id,
                "full",
                now + self._policy.absolute_lifetime,
                client_ip,
                user_agent,
            )
        log.info("identity.mfa.enrolled", user_id=str(session.user_id))
        return EnrollmentCompleted(session=issued, recovery_codes=codes)

    # Accounts

    async def create_user(
        self,
        *,
        email: str,
        display_name: str,
        role: Role,
        password: str | None,
        locale: str = "tr",
        context_words: tuple[str, ...] = (),
    ) -> UUID:
        """Create an account. The password must satisfy the policy for a single factor."""
        email = normalize_email(email)
        password_hash = None
        if password is not None:
            passwords.validate_password(
                password,
                mfa_enabled=False,
                context_words=[email.split("@")[0], display_name, *context_words],
            )
            password_hash = await asyncio.to_thread(passwords.hash_password, password)
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            return await repository.insert_user(
                connection,
                repository.NewUser(
                    tenant_id=self._tenant_id,
                    email=email,
                    display_name=display_name,
                    role=role,
                    locale=locale,
                    password_hash=password_hash,
                ),
            )
