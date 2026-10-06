"""The organisation's settings: stored, validated, audited, and the second-factor policy they
set applied at sign-in, against the real database."""

import uuid
from collections.abc import Iterator

import pyotp
import pytest
from fastapi.testclient import TestClient

from synapse import accounts_cli
from synapse.api.app import create_app
from synapse.api.deps import CLIENT_HEADER, CSRF_HEADER
from synapse.identity.public import Role
from tests.db.conftest import TestDatabase
from tests.db.test_ingest_pipeline import PASSWORD, World, make_world


@pytest.fixture(scope="module")
def world(test_database: TestDatabase, tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    yield from make_world(test_database, tmp_path_factory)


def account(world: World, role: Role) -> str:
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.org"
    accounts_cli.create_user(
        world.api, email=email, display_name=role.title(), role=role, locale="en", password=PASSWORD
    )
    return email


def sign_in(client: TestClient, email: str) -> dict[str, str]:
    body: dict[str, str] = client.post(
        "/api/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={CLIENT_HEADER: "web"},
    ).json()
    return body


@pytest.fixture(scope="module")
def admin(world: World) -> Iterator[TestClient]:
    with TestClient(create_app(world.api), base_url="https://testserver") as client:
        body = sign_in(client, account(world, "admin"))
        csrf = {CSRF_HEADER: body["csrf_token"]}
        secret = client.post("/api/auth/mfa/totp/enroll", headers=csrf).json()["secret"]
        done = client.post(
            "/api/auth/mfa/totp/confirm", json={"code": pyotp.TOTP(secret).now()}, headers=csrf
        ).json()
        client.headers[CSRF_HEADER] = done["csrf_token"]
        yield client


def level_of(world: World, email: str) -> str:
    with TestClient(create_app(world.api), base_url="https://testserver") as client:
        return sign_in(client, email)["auth_level"]


def test_a_role_asked_for_a_second_factor_must_enrol_one(world: World, admin: TestClient) -> None:
    editor, member = account(world, "editor"), account(world, "member")
    assert admin.get("/api/admin/settings").json() == {"mfa_required_roles": []}
    assert (level_of(world, editor), level_of(world, member)) == ("full", "full")

    changed = admin.put("/api/admin/settings", json={"mfa_required_roles": ["editor", "editor"]})
    assert changed.status_code == 200, changed.json()
    assert changed.json() == {"mfa_required_roles": ["editor"]}
    assert admin.get("/api/admin/settings").json() == {"mfa_required_roles": ["editor"]}
    assert (level_of(world, editor), level_of(world, member)) == ("enroll_mfa", "full")

    events = world.db.execute(
        "SELECT details FROM synapse.audit_events WHERE tenant_id = %s "
        "AND action = 'org.settings.change' ORDER BY seq",
        (world.tenant_id,),
    ).fetchall()
    assert events == [({"changed": {"mfa_required_roles": ["editor"]}},)]
    # the same settings again change nothing, and record nothing
    admin.put("/api/admin/settings", json={"mfa_required_roles": ["editor"]})
    assert world.db.execute(
        "SELECT count(*) FROM synapse.audit_events WHERE tenant_id = %s "
        "AND action = 'org.settings.change'",
        (world.tenant_id,),
    ).fetchone() == (1,)

    admin.put("/api/admin/settings", json={"mfa_required_roles": []})
    assert level_of(world, editor) == "full"


def test_settings_are_checked_and_only_administrators_change_them(
    world: World, admin: TestClient
) -> None:
    # administrators always need a second factor; an unknown setting is refused, not ignored
    for wrong in (
        {"mfa_required_roles": ["admin"]},
        {"theme": "dark"},
        {"mfa_required_roles": "x"},
    ):
        assert admin.put("/api/admin/settings", json=wrong).status_code == 422, wrong
    with TestClient(create_app(world.api), base_url="https://testserver") as client:
        body = sign_in(client, account(world, "editor"))
        client.headers[CSRF_HEADER] = body["csrf_token"]
        assert client.get("/api/admin/settings").json() == {"error": "forbidden"}
        assert client.put("/api/admin/settings", json={}).json() == {"error": "forbidden"}
