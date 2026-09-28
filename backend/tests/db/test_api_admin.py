"""Administration API end to end: accounts, groups, collections and grants, all audited."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pyotp
import pytest
from fastapi.testclient import TestClient

from synapse import accounts_cli
from synapse.api.app import create_app
from synapse.api.deps import CLIENT_HEADER, CSRF_HEADER
from synapse.identity.public import Role
from synapse.kernel.config import Settings
from tests.db.conftest import TestDatabase

PASSWORD = "a sufficiently long passphrase"


@dataclass(frozen=True)
class Setup:
    settings: Settings
    admin: str
    member: str


@pytest.fixture(scope="module")
def setup(test_database: TestDatabase) -> Setup:
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
    tenant_id = accounts_cli.create_tenant(base, f"adm-{uuid.uuid4().hex[:8]}", "Admin tests")
    settings = base.model_copy(update={"tenant_id": tenant_id})
    roles: tuple[Role, ...] = ("admin", "member")
    emails = {role: f"{role}-{uuid.uuid4().hex[:6]}@example.org" for role in roles}
    for role, email in emails.items():
        accounts_cli.create_user(
            settings,
            email=email,
            display_name=role.title(),
            role=role,
            locale="en",
            password=PASSWORD,
        )
    return Setup(settings=settings, admin=emails["admin"], member=emails["member"])


def new_client(setup: Setup) -> TestClient:
    return TestClient(create_app(setup.settings), base_url="https://testserver")


@pytest.fixture
def member(setup: Setup) -> Iterator[TestClient]:
    with new_client(setup) as client:
        body = client.post(
            "/api/auth/login",
            json={"email": setup.member, "password": PASSWORD},
            headers={CLIENT_HEADER: "web"},
        ).json()
        client.headers[CSRF_HEADER] = body["csrf_token"]
        yield client


@pytest.fixture(scope="module")
def admin(setup: Setup) -> Iterator[TestClient]:
    """One fully signed-in admin for the whole module.

    Signing in again per test would need a fresh TOTP time step each time, and only the
    neighbouring steps are accepted, so the session is shared instead.
    """
    with new_client(setup) as client:
        body = client.post(
            "/api/auth/login",
            json={"email": setup.admin, "password": PASSWORD},
            headers={CLIENT_HEADER: "web"},
        ).json()
        assert body["auth_level"] == "enroll_mfa"
        csrf = {CSRF_HEADER: body["csrf_token"]}
        secret = client.post("/api/auth/mfa/totp/enroll", headers=csrf).json()["secret"]
        done = client.post(
            "/api/auth/mfa/totp/confirm", json={"code": pyotp.TOTP(secret).now()}, headers=csrf
        ).json()
        assert done["auth_level"] == "full", done
        client.headers[CSRF_HEADER] = done["csrf_token"]
        yield client


def test_members_cannot_administer(member: TestClient) -> None:
    for method, path in (
        ("GET", "/api/admin/users"),
        ("GET", "/api/admin/groups"),
        ("GET", "/api/admin/collections"),
    ):
        assert member.request(method, path).json() == {"error": "forbidden"}


def test_creating_accounts(admin: TestClient) -> None:
    email = f"new-{uuid.uuid4().hex[:6]}@example.org"
    body = {"email": email, "display_name": "Yeni Kişi", "role": "member", "password": PASSWORD}
    assert admin.post("/api/admin/users", json=body).status_code == 201
    assert admin.post("/api/admin/users", json=body).json() == {"error": "email_taken"}
    weak = body | {"email": f"w-{email}", "password": "short"}
    assert admin.post("/api/admin/users", json=weak).json() == {"error": "password_too_short"}
    listed = {user["email"]: user for user in admin.get("/api/admin/users").json()}
    assert listed[email]["display_name"] == "Yeni Kişi"
    assert listed[email]["has_mfa"] is False


def test_a_role_change_ends_the_accounts_sessions(admin: TestClient, setup: Setup) -> None:
    email = f"target-{uuid.uuid4().hex[:6]}@example.org"
    created = admin.post(
        "/api/admin/users",
        json={"email": email, "display_name": "Target", "role": "member", "password": PASSWORD},
    ).json()
    with new_client(setup) as target:
        target.post(
            "/api/auth/login",
            json={"email": email, "password": PASSWORD},
            headers={CLIENT_HEADER: "web"},
        )
        assert target.get("/api/auth/session").status_code == 200
        changed = admin.patch(f"/api/admin/users/{created['id']}", json={"role": "editor"})
        assert changed.json()["role"] == "editor"
        assert target.get("/api/auth/session").status_code == 401


def test_the_last_administrator_cannot_be_removed(admin: TestClient) -> None:
    me = next(user for user in admin.get("/api/admin/users").json() if user["role"] == "admin")
    response = admin.patch(f"/api/admin/users/{me['id']}", json={"role": "member"})
    assert response.status_code == 409
    assert response.json() == {"error": "last_administrator"}
    assert (
        admin.patch(f"/api/admin/users/{uuid.uuid4()}", json={"role": "member"}).status_code == 404
    )


def test_groups_and_membership(admin: TestClient) -> None:
    name = f"legal-{uuid.uuid4().hex[:6]}"
    group = admin.post("/api/admin/groups", json={"name": name}).json()["id"]
    assert admin.post("/api/admin/groups", json={"name": name}).status_code == 409
    user = admin.get("/api/admin/users").json()[0]["id"]
    members = f"/api/admin/groups/{group}/members"
    assert admin.post(members, json={"user_id": user}).status_code == 204
    assert admin.post(members, json={"user_id": user}).status_code == 409
    assert admin.post(members, json={"user_id": str(uuid.uuid4())}).status_code == 404
    counts = {g["name"]: g["member_count"] for g in admin.get("/api/admin/groups").json()}
    assert counts[name] == 1
    assert [m["user_id"] for m in admin.get(members).json()] == [user]
    assert admin.get(f"/api/admin/groups/{uuid.uuid4()}/members").status_code == 404
    assert admin.delete(f"{members}/{user}").status_code == 204
    assert admin.delete(f"{members}/{user}").status_code == 404


def test_collections_and_grants(admin: TestClient, setup: Setup) -> None:
    created = admin.post(
        "/api/admin/collections", json={"name": f"Kararlar {uuid.uuid4().hex[:4]}"}
    )
    collection = created.json()["id"]
    grants = f"/api/admin/collections/{collection}/grants"
    assert admin.get(grants).json() == []  # admins get no automatic access

    group = admin.post("/api/admin/groups", json={"name": f"g-{uuid.uuid4().hex[:6]}"}).json()["id"]
    granted = admin.post(
        grants, json={"principal_type": "group", "principal": group, "permission": "read"}
    )
    assert granted.status_code == 201
    listed = admin.get(grants).json()
    assert [(g["principal_type"], g["permission"]) for g in listed] == [("group", "read")]
    missing = {"principal_type": "user", "principal": str(uuid.uuid4()), "permission": "read"}
    assert admin.post(grants, json=missing).status_code == 404
    assert admin.delete(f"/api/admin/grants/{granted.json()['id']}").status_code == 204
    assert admin.delete(f"/api/admin/grants/{granted.json()['id']}").status_code == 404


def test_an_editor_can_use_the_collection_it_creates(admin: TestClient, setup: Setup) -> None:
    email = f"editor-{uuid.uuid4().hex[:6]}@example.org"
    admin.post(
        "/api/admin/users",
        json={"email": email, "display_name": "Editor", "role": "editor", "password": PASSWORD},
    )
    with new_client(setup) as editor:
        body = editor.post(
            "/api/auth/login",
            json={"email": email, "password": PASSWORD},
            headers={CLIENT_HEADER: "web"},
        ).json()
        editor.headers[CSRF_HEADER] = body["csrf_token"]
        collection = editor.post("/api/admin/collections", json={"name": f"E {email}"}).json()["id"]
    grants = admin.get(f"/api/admin/collections/{collection}/grants").json()
    assert [(g["principal_type"], g["permission"]) for g in grants] == [("user", "manage")]


def test_administration_is_audited(admin: TestClient, setup: Setup) -> None:
    admin.post("/api/admin/groups", json={"name": f"audited-{uuid.uuid4().hex[:6]}"})
    with new_client(setup) as auditor_client:
        email = f"auditor-{uuid.uuid4().hex[:6]}@example.org"
        admin.post(
            "/api/admin/users",
            json={
                "email": email,
                "display_name": "Auditor",
                "role": "auditor",
                "password": PASSWORD,
            },
        )
        auditor_client.post(
            "/api/auth/login",
            json={"email": email, "password": PASSWORD},
            headers={CLIENT_HEADER: "web"},
        )
        status = auditor_client.get("/api/audit/status").json()
    assert status["ok"] is True
    assert status["events_checked"] > 10


def sign_in(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    body: dict[str, str] = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers={CLIENT_HEADER: "web"},
    ).json()
    return body


def test_resetting_a_password(admin: TestClient, setup: Setup) -> None:
    email = f"forgot-{uuid.uuid4().hex[:6]}@example.org"
    user = admin.post(
        "/api/admin/users",
        json={"email": email, "display_name": "Forgot", "role": "member", "password": PASSWORD},
    ).json()["id"]
    reset = f"/api/admin/users/{user}/password"
    new_password = "a brand new long passphrase"
    with new_client(setup) as target:
        sign_in(target, email)
        assert admin.post(reset, json={"password": "short"}).json() == {
            "error": "password_too_short"
        }
        assert admin.post(reset, json={"password": new_password}).status_code == 204
        assert target.get("/api/auth/session").status_code == 401
    with new_client(setup) as target:
        assert sign_in(target, email).get("error") == "invalid_credentials"
    with new_client(setup) as target:
        assert sign_in(target, email, new_password)["auth_level"] == "full"
    missing = f"/api/admin/users/{uuid.uuid4()}/password"
    assert admin.post(missing, json={"password": new_password}).status_code == 404


def test_administrators_cannot_reset_their_own_account(admin: TestClient) -> None:
    me = admin.get("/api/auth/session").json()["user"]["id"]
    own = admin.post(f"/api/admin/users/{me}/password", json={"password": "x" * 20})
    assert own.json() == {"error": "own_account"}
    assert admin.delete(f"/api/admin/users/{me}/mfa").json() == {"error": "own_account"}


def test_resetting_a_second_factor(admin: TestClient, setup: Setup) -> None:
    email = f"lostphone-{uuid.uuid4().hex[:6]}@example.org"
    user = admin.post(
        "/api/admin/users",
        json={"email": email, "display_name": "Lost", "role": "admin", "password": PASSWORD},
    ).json()["id"]
    with new_client(setup) as target:
        csrf = {CSRF_HEADER: sign_in(target, email)["csrf_token"]}
        secret = target.post("/api/auth/mfa/totp/enroll", headers=csrf).json()["secret"]
        target.post(
            "/api/auth/mfa/totp/confirm", json={"code": pyotp.TOTP(secret).now()}, headers=csrf
        )
        assert target.get("/api/auth/session").json()["auth_level"] == "full"
        listed = {u["id"]: u for u in admin.get("/api/admin/users").json()}
        assert listed[user]["has_mfa"] is True

        assert admin.delete(f"/api/admin/users/{user}/mfa").status_code == 204
        assert target.get("/api/auth/session").status_code == 401
    listed = {u["id"]: u for u in admin.get("/api/admin/users").json()}
    assert listed[user]["has_mfa"] is False
    with new_client(setup) as target:
        assert sign_in(target, email)["auth_level"] == "enroll_mfa"
    assert admin.delete(f"/api/admin/users/{uuid.uuid4()}/mfa").status_code == 404
