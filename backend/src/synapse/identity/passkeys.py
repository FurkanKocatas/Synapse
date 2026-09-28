"""Passkeys (WebAuthn) as a second factor next to TOTP (ADR 0006, docs/design/identity.md).

- Registration works from a full session (account page) and from an ``enroll_mfa`` session,
  so an administrator can meet the second-factor requirement with a passkey instead of an
  authenticator app. The first second factor of an account comes with recovery codes.
- Authentication raises a ``pending_mfa`` session to ``full``, like a TOTP code, with the same
  throttling subject.
- User verification (PIN or biometrics on the device) is required and no attestation is asked
  for: Synapse does not need to know the device model, and asking would reveal it.
- Each ceremony has a 32-byte random challenge bound to the session and its purpose. Taking it
  deletes it, so a signed response is accepted at most once.

Verification itself (signatures, origin, RP ID, counters, CBOR) is done by the ``webauthn``
package; this module handles storage, sessions, throttling and audit.
"""

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import structlog
import webauthn
from psycopg import AsyncConnection
from psycopg.rows import class_row
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from synapse.audit import public as audit
from synapse.audit.public import AuditEvent
from synapse.identity import repository, throttle
from synapse.identity.service import CurrentSession, IdentityService, IssuedSession, LoginRejected
from synapse.kernel.database import Database

log = structlog.get_logger(__name__)

CHALLENGE_LIFETIME = timedelta(minutes=5)
CEREMONY_TIMEOUT_MS = 120_000
Purpose = Literal["register", "authenticate"]


@dataclass(frozen=True)
class RelyingParty:
    """The site passkeys are bound to: the host name of the address users open."""

    id: str
    origin: str
    name: str = "Synapse"

    @classmethod
    def from_url(cls, url: str) -> RelyingParty:
        host = urlsplit(url).hostname
        if not host:
            raise ValueError(f"not an absolute URL: {url!r}")
        return cls(id=host, origin=url.rstrip("/"))


@dataclass(frozen=True)
class Passkey:
    id: UUID
    name: str
    backed_up: bool
    created_at: datetime
    last_used_at: datetime | None


@dataclass(frozen=True)
class PasskeyRegistered:
    passkey_id: UUID
    # Set when the registration completed the account's mandatory enrollment.
    session: IssuedSession | None
    # Set when this is the account's first second factor; shown to the user once.
    recovery_codes: list[str] | None


class PasskeyError(ValueError):
    """The ceremony failed: no challenge, an expired one, or a response that does not verify."""


class LastSecondFactorError(RuntimeError):
    """Removing this passkey would leave an account that must have a second factor without one."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _transports(values: object) -> list[AuthenticatorTransport]:
    known = {transport.value for transport in AuthenticatorTransport}
    if not isinstance(values, list):
        return []
    return [AuthenticatorTransport(v) for v in values if isinstance(v, str) and v in known]


class PasskeyService:
    def __init__(
        self,
        database: Database,
        *,
        tenant_id: UUID,
        identity: IdentityService,
        relying_party: RelyingParty,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._db = database
        self._tenant_id = tenant_id
        self._identity = identity
        self._rp = relying_party
        self._now = clock

    # Registration

    async def registration_options(self, session: CurrentSession) -> dict[str, Any]:
        if session.auth_level not in ("enroll_mfa", "full"):
            raise PasskeyError("wrong session level")
        challenge = secrets.token_bytes(32)
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            existing = await _credential_ids(connection, session.user_id)
            await self._store_challenge(connection, session, "register", challenge)
        options = webauthn.generate_registration_options(
            rp_id=self._rp.id,
            rp_name=self._rp.name,
            user_id=session.user_id.bytes,
            user_name=session.email,
            user_display_name=session.display_name,
            challenge=challenge,
            timeout=CEREMONY_TIMEOUT_MS,
            authenticator_selection=AuthenticatorSelectionCriteria(
                # Discoverable where possible, so passwordless sign-in can be added later
                # without asking everyone to register again.
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[PublicKeyCredentialDescriptor(id=c) for c in existing],
        )
        parsed: dict[str, Any] = json.loads(webauthn.options_to_json(options))
        return parsed

    async def register(
        self,
        session: CurrentSession,
        credential: dict[str, Any],
        name: str,
        *,
        client_ip: str | None,
        user_agent: str | None,
    ) -> PasskeyRegistered:
        now = self._now()
        # Taken in a transaction of its own, so that it is gone even if what follows fails.
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            challenge = await self._take_challenge(connection, session, "register", now)
        try:
            verified = webauthn.verify_registration_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=self._rp.id,
                expected_origin=self._rp.origin,
                require_user_verification=True,
            )
        except WebAuthnException as error:
            log.info("identity.passkey.register_rejected", reason=str(error))
            raise PasskeyError("registration did not verify") from error
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            first_factor = not await repository.has_second_factor(connection, session.user_id)
            response = credential.get("response")
            transports = _transports(
                response.get("transports") if isinstance(response, dict) else None
            )
            cursor = await connection.execute(
                "INSERT INTO passkeys (tenant_id, user_id, credential_id, public_key, sign_count, "
                "transports, backed_up, name, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (tenant_id, credential_id) DO NOTHING RETURNING id",
                (
                    self._tenant_id,
                    session.user_id,
                    verified.credential_id,
                    verified.credential_public_key,
                    verified.sign_count,
                    [t.value for t in transports],
                    verified.credential_backed_up,
                    name,
                    now,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                raise PasskeyError("this passkey is already registered")
            passkey_id: UUID = row[0]
            codes = (
                await self._identity.issue_recovery_codes(connection, session.user_id)
                if first_factor
                else None
            )
            issued = (
                await self._identity.upgrade_session(
                    connection, session, now, client_ip, user_agent
                )
                if session.auth_level == "enroll_mfa"
                else None
            )
            event = _passkey_event("identity.passkey.register", session, client_ip, passkey_id)
            await audit.record(
                connection,
                self._tenant_id,
                replace(event, details={"backed_up": verified.credential_backed_up}),
                now,
            )
        log.info("identity.passkey.registered", user_id=str(session.user_id))
        return PasskeyRegistered(passkey_id=passkey_id, session=issued, recovery_codes=codes)

    # Authentication

    async def authentication_options(self, session: CurrentSession) -> dict[str, Any]:
        if session.auth_level != "pending_mfa":
            raise PasskeyError("wrong session level")
        challenge = secrets.token_bytes(32)
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            allowed = await _credential_ids(connection, session.user_id)
            if not allowed:
                raise PasskeyError("the account has no passkey")
            await self._store_challenge(connection, session, "authenticate", challenge)
        options = webauthn.generate_authentication_options(
            rp_id=self._rp.id,
            challenge=challenge,
            timeout=CEREMONY_TIMEOUT_MS,
            allow_credentials=[PublicKeyCredentialDescriptor(id=c) for c in allowed],
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        parsed: dict[str, Any] = json.loads(webauthn.options_to_json(options))
        return parsed

    async def authenticate(
        self,
        session: CurrentSession,
        credential: dict[str, Any],
        *,
        client_ip: str | None,
        user_agent: str | None,
    ) -> IssuedSession | LoginRejected:
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
                        details={"method": "passkey", "reason": "throttled"},
                    ),
                    now,
                )
                return LoginRejected("throttled", retry_after=blocked - now)
            issued = await self._verify_assertion(
                connection, session, credential, now, client_ip, user_agent
            )
        if issued is None:
            await self._record_failure(subject, session, client_ip, now)
            return LoginRejected("invalid")
        log.info("identity.mfa.succeeded", user_id=str(session.user_id), method="passkey")
        return issued

    async def _verify_assertion(
        self,
        connection: AsyncConnection,
        session: CurrentSession,
        credential: dict[str, Any],
        now: datetime,
        client_ip: str | None,
        user_agent: str | None,
    ) -> IssuedSession | None:
        try:
            challenge = await self._take_challenge(connection, session, "authenticate", now)
            credential_id = base64url_to_bytes(str(credential.get("rawId", "")))
        except PasskeyError, ValueError:
            return None
        cursor = await connection.execute(
            "SELECT id, public_key, sign_count FROM passkeys "
            "WHERE user_id = %s AND credential_id = %s FOR UPDATE",
            (session.user_id, credential_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        passkey_id, public_key, sign_count = row
        try:
            verified = webauthn.verify_authentication_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=self._rp.id,
                expected_origin=self._rp.origin,
                credential_public_key=public_key,
                credential_current_sign_count=sign_count,
                require_user_verification=True,
            )
        except WebAuthnException as error:
            # A counter that did not increase lands here too: possibly a cloned authenticator.
            log.warning("identity.passkey.assertion_rejected", reason=str(error))
            return None
        await connection.execute(
            "UPDATE passkeys SET sign_count = %s, backed_up = %s, last_used_at = %s WHERE id = %s",
            (verified.new_sign_count, verified.credential_backed_up, now, passkey_id),
        )
        await repository.clear_failures(connection, f"mfa:{session.user_id}")
        issued = await self._identity.upgrade_session(
            connection, session, now, client_ip, user_agent
        )
        await audit.record(
            connection,
            self._tenant_id,
            AuditEvent(
                "identity.mfa.verify",
                "success",
                actor_user_id=session.user_id,
                actor_ip=client_ip,
                details={"method": "passkey"},
            ),
            now,
        )
        return issued

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
                    "identity.mfa.verify",
                    "failure",
                    actor_user_id=session.user_id,
                    actor_ip=client_ip,
                    details={"method": "passkey"},
                ),
                now,
            )

    # Management

    async def list_passkeys(self, session: CurrentSession) -> list[Passkey]:
        async with (
            self._db.tenant_transaction(self._tenant_id) as connection,
            connection.cursor(row_factory=class_row(Passkey)) as cursor,
        ):
            await cursor.execute(
                "SELECT id, name, backed_up, created_at, last_used_at FROM passkeys "
                "WHERE user_id = %s ORDER BY created_at",
                (session.user_id,),
            )
            return await cursor.fetchall()

    async def remove(
        self, session: CurrentSession, passkey_id: UUID, *, client_ip: str | None
    ) -> bool:
        """Remove one of the user's own passkeys; False if it is not theirs."""
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            cursor = await connection.execute(
                "DELETE FROM passkeys WHERE id = %s AND user_id = %s",
                (passkey_id, session.user_id),
            )
            if cursor.rowcount == 0:
                return False
            if session.role == "admin" and not await repository.has_second_factor(
                connection, session.user_id
            ):
                # Raising rolls the delete back.
                raise LastSecondFactorError("administrators must keep a second factor")
            event = _passkey_event("identity.passkey.remove", session, client_ip, passkey_id)
            await audit.record(connection, self._tenant_id, event, now)
        return True

    # Challenges

    async def _store_challenge(
        self,
        connection: AsyncConnection,
        session: CurrentSession,
        purpose: Purpose,
        challenge: bytes,
    ) -> None:
        await connection.execute(
            "INSERT INTO webauthn_challenges (tenant_id, session_id, purpose, challenge, "
            "expires_at) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (tenant_id, session_id, purpose) DO UPDATE "
            "SET challenge = EXCLUDED.challenge, expires_at = EXCLUDED.expires_at",
            (
                self._tenant_id,
                session.session_id,
                purpose,
                challenge,
                self._now() + CHALLENGE_LIFETIME,
            ),
        )

    async def _take_challenge(
        self,
        connection: AsyncConnection,
        session: CurrentSession,
        purpose: Purpose,
        now: datetime,
    ) -> bytes:
        cursor = await connection.execute(
            "DELETE FROM webauthn_challenges WHERE session_id = %s AND purpose = %s "
            "RETURNING challenge, expires_at",
            (session.session_id, purpose),
        )
        row = await cursor.fetchone()
        if row is None or row[1] <= now:
            raise PasskeyError("no challenge in progress")
        challenge: bytes = row[0]
        return challenge


async def _credential_ids(connection: AsyncConnection, user_id: UUID) -> list[bytes]:
    cursor = await connection.execute(
        "SELECT credential_id FROM passkeys WHERE user_id = %s", (user_id,)
    )
    return [row[0] for row in await cursor.fetchall()]


def _passkey_event(
    action: str, session: CurrentSession, client_ip: str | None, passkey_id: UUID
) -> AuditEvent:
    return AuditEvent(
        action,
        "success",
        actor_user_id=session.user_id,
        actor_ip=client_ip,
        target_type="passkey",
        target_id=str(passkey_id),
    )
