"""The sign-in API end to end: real database, real cookies, CSRF and TOTP."""

import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pyotp
import pytest
from fastapi.testclient import TestClient

from synapse import accounts_cli
from synapse.api.app import StartupError, create_app
from synapse.api.deps import CLIENT_HEADER, CSRF_HEADER, SESSION_COOKIE
from synapse.kernel.config import Settings
from tests.db.conftest import TestDatabase

PASSWORD = "a sufficiently long passphrase"
WEB = {CLIENT_HEADER: "web"}


@dataclass(frozen=True)
class Tenant:
    settings: Settings
    member: str
    admin: str


@pytest.fixture(scope="module")
def tenant(test_database: TestDatabase, tmp_path_factory: pytest.TempPathFactory) -> Tenant:
    connection = test_database.settings("synapse_api")
    base = Settings(
        db_host=connection.host,
        db_port=connection.port,
        db_name=connection.dbname,
        db_user=connection.user,
        db_password_file=connection.password_file,
        csrf_key_file=test_database.secrets_dir / "csrf_key",
        totp_key_file=test_database.secrets_dir / "totp_key",
        log_format="console",
    )
    tenant_id = accounts_cli.create_tenant(base, f"api-{uuid.uuid4().hex[:8]}", "API tests")
    settings = base.model_copy(update={"tenant_id": tenant_id})
    password_file: Path = tmp_path_factory.mktemp("pw") / "password"
    password_file.write_text(PASSWORD, encoding="utf-8")
    emails = {}
    for role in ("member", "admin"):
        emails[role] = f"{role}-{uuid.uuid4().hex[:6]}@example.org"
        accounts_cli.create_user(
            settings,
            email=emails[role],
            display_name=f"Test {role}",
            role=role,
            locale="en",
            password=accounts_cli.read_new_password(password_file),
        )
    return Tenant(settings=settings, member=emails["member"], admin=emails["admin"])


@pytest.fixture
def client(tenant: Tenant) -> Iterator[TestClient]:
    # https, because the session cookie is Secure and would not be sent back over http.
    with TestClient(create_app(tenant.settings), base_url="https://testserver") as test_client:
        yield test_client


def login(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"email": email, "password": password}, headers=WEB
    )
    assert response.status_code == 200, response.text
    body: dict[str, str] = response.json()
    return body


def test_ready_when_the_database_is_migrated(client: TestClient) -> None:
    assert client.get("/readyz").json()["status"] == "ok"


def test_login_requires_the_client_header(client: TestClient, tenant: Tenant) -> None:
    response = client.post("/api/auth/login", json={"email": tenant.member, "password": PASSWORD})
    assert response.status_code == 403
    assert response.json() == {"error": "client_header_missing"}


def test_member_login_sets_a_hardened_cookie(client: TestClient, tenant: Tenant) -> None:
    response = client.post(
        "/api/auth/login", json={"email": tenant.member, "password": PASSWORD}, headers=WEB
    )
    assert response.status_code == 200
    assert response.json()["auth_level"] == "full"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    for attribute in ("Secure", "HttpOnly", "SameSite=lax", "Path=/"):
        assert attribute in cookie
    assert "Domain" not in cookie
    # The session token travels only in the cookie, never in the body.
    assert client.cookies[SESSION_COOKIE] not in response.text

    session = client.get("/api/auth/session").json()
    assert session["user"]["email"] == tenant.member
    assert session["user"]["role"] == "member"


def test_bad_credentials_get_one_generic_answer(client: TestClient, tenant: Tenant) -> None:
    wrong = client.post(
        "/api/auth/login", json={"email": tenant.member, "password": "x" * 20}, headers=WEB
    )
    unknown = client.post(
        "/api/auth/login", json={"email": "ghost@example.org", "password": PASSWORD}, headers=WEB
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"error": "invalid_credentials"}


def test_state_changing_requests_need_the_csrf_token(client: TestClient, tenant: Tenant) -> None:
    body = login(client, tenant.member)
    assert client.post("/api/auth/logout").json() == {"error": "csrf_failed"}
    assert client.post("/api/auth/logout", headers={CSRF_HEADER: "0" * 64}).status_code == 403
    assert (
        client.post("/api/auth/logout", headers={CSRF_HEADER: body["csrf_token"]}).status_code
        == 204
    )
    assert client.get("/api/auth/session").status_code == 401


def test_repeated_failures_are_throttled_with_retry_after(client: TestClient) -> None:
    email = f"target-{uuid.uuid4().hex[:6]}@example.org"  # throttling works for unknown accounts
    for _ in range(5):
        client.post("/api/auth/login", json={"email": email, "password": "x" * 20}, headers=WEB)
    response = client.post(
        "/api/auth/login", json={"email": email, "password": "x" * 20}, headers=WEB
    )
    assert response.status_code == 429
    assert response.json() == {"error": "too_many_attempts"}
    assert int(response.headers["Retry-After"]) >= 1


def test_admin_enrolls_totp_then_signs_in_with_it(client: TestClient, tenant: Tenant) -> None:
    first = login(client, tenant.admin)
    assert first["auth_level"] == "enroll_mfa"
    session = client.get("/api/auth/session").json()
    assert session["user"] is None  # no account details before the second factor

    csrf = {CSRF_HEADER: first["csrf_token"]}
    assert client.post("/api/auth/mfa/verify", json={"code": "123456"}, headers=csrf).json() == {
        "error": "no_second_factor_pending"
    }
    enrollment = client.post("/api/auth/mfa/totp/enroll", headers=csrf).json()
    totp = pyotp.TOTP(enrollment["secret"])
    confirmed = client.post("/api/auth/mfa/totp/confirm", json={"code": totp.now()}, headers=csrf)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["auth_level"] == "full"
    assert len(confirmed.json()["recovery_codes"]) == 10

    # A second enrollment is refused once TOTP is confirmed.
    full_csrf = {CSRF_HEADER: confirmed.json()["csrf_token"]}
    assert client.post("/api/auth/mfa/totp/enroll", headers=full_csrf).json() == {
        "error": "totp_already_enrolled"
    }

    client.post("/api/auth/logout", headers=full_csrf)
    pending = login(client, tenant.admin)
    assert pending["auth_level"] == "pending_mfa"
    code = totp.at(int(time.time()) + 30)  # the next step; the current one is used
    verified = client.post(
        "/api/auth/mfa/verify", json={"code": code}, headers={CSRF_HEADER: pending["csrf_token"]}
    )
    assert verified.status_code == 200, verified.text
    assert client.get("/api/auth/session").json()["user"]["role"] == "admin"


def test_not_ready_when_the_database_is_unreachable(tenant: Tenant) -> None:
    with TestClient(create_app(tenant.settings), base_url="https://testserver") as test_client:
        assert test_client.portal is not None
        database = test_client.app.state.database  # type: ignore[attr-defined]
        test_client.portal.call(database.close)
        response = test_client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_the_api_refuses_to_start_without_a_tenant(tenant: Tenant) -> None:
    settings = tenant.settings.model_copy(update={"tenant_id": None})
    with pytest.raises(StartupError, match="SYNAPSE_TENANT_ID"), TestClient(create_app(settings)):
        pass


def test_enrollment_rejects_a_wrong_code(client: TestClient, tenant: Tenant) -> None:
    email = f"admin2-{uuid.uuid4().hex[:6]}@example.org"
    accounts_cli.create_user(
        tenant.settings,
        email=email,
        display_name="Second admin",
        role="admin",
        locale="tr",
        password=PASSWORD,
    )
    csrf = {CSRF_HEADER: login(client, email)["csrf_token"]}
    client.post("/api/auth/mfa/totp/enroll", headers=csrf)
    response = client.post("/api/auth/mfa/totp/confirm", json={"code": "000000"}, headers=csrf)
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_code"}


def test_audit_status_needs_the_audit_permission(client: TestClient, tenant: Tenant) -> None:
    login(client, tenant.member)
    assert client.get("/api/audit/status").json() == {"error": "forbidden"}

    auditor = f"auditor-{uuid.uuid4().hex[:6]}@example.org"
    accounts_cli.create_user(
        tenant.settings,
        email=auditor,
        display_name="Auditor",
        role="auditor",
        locale="en",
        password=PASSWORD,
    )
    client.cookies.clear()
    login(client, auditor)
    status = client.get("/api/audit/status").json()
    assert status["ok"] is True
    assert status["events_checked"] >= 1
