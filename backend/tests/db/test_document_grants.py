"""Grants on single documents through the administration API, against the real database: one
document of a folder shown to someone who cannot read the folder, and taken back."""

import uuid
from collections.abc import Iterator

import pyotp
import pytest
from fastapi.testclient import TestClient

from synapse import accounts_cli
from synapse.api.app import create_app
from synapse.api.deps import CSRF_HEADER
from tests import knowledge_samples as samples
from tests.db.conftest import TestDatabase
from tests.db.test_ingest_pipeline import PASSWORD, World, make_world, signed_in_editor, upload
from tests.db.test_organization import account, sign_in


@pytest.fixture(scope="module")
def world(test_database: TestDatabase, tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    yield from make_world(test_database, tmp_path_factory)


@pytest.fixture
def editor(world: World) -> Iterator[TestClient]:
    yield from signed_in_editor(world)


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


def test_a_document_is_shared_alone_and_taken_back(
    world: World, admin: TestClient, editor: TestClient
) -> None:
    shared = upload(editor, samples.pdf("Karar 2026/35."), "paylasilan.pdf")
    other = editor.post(
        f"/api/collections/{shared['collection_id']}/documents",
        params={"filename": "diger.pdf"},
        content=samples.pdf("Karar 2026/36."),
    ).json()
    email = f"member-{uuid.uuid4().hex[:6]}@example.org"
    member_id = accounts_cli.create_user(
        world.api, email=email, display_name="M", role="member", locale="en", password=PASSWORD
    )

    grants = f"/api/admin/documents/{shared['id']}/grants"
    assert admin.get(grants).json() == []
    granted = admin.post(
        grants, json={"principal_type": "user", "principal": str(member_id), "permission": "read"}
    )
    assert granted.status_code == 201, granted.json()
    assert admin.get(grants).json() == [
        {
            "id": granted.json()["id"],
            "document_id": shared["id"],
            "principal_type": "user",
            "principal": str(member_id),
            "permission": "read",
        }
    ]

    with TestClient(create_app(world.api), base_url="https://testserver") as member:
        member.headers[CSRF_HEADER] = sign_in(member, email)["csrf_token"]
        # That one document, not the folder's other one, nor the folder itself.
        assert member.get(f"/api/documents/{shared['id']}/versions").status_code == 200
        assert member.get(f"/api/documents/{other['id']}/versions").status_code == 404
        assert admin.delete(f"/api/admin/grants/{granted.json()['id']}").status_code == 204
        assert member.get(f"/api/documents/{shared['id']}/versions").status_code == 404
    assert admin.delete(f"/api/admin/grants/{granted.json()['id']}").status_code == 404

    events = world.db.execute(
        "SELECT action, target_type, target_id FROM synapse.audit_events "
        "WHERE tenant_id = %s AND action LIKE 'authz.grant.%%' AND target_type = 'document' "
        "ORDER BY seq",
        (world.tenant_id,),
    ).fetchall()
    assert events == [
        ("authz.grant.add", "document", shared["id"]),
        ("authz.grant.remove", "document", shared["id"]),
    ]


def test_a_grant_needs_a_live_document_and_a_known_principal(
    admin: TestClient, editor: TestClient
) -> None:
    gone = upload(editor, samples.pdf("Silinecek."), "silinecek.pdf")
    assert editor.delete(f"/api/documents/{gone['id']}").status_code == 204
    read = {"principal_type": "role", "principal": "member", "permission": "read"}
    for document in (gone["id"], str(uuid.uuid4())):
        assert admin.post(f"/api/admin/documents/{document}/grants", json=read).status_code == 404
        assert admin.get(f"/api/admin/documents/{document}/grants").status_code == 404
    live = upload(editor, samples.pdf("Kalan."), "kalan.pdf")
    stranger = {"principal_type": "user", "principal": str(uuid.uuid4()), "permission": "read"}
    path = f"/api/admin/documents/{live['id']}/grants"
    assert admin.post(path, json=stranger).status_code == 404
    assert admin.post(path, json=read).status_code == 201
    # editors use what they were granted; granting is for administrators
    assert editor.post(path, json=read).json() == {"error": "forbidden"}
