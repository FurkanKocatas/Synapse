"""The auditor's endpoints: events filtered and paged, exports as CSV and signed JSON, the chain
and its checkpoints checked, against the real database."""

import asyncio
import csv
import io
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pyotp
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from synapse import accounts_cli
from synapse.api.app import create_app
from synapse.api.deps import CLIENT_HEADER, CSRF_HEADER
from synapse.audit import public as audit
from synapse.audit.chain import AuditEvent, event_hash
from synapse.kernel.config import Settings
from synapse.kernel.database import Database
from tests.db.conftest import TestDatabase
from tests.db.test_ingest_pipeline import PASSWORD, World, make_world


@pytest.fixture(scope="module")
def world(test_database: TestDatabase, tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    yield from make_world(test_database, tmp_path_factory)


@pytest.fixture(scope="module")
def settings(world: World, test_database: TestDatabase) -> Settings:
    return world.api.model_copy(
        update={"audit_signing_key_file": test_database.secrets_dir / "audit_signing_key"}
    )


def signed_in(settings: Settings, email: str) -> Iterator[TestClient]:
    """A client signed in as ``email``, enrolling the TOTP its role may require."""
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        body = client.post(
            "/api/auth/login",
            json={"email": email, "password": PASSWORD},
            headers={CLIENT_HEADER: "web"},
        ).json()
        if body["auth_level"] == "enroll_mfa":
            csrf = {CSRF_HEADER: body["csrf_token"]}
            secret = client.post("/api/auth/mfa/totp/enroll", headers=csrf).json()["secret"]
            body = client.post(
                "/api/auth/mfa/totp/confirm", json={"code": pyotp.TOTP(secret).now()}, headers=csrf
            ).json()
        assert body["auth_level"] == "full", body
        client.headers[CSRF_HEADER] = body["csrf_token"]
        yield client


@pytest.fixture(scope="module")
def auditor(world: World, settings: Settings) -> Iterator[TestClient]:
    email = f"auditor-{uuid.uuid4().hex[:6]}@example.org"
    accounts_cli.create_user(
        world.api,
        email=email,
        display_name="Auditor",
        role="auditor",
        locale="tr",
        password=PASSWORD,
    )
    yield from signed_in(settings, email)


def record(settings: Settings, world: World, *events: AuditEvent) -> None:
    async def write() -> None:
        database = Database(settings.database(application_name="synapse-tests"), max_size=1)
        await database.open()
        try:
            for event in events:
                async with database.tenant_transaction(world.tenant_id) as connection:
                    await audit.record(connection, world.tenant_id, event, datetime.now(UTC))
        finally:
            await database.close()

    asyncio.run(write())


def test_events_come_newest_first_filtered_and_in_pages(
    world: World, settings: Settings, auditor: TestClient
) -> None:
    actor = uuid.uuid4()
    record(
        settings,
        world,
        *(
            AuditEvent("test.page", "success", target_id=f"t{n}", details={"n": n})
            for n in range(5)
        ),
        AuditEvent("test.other", "failure", actor_ip="192.0.2.9", details={"reason": "x"}),
    )
    page = auditor.get("/api/audit/events", params={"action": "test.page", "limit": 2}).json()
    assert [e["target_id"] for e in page["events"]] == ["t4", "t3"]
    rest = auditor.get(
        "/api/audit/events",
        params={"action": "test.page", "limit": 2, "before": page["next_before"]},
    ).json()
    assert [e["target_id"] for e in rest["events"]] == ["t2", "t1"]
    family = auditor.get("/api/audit/events", params={"action": "test.", "limit": 50}).json()
    assert {e["action"] for e in family["events"]} == {"test.page", "test.other"}
    assert family["next_before"] is None
    failed = auditor.get("/api/audit/events", params={"outcome": "failure", "action": "test."})
    assert [e["actor_ip"] for e in failed.json()["events"]] == ["192.0.2.9"]
    nobody = auditor.get("/api/audit/events", params={"actor": str(actor)}).json()
    assert nobody["events"] == []
    # the hashes are not shown on the screen
    assert "hash" not in family["events"][0]
    assert auditor.get("/api/audit/events", params={"action": "Test;DROP"}).status_code == 422


def test_a_csv_export_opens_in_a_spreadsheet_and_is_audited(
    world: World, settings: Settings, auditor: TestClient
) -> None:
    record(settings, world, AuditEvent("test.csv", "success", details={"text": 'Çağrı; "x"'}))
    response = auditor.get("/api/audit/export", params={"format": "csv", "action": "test.csv"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    text = response.content.decode("utf-8")
    assert text.startswith("\ufeff")
    rows = list(csv.reader(io.StringIO(text.removeprefix("\ufeff")), delimiter=";"))
    assert rows[0] == list(audit.as_csv([]).removeprefix("\ufeff").strip().split(";"))
    assert len(rows) == 2
    assert json.loads(rows[1][rows[0].index("details")]) == {"text": 'Çağrı; "x"'}
    exported = auditor.get(
        "/api/audit/events", params={"action": "audit.export", "limit": 1}
    ).json()["events"]
    assert exported[0]["details"] == {"format": "csv", "count": 1, "action": "test.csv"}


def test_a_signed_export_proves_itself_and_every_event(
    world: World, settings: Settings, auditor: TestClient, test_database: TestDatabase
) -> None:
    record(settings, world, AuditEvent("test.signed", "success", target_type="t", details={"n": 1}))
    response = auditor.get("/api/audit/export", params={"format": "json", "action": "test."})
    assert response.status_code == 200
    document: dict[str, Any] = response.json()
    key = audit.load_signing_key(test_database.secrets_dir / "audit_signing_key").public_key()
    assert audit.export_is_authentic(document, key)
    assert document["manifest"]["count"] == len(document["events"]) > 0
    # every column is there: each event's hash can be computed again from the file
    for event in document["events"]:
        recomputed = event_hash(
            tenant_id=world.tenant_id,
            seq=event["seq"],
            event_id=uuid.UUID(event["id"]),
            occurred_at=datetime.fromisoformat(event["occurred_at"]),
            event=AuditEvent(
                event["action"],
                event["outcome"],
                actor_user_id=uuid.UUID(event["actor_user_id"]) if event["actor_user_id"] else None,
                actor_ip=event["actor_ip"],
                target_type=event["target_type"],
                target_id=event["target_id"],
                details=event["details"],
            ),
            schema_version=event["schema_version"],
            prev_hash=bytes.fromhex(event["prev_hash"]),
        )
        assert recomputed.hex() == event["hash"]
    # a changed event, or another key, no longer passes
    tampered = json.loads(json.dumps(document))
    tampered["events"][0]["details"] = {"n": 2}
    assert not audit.export_is_authentic(tampered, key)
    other = Ed25519PrivateKey.generate().public_key()
    assert not audit.export_is_authentic(document, other)


def test_the_status_compares_the_checkpoints(
    world: World, settings: Settings, auditor: TestClient, test_database: TestDatabase
) -> None:
    key = audit.load_signing_key(test_database.secrets_dir / "audit_signing_key")

    async def checkpoint() -> None:
        database = Database(settings.database(application_name="synapse-tests"), max_size=1)
        await database.open()
        try:
            async with database.tenant_transaction(world.tenant_id) as connection:
                await audit.store_checkpoint(connection, world.tenant_id, key, datetime.now(UTC))
        finally:
            await database.close()

    record(settings, world, AuditEvent("test.status", "success"))
    asyncio.run(checkpoint())
    body = auditor.get("/api/audit/status").json()
    assert body["ok"] is True
    assert body["checkpoints_checked"] >= 1


def test_an_export_too_wide_is_refused(world: World, settings: Settings) -> None:
    record(settings, world, AuditEvent("test.wide", "success"), AuditEvent("test.wide", "success"))

    async def export() -> None:
        database = Database(settings.database(application_name="synapse-tests"), max_size=1)
        await database.open()
        try:
            async with database.tenant_transaction(world.tenant_id) as connection:
                where = audit.EventFilter(action="test.wide")
                await audit.export_events(connection, world.tenant_id, where, limit=1)
        finally:
            await database.close()

    with pytest.raises(audit.TooManyEventsError):
        asyncio.run(export())


def test_others_may_not_read_the_audit_log(world: World, settings: Settings) -> None:
    for client in signed_in(settings, world.editor):
        assert client.get("/api/audit/events").json() == {"error": "forbidden"}
        assert client.get("/api/audit/export").json() == {"error": "forbidden"}
