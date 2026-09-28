"""The signed-in user's own account: password, sessions and language."""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from synapse import accounts_cli
from synapse.api.app import create_app
from synapse.api.deps import CLIENT_HEADER, CSRF_HEADER
from synapse.kernel.config import Settings
from tests.db.conftest import TestDatabase

PASSWORD = "a sufficiently long passphrase"
NEW_PASSWORD = "another quite long passphrase"


@pytest.fixture(scope="module")
def settings(test_database: TestDatabase) -> Settings:
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
    tenant_id = accounts_cli.create_tenant(base, f"acc-{uuid.uuid4().hex[:8]}", "Account tests")
    return base.model_copy(update={"tenant_id": tenant_id})


@pytest.fixture
def email(settings: Settings) -> str:
    address = f"user-{uuid.uuid4().hex[:8]}@example.org"
    accounts_cli.create_user(
        settings,
        email=address,
        display_name="Test User",
        role="member",
        locale="tr",
        password=PASSWORD,
    )
    return address


def signed_in(settings: Settings, email: str, password: str = PASSWORD) -> TestClient:
    client = TestClient(create_app(settings), base_url="https://testserver")
    client.__enter__()
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers={CLIENT_HEADER: "web"},
    )
    if response.status_code == 200:
        client.headers[CSRF_HEADER] = response.json()["csrf_token"]
    return client


@pytest.fixture
def clients() -> Iterator[list[TestClient]]:
    opened: list[TestClient] = []
    yield opened
    for client in opened:
        client.__exit__(None, None, None)


def test_changing_the_password_ends_other_sessions(
    settings: Settings, email: str, clients: list[TestClient]
) -> None:
    here = signed_in(settings, email)
    elsewhere = signed_in(settings, email)
    clients += [here, elsewhere]
    body = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    assert here.post("/api/account/password", json=body).status_code == 204
    assert here.get("/api/auth/session").status_code == 200
    assert elsewhere.get("/api/auth/session").status_code == 401

    old = signed_in(settings, email)
    new = signed_in(settings, email, NEW_PASSWORD)
    clients += [old, new]
    assert old.get("/api/auth/session").status_code == 401
    assert new.get("/api/auth/session").status_code == 200


def test_wrong_current_password_is_rejected_and_throttled(
    settings: Settings, email: str, clients: list[TestClient]
) -> None:
    client = signed_in(settings, email)
    clients.append(client)
    wrong = {"current_password": "not the right one at all", "new_password": NEW_PASSWORD}
    assert client.post("/api/account/password", json=wrong).json() == {"error": "wrong_password"}
    for _ in range(5):
        client.post("/api/account/password", json=wrong)
    response = client.post("/api/account/password", json=wrong)
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1


def test_the_new_password_must_meet_the_policy(
    settings: Settings, email: str, clients: list[TestClient]
) -> None:
    client = signed_in(settings, email)
    clients.append(client)
    body = {"current_password": PASSWORD, "new_password": "too short"}
    assert client.post("/api/account/password", json=body).json() == {"error": "password_too_short"}


def test_users_see_and_end_their_own_sessions_only(
    settings: Settings, email: str, clients: list[TestClient]
) -> None:
    here = signed_in(settings, email)
    other_device = signed_in(settings, email)
    clients += [here, other_device]
    sessions = here.get("/api/account/sessions").json()
    assert len(sessions) == 2
    assert sum(session["current"] for session in sessions) == 1
    other = next(session for session in sessions if not session["current"])
    assert here.delete(f"/api/account/sessions/{other['id']}").status_code == 204
    assert other_device.get("/api/auth/session").status_code == 401
    assert here.delete(f"/api/account/sessions/{other['id']}").status_code == 404

    stranger_email = f"stranger-{uuid.uuid4().hex[:6]}@example.org"
    accounts_cli.create_user(
        settings,
        email=stranger_email,
        display_name="Stranger",
        role="member",
        locale="tr",
        password=PASSWORD,
    )
    stranger = signed_in(settings, stranger_email)
    clients.append(stranger)
    stranger_session = stranger.get("/api/account/sessions").json()[0]["id"]
    assert here.delete(f"/api/account/sessions/{stranger_session}").status_code == 404
    assert stranger.get("/api/auth/session").status_code == 200


def test_the_language_preference_is_stored_on_the_account(
    settings: Settings, email: str, clients: list[TestClient]
) -> None:
    client = signed_in(settings, email)
    clients.append(client)
    assert client.put("/api/account/preferences", json={"locale": "en"}).status_code == 204
    assert client.get("/api/auth/session").json()["user"]["locale"] == "en"
    assert client.put("/api/account/preferences", json={"locale": "de"}).status_code == 422
