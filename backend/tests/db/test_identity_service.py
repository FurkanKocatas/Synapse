"""Sign-in, sessions and second factors against the real database."""

import uuid
from datetime import UTC, datetime, timedelta

import pyotp
import pytest

from synapse.audit.chain import verify as audit_verify
from synapse.identity.passwords import PasswordPolicyError
from synapse.identity.service import (
    CurrentSession,
    IdentityService,
    IssuedSession,
    LoginRejected,
    NewAccount,
)
from synapse.identity.totp import TotpCipher
from synapse.kernel.database import Database

PASSWORD = "a sufficiently long passphrase"


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


async def new_tenant(db: Database) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    async with db.tenant_transaction(tenant_id) as connection:
        await connection.execute(
            "INSERT INTO tenants (id, slug, name) VALUES (%s, %s, 'Test')",
            (tenant_id, f"t-{tenant_id.hex[:12]}"),
        )
    return tenant_id


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def service(api_db: Database, clock: FakeClock) -> IdentityService:
    return IdentityService(
        api_db,
        tenant_id=await new_tenant(api_db),
        csrf_key=b"c" * 32,
        totp_cipher=TotpCipher(b"t" * 32),
        clock=clock,
    )


async def add_user(service: IdentityService, role: str = "member") -> str:
    email = f"user-{uuid.uuid4().hex[:8]}@example.org"
    await service.create_user(
        NewAccount(email=email, display_name="Test User", role=role, password=PASSWORD)  # type: ignore[arg-type]
    )
    return email


async def login(service: IdentityService, email: str, password: str = PASSWORD) -> IssuedSession:
    result = await service.login(email, password, client_ip="192.0.2.10", user_agent="tests")
    assert isinstance(result, IssuedSession), result
    return result


async def session_of(service: IdentityService, issued: IssuedSession) -> CurrentSession:
    session = await service.authenticate(issued.token)
    assert session is not None
    return session


async def test_password_policy_applies_on_creation(service: IdentityService) -> None:
    with pytest.raises(PasswordPolicyError):
        await service.create_user(
            NewAccount(
                email="short@example.org", display_name="Short", role="member", password="too short"
            )
        )


async def test_member_signs_in_to_a_full_session(service: IdentityService) -> None:
    email = await add_user(service)
    issued = await login(service, email.upper() + "  ")  # email is normalized
    assert issued.auth_level == "full"
    session = await session_of(service, issued)
    assert session.email == email
    assert service.csrf_matches(session, issued.csrf_token)
    assert not service.csrf_matches(session, "0" * 64)


async def test_wrong_password_and_unknown_account_look_the_same(service: IdentityService) -> None:
    email = await add_user(service)
    wrong = await service.login(email, "not the password at all", client_ip=None, user_agent=None)
    unknown = await service.login("nobody@example.org", PASSWORD, client_ip=None, user_agent=None)
    assert wrong == unknown == LoginRejected("invalid")


async def test_repeated_failures_back_off_then_recover(
    service: IdentityService, clock: FakeClock
) -> None:
    email = await add_user(service)
    for _ in range(5):
        await service.login(email, "wrong password here", client_ip=None, user_agent=None)
    throttled = await service.login(email, PASSWORD, client_ip=None, user_agent=None)
    assert isinstance(throttled, LoginRejected)
    assert throttled.reason == "throttled"
    clock.advance(timedelta(seconds=2))
    assert isinstance(
        await service.login(email, PASSWORD, client_ip=None, user_agent=None), IssuedSession
    )


async def test_sessions_expire_when_idle_and_at_their_absolute_limit(
    service: IdentityService, clock: FakeClock
) -> None:
    email = await add_user(service)
    idle = await login(service, email)
    clock.advance(timedelta(minutes=31))
    assert await service.authenticate(idle.token) is None

    active = await login(service, email)
    for _ in range(30):  # stay active: 30 x 29 minutes is more than the 12-hour limit
        clock.advance(timedelta(minutes=29))
        if await service.authenticate(active.token) is None:
            break
    else:
        pytest.fail("session outlived its absolute lifetime")
    # It ended because of the absolute limit, not earlier.
    assert clock.now >= active.expires_at


async def test_logout_revokes_the_session(service: IdentityService) -> None:
    issued = await login(service, await add_user(service))
    await service.logout(await session_of(service, issued))
    assert await service.authenticate(issued.token) is None


async def test_unknown_token_is_rejected(service: IdentityService) -> None:
    assert await service.authenticate("not-a-real-token") is None


async def test_accounts_are_invisible_to_other_tenants(
    service: IdentityService, api_db: Database, clock: FakeClock
) -> None:
    email = await add_user(service)
    other = IdentityService(
        api_db,
        tenant_id=await new_tenant(api_db),
        csrf_key=b"c" * 32,
        totp_cipher=TotpCipher(b"t" * 32),
        clock=clock,
    )
    assert await other.login(email, PASSWORD, client_ip=None, user_agent=None) == LoginRejected(
        "invalid"
    )
    issued = await login(service, email)
    assert await other.authenticate(issued.token) is None


async def enrolled_admin(service: IdentityService) -> tuple[str, str, list[str]]:
    """An admin with TOTP set up: returns email, TOTP secret and recovery codes."""
    email = await add_user(service, role="admin")
    issued = await login(service, email)
    assert issued.auth_level == "enroll_mfa"
    session = await session_of(service, issued)
    enrollment = await service.start_totp_enrollment(session)
    assert enrollment is not None
    completed = await service.confirm_totp_enrollment(
        session, pyotp.TOTP(enrollment.secret).now(), client_ip=None, user_agent=None
    )
    assert completed is not None
    assert completed.session.auth_level == "full"
    # The pre-enrollment token must stop working once the session is upgraded.
    assert await service.authenticate(issued.token) is None
    return email, enrollment.secret, completed.recovery_codes


async def test_admin_must_enroll_and_enrollment_upgrades_the_session(
    service: IdentityService,
) -> None:
    _, _, codes = await enrolled_admin(service)
    assert len(codes) == 10


async def test_second_factor_is_required_and_codes_cannot_be_replayed(
    service: IdentityService, clock: FakeClock
) -> None:
    email, secret, _ = await enrolled_admin(service)
    clock.advance(timedelta(seconds=31))  # the enrollment code's step is already used

    pending = await login(service, email)
    assert pending.auth_level == "pending_mfa"
    session = await session_of(service, pending)
    wrong = await service.complete_mfa(session, "000000", client_ip=None, user_agent=None)
    assert wrong == LoginRejected("invalid")

    code = pyotp.TOTP(secret).at(int(datetime.now(UTC).timestamp()) + 30)
    full = await service.complete_mfa(session, code, client_ip=None, user_agent=None)
    assert isinstance(full, IssuedSession)
    assert full.auth_level == "full"
    assert await service.authenticate(pending.token) is None

    second = await session_of(service, await login(service, email))
    replay = await service.complete_mfa(second, code, client_ip=None, user_agent=None)
    assert replay == LoginRejected("invalid")


async def test_recovery_code_works_exactly_once(service: IdentityService) -> None:
    email, _, codes = await enrolled_admin(service)
    first = await session_of(service, await login(service, email))
    assert isinstance(
        await service.complete_mfa(first, codes[0].lower(), client_ip=None, user_agent=None),
        IssuedSession,
    )
    second = await session_of(service, await login(service, email))
    assert await service.complete_mfa(second, codes[0], client_ip=None, user_agent=None) == (
        LoginRejected("invalid")
    )


async def test_confirmed_totp_cannot_be_replaced_through_enrollment(
    service: IdentityService,
) -> None:
    email, _secret, _ = await enrolled_admin(service)
    pending = await session_of(service, await login(service, email))
    assert await service.start_totp_enrollment(pending) is None  # wrong level


async def test_disabled_accounts_cannot_sign_in_and_lose_their_sessions(
    service: IdentityService, api_db: Database
) -> None:
    email = await add_user(service)
    issued = await login(service, email)
    async with api_db.tenant_transaction(service._tenant_id) as connection:
        await connection.execute("UPDATE users SET status = 'disabled' WHERE email = %s", (email,))
    assert await service.authenticate(issued.token) is None
    assert await service.login(email, PASSWORD, client_ip=None, user_agent=None) == (
        LoginRejected("invalid")
    )


async def test_second_factor_calls_require_the_right_session_level(
    service: IdentityService,
) -> None:
    member = await session_of(service, await login(service, await add_user(service)))
    assert await service.complete_mfa(member, "123456", client_ip=None, user_agent=None) == (
        LoginRejected("invalid")
    )


async def audit_actions(api_db: Database, tenant_id: uuid.UUID) -> list[tuple[str, str]]:
    async with api_db.tenant_transaction(tenant_id) as connection:
        cursor = await connection.execute("SELECT action, outcome FROM audit_events ORDER BY seq")
        rows = await cursor.fetchall()
        result = await audit_verify(connection, tenant_id)
    assert result.ok, result.problem
    return [(str(action), str(outcome)) for action, outcome in rows]


async def test_sign_in_events_are_audited(service: IdentityService, api_db: Database) -> None:
    email = await add_user(service)
    await service.login(email, "wrong password here!!", client_ip="192.0.2.7", user_agent=None)
    issued = await login(service, email)
    await service.logout(await session_of(service, issued))
    assert await audit_actions(api_db, service._tenant_id) == [
        ("identity.user.create", "success"),
        ("identity.login", "failure"),
        ("identity.login", "success"),
        ("identity.logout", "success"),
    ]
