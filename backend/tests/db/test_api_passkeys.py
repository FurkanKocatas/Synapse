"""Passkeys end to end, with a software authenticator and the real WebAuthn verification."""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from synapse import accounts_cli
from synapse.api.app import create_app
from synapse.api.deps import CLIENT_HEADER, CSRF_HEADER
from synapse.identity.public import Role
from synapse.kernel.config import Settings
from tests.db.conftest import TestDatabase
from tests.soft_authenticator import SoftAuthenticator

PASSWORD = "a sufficiently long passphrase"
ORIGIN = "https://synapse.test"


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
        public_url=ORIGIN,
    )
    tenant_id = accounts_cli.create_tenant(base, f"pk-{uuid.uuid4().hex[:8]}", "Passkey tests")
    return base.model_copy(update={"tenant_id": tenant_id})


@pytest.fixture
def clients() -> Iterator[list[TestClient]]:
    opened: list[TestClient] = []
    yield opened
    for client in opened:
        client.__exit__(None, None, None)


def new_user(settings: Settings, role: Role = "member") -> str:
    email = f"{role}-{uuid.uuid4().hex[:8]}@example.org"
    accounts_cli.create_user(
        settings,
        email=email,
        display_name="Passkey User",
        role=role,
        locale="en",
        password=PASSWORD,
    )
    return email


def sign_in(
    settings: Settings, email: str, clients: list[TestClient]
) -> tuple[TestClient, dict[str, Any]]:
    client = TestClient(create_app(settings), base_url="https://testserver")
    client.__enter__()
    clients.append(client)
    body = client.post(
        "/api/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={CLIENT_HEADER: "web"},
    ).json()
    client.headers[CSRF_HEADER] = body["csrf_token"]
    return client, body


def register(client: TestClient, authenticator: SoftAuthenticator, name: str = "Laptop") -> Any:
    options = client.post("/api/auth/passkeys/registration-options").json()
    return client.post(
        "/api/auth/passkeys", json={"credential": authenticator.create(options), "name": name}
    )


def authenticator() -> SoftAuthenticator:
    return SoftAuthenticator(origin=ORIGIN, rp_id="synapse.test")


def test_a_member_registers_a_passkey_and_signs_in_with_it(
    settings: Settings, clients: list[TestClient]
) -> None:
    email = new_user(settings)
    device = authenticator()
    client, _ = sign_in(settings, email, clients)
    options = client.post("/api/auth/passkeys/registration-options").json()
    assert options["rp"] == {"id": "synapse.test", "name": "Synapse"}
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert options["attestation"] == "none"
    registered = client.post(
        "/api/auth/passkeys", json={"credential": device.create(options), "name": "Laptop"}
    )
    assert registered.status_code == 201, registered.json()
    assert len(registered.json()["recovery_codes"]) == 10  # the account's first second factor
    assert registered.json()["session"] is None  # already full
    assert [p["name"] for p in client.get("/api/account/passkeys").json()] == ["Laptop"]

    again, body = sign_in(settings, email, clients)
    assert body["auth_level"] == "pending_mfa"
    assert again.get("/api/auth/session").json()["second_factors"] == ["passkey"]
    challenge = again.post("/api/auth/mfa/passkey/options").json()
    assert challenge["userVerification"] == "required"
    done = again.post("/api/auth/mfa/passkey", json={"credential": device.get(challenge)})
    assert done.json()["auth_level"] == "full", done.json()
    assert again.get("/api/auth/session").json()["user"]["email"] == email
    used = client.get("/api/account/passkeys").json()[0]
    assert used["last_used_at"] is not None


def test_a_response_counts_only_for_the_session_that_asked(
    settings: Settings, clients: list[TestClient]
) -> None:
    email = new_user(settings)
    device = authenticator()
    register(sign_in(settings, email, clients)[0], device)

    first, _ = sign_in(settings, email, clients)
    assertion = device.get(first.post("/api/auth/mfa/passkey/options").json())
    second, _ = sign_in(settings, email, clients)
    second.post("/api/auth/mfa/passkey/options")
    # Another session's challenge does not make a captured response valid here.
    assert second.post("/api/auth/mfa/passkey", json={"credential": assertion}).status_code == 401
    assert first.post("/api/auth/mfa/passkey", json={"credential": assertion}).status_code == 200


def test_a_counter_that_does_not_increase_is_rejected(
    settings: Settings, clients: list[TestClient]
) -> None:
    email = new_user(settings)
    device = authenticator()
    register(sign_in(settings, email, clients)[0], device)
    client, _ = sign_in(settings, email, clients)
    assert (
        client.post(
            "/api/auth/mfa/passkey",
            json={"credential": device.get(client.post("/api/auth/mfa/passkey/options").json())},
        ).status_code
        == 200
    )
    clone, _ = sign_in(settings, email, clients)
    device.sign_count -= 1  # a copy of the key that has not seen the last use
    options = clone.post("/api/auth/mfa/passkey/options").json()
    assert clone.post("/api/auth/mfa/passkey", json={"credential": device.get(options)}).json() == {
        "error": "passkey_failed"
    }


def test_responses_for_another_site_or_without_verification_are_rejected(
    settings: Settings, clients: list[TestClient]
) -> None:
    client, _ = sign_in(settings, new_user(settings), clients)
    options = client.post("/api/auth/passkeys/registration-options").json()
    phished = authenticator().create(options, origin="https://synapse-login.example")
    assert client.post("/api/auth/passkeys", json={"credential": phished, "name": "x"}).json() == {
        "error": "passkey_failed"
    }
    lazy = SoftAuthenticator(origin=ORIGIN, rp_id="synapse.test", user_verified=False)
    assert register(client, lazy).status_code == 400
    assert client.get("/api/account/passkeys").json() == []


def test_an_administrator_can_enroll_with_a_passkey(
    settings: Settings, clients: list[TestClient]
) -> None:
    client, body = sign_in(settings, new_user(settings, "admin"), clients)
    assert body["auth_level"] == "enroll_mfa"
    assert client.get("/api/account/passkeys").status_code == 403
    registered = register(client, authenticator()).json()
    assert registered["session"]["auth_level"] == "full"
    assert len(registered["recovery_codes"]) == 10
    client.headers[CSRF_HEADER] = registered["session"]["csrf_token"]
    assert client.get("/api/auth/session").json()["auth_level"] == "full"


def test_the_last_second_factor_of_an_administrator_stays(
    settings: Settings, clients: list[TestClient]
) -> None:
    client, _ = sign_in(settings, new_user(settings, "admin"), clients)
    registered = register(client, authenticator()).json()
    client.headers[CSRF_HEADER] = registered["session"]["csrf_token"]
    only = f"/api/account/passkeys/{registered['id']}"
    assert client.delete(only).json() == {"error": "last_second_factor"}
    second = register(client, authenticator(), "Phone").json()
    assert client.delete(only).status_code == 204
    assert [p["id"] for p in client.get("/api/account/passkeys").json()] == [second["id"]]


def test_passkeys_belong_to_their_owner(settings: Settings, clients: list[TestClient]) -> None:
    owner_device = authenticator()
    owner, _ = sign_in(settings, new_user(settings), clients)
    passkey = register(owner, owner_device).json()["id"]
    stranger, _ = sign_in(settings, new_user(settings), clients)
    register(stranger, authenticator())
    assert stranger.delete(f"/api/account/passkeys/{passkey}").status_code == 404

    # Someone else's authenticator is no good for an account's pending sign-in.
    victim_email = new_user(settings)
    register(sign_in(settings, victim_email, clients)[0], authenticator())
    attacker, _ = sign_in(settings, victim_email, clients)
    options = attacker.post("/api/auth/mfa/passkey/options").json()
    wrong = owner_device.get(options)
    assert attacker.post("/api/auth/mfa/passkey", json={"credential": wrong}).status_code == 401


def test_without_a_public_url_passkeys_are_unavailable(
    settings: Settings, clients: list[TestClient]
) -> None:
    email = new_user(settings)
    plain = settings.model_copy(update={"public_url": None})
    client, _ = sign_in(plain, email, clients)
    response = client.post("/api/auth/passkeys/registration-options")
    assert response.json() == {"error": "passkeys_unavailable"}


def test_each_challenge_is_consumed_by_the_first_attempt(
    settings: Settings, clients: list[TestClient]
) -> None:
    email = new_user(settings)
    device = authenticator()
    register(sign_in(settings, email, clients)[0], device)
    client, _ = sign_in(settings, email, clients)
    options = client.post("/api/auth/mfa/passkey/options").json()
    forged = device.get(options)
    forged["response"]["signature"] = forged["response"]["signature"][::-1]
    assert client.post("/api/auth/mfa/passkey", json={"credential": forged}).status_code == 401
    # A valid response to the same challenge now fails too: the first attempt used it up.
    genuine = device.get(options)
    assert client.post("/api/auth/mfa/passkey", json={"credential": genuine}).status_code == 401
    fresh = device.get(client.post("/api/auth/mfa/passkey/options").json())
    assert client.post("/api/auth/mfa/passkey", json={"credential": fresh}).status_code == 200


def test_an_administrator_reset_removes_passkeys(
    settings: Settings, clients: list[TestClient]
) -> None:
    admin, _ = sign_in(settings, new_user(settings, "admin"), clients)
    admin.headers[CSRF_HEADER] = register(admin, authenticator()).json()["session"]["csrf_token"]
    email = new_user(settings)
    register(sign_in(settings, email, clients)[0], authenticator())
    user = next(u for u in admin.get("/api/admin/users").json() if u["email"] == email)
    assert user["has_mfa"] is True
    assert admin.delete(f"/api/admin/users/{user['id']}/mfa").status_code == 204
    assert sign_in(settings, email, clients)[1]["auth_level"] == "full"
