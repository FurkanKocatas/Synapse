"""Audit retention against the real database (ADR 0022, migration 0028): what audit_prune()
removes and keeps, the anchor verification starts from, tampering after a prune, and who may
run it."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from synapse.audit.anchor import store_checkpoint, verify_checkpoints
from synapse.audit.browse import EventFilter, list_events
from synapse.audit.chain import AuditEvent, prune, record, text_digest, verify
from synapse.dbadmin import migrate
from synapse.dbadmin.roles import MIGRATOR, RETENTION, RUNTIME_ROLES
from synapse.kernel.config import Settings
from synapse.kernel.database import Database
from tests.db.conftest import TestDatabase
from tests.db.test_audit import admin, new_tenant  # noqa: F401  (admin is a fixture)

NOW = datetime.now(UTC)


@pytest.fixture
async def retention_db(test_database: TestDatabase) -> AsyncIterator[Database]:
    db = Database(test_database.settings(RETENTION.name), max_size=1)
    await db.open()
    yield db
    await db.close()


async def write(db: Database, tenant: uuid.UUID, days_ago: int, text: str | None = None) -> None:
    async with db.tenant_transaction(tenant) as connection:
        await record(
            connection,
            tenant,
            AuditEvent("test.event", "success", details={"days_ago": days_ago}, text=text),
            NOW - timedelta(days=days_ago),
        )


async def prune_now(retention_db: Database, tenant: uuid.UUID) -> dict[str, Any]:
    async with retention_db.system_transaction() as connection:
        return dict(await prune(connection, tenant))


async def test_old_events_go_from_the_start_with_an_anchor_and_old_texts_go_alone(
    api_db: Database, retention_db: Database
) -> None:
    tenant = await new_tenant(api_db)
    key = Ed25519PrivateKey.generate()
    for days in (400, 370):
        await write(api_db, tenant, days, text=f"{days} gün önceki soru")
    async with api_db.tenant_transaction(tenant) as connection:
        await store_checkpoint(connection, tenant, key, NOW)  # signs event 2, which will go
    for days in (200, 100, 10):
        await write(api_db, tenant, days, text=f"{days} gün önceki soru")
    async with api_db.tenant_transaction(tenant) as connection:
        await store_checkpoint(connection, tenant, key, NOW)  # signs event 5, which stays

    # Events a year old (365 days) go; a question's text after six months (183 days).
    assert await prune_now(retention_db, tenant) == {"events": 2, "texts": 3, "through_seq": 2}

    async with api_db.tenant_transaction(tenant) as connection:
        result = await verify(connection, tenant)
        kept = await verify_checkpoints(connection, tenant, key.public_key())
        events = await list_events(connection, tenant, EventFilter())
    assert (result.ok, result.events_checked, result.removed_through) == (True, 4, 2)
    assert (kept.problem, kept.checked) == (None, 1)
    by_seq = {event.seq: event for event in events}
    assert sorted(by_seq) == [3, 4, 5, 6]
    # The 200-day-old event stays without its text; its hash still names it.
    assert by_seq[3].text is None
    assert by_seq[3].details["text_sha256"] == text_digest("200 gün önceki soru")
    assert by_seq[4].text == "100 gün önceki soru"
    anchor = by_seq[6]
    assert (anchor.action, anchor.target_type, anchor.actor_user_id) == (
        "audit.prune",
        "audit",
        None,
    )
    assert {k: anchor.details[k] for k in ("count", "questions", "through_seq")} == {
        "count": 2,
        "questions": 3,
        "through_seq": 2,
    }

    # Nothing left past its period: nothing removed, nothing appended.
    assert await prune_now(retention_db, tenant) == {"events": 0, "texts": 0}
    async with api_db.tenant_transaction(tenant) as connection:
        assert (await verify(connection, tenant)).events_checked == 4


async def test_a_chain_wholly_past_its_period_keeps_only_its_anchor(
    api_db: Database, retention_db: Database
) -> None:
    tenant = await new_tenant(api_db)
    for days in (500, 450):
        await write(api_db, tenant, days)
    assert await prune_now(retention_db, tenant) == {"events": 2, "texts": 0, "through_seq": 2}
    async with api_db.tenant_transaction(tenant) as connection:
        result = await verify(connection, tenant)
    assert (result.ok, result.events_checked, result.removed_through) == (True, 1, 2)
    # An empty chain has nothing to prune.
    assert await prune_now(retention_db, await new_tenant(api_db)) == {"events": 0, "texts": 0}


async def test_tampering_after_a_prune_is_still_found(
    api_db: Database,
    retention_db: Database,
    admin: psycopg.AsyncConnection,  # noqa: F811  (the fixture)
) -> None:
    tenant = await new_tenant(api_db)
    for days in (400, 100, 50, 10):
        await write(api_db, tenant, days, text=f"{days}")
    await prune_now(retention_db, tenant)  # event 1 goes; 2, 3, 4 and the anchor (5) stay

    # A superuser removes the oldest kept event past the triggers: no anchor accounts for it.
    await admin.execute("SELECT set_config('synapse.audit_prune', 'on', true)")
    await admin.execute(
        "DELETE FROM synapse.audit_texts WHERE tenant_id = %s AND event_id = "
        "(SELECT id FROM synapse.audit_events WHERE tenant_id = %s AND seq = 2)",
        (tenant, tenant),
    )
    await admin.execute(
        "DELETE FROM synapse.audit_events WHERE tenant_id = %s AND seq = 2", (tenant,)
    )
    assert (await verify(admin, tenant)).problem == "sequence gap before event 3"
    await admin.rollback()

    # A kept text changed: the hash in its event no longer names it.
    await admin.execute("ALTER TABLE synapse.audit_texts DISABLE TRIGGER audit_texts_immutable")
    await admin.execute(
        "UPDATE synapse.audit_texts SET text = 'başka soru' WHERE tenant_id = %s AND event_id = "
        "(SELECT id FROM synapse.audit_events WHERE tenant_id = %s AND seq = 3)",
        (tenant, tenant),
    )
    assert (await verify(admin, tenant)).problem == "the text of event 3 was modified"


def test_only_the_retention_role_runs_the_prune_and_it_holds_nothing_else(
    test_database: TestDatabase,
) -> None:
    tenant = str(uuid.uuid4())
    # The migrator owns the function (and could disable the triggers anyway); no runtime role
    # may run it.
    for role in RUNTIME_ROLES:
        with (
            psycopg.connect(test_database.settings(role.name).conninfo()) as connection,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            connection.execute("SELECT audit_prune(%s)", (tenant,))
    with psycopg.connect(test_database.settings(RETENTION.name).conninfo()) as connection:
        for statement in (
            "SELECT * FROM audit_events",
            "DELETE FROM audit_events",
            "SELECT * FROM audit_settings",
            "UPDATE audit_settings SET keep_events_days = 90",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(statement)
            connection.rollback()


def test_the_periods_are_the_migrators_with_floors(test_database: TestDatabase) -> None:
    migrator = test_database.settings(MIGRATOR)
    with psycopg.connect(migrator.conninfo()) as connection:
        for events, questions in ((89, 30), (365, 29), (100, 200)):
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "UPDATE audit_settings SET keep_events_days = %s, keep_question_days = %s",
                    (events, questions),
                )
            connection.rollback()
    try:
        migrate.set_audit_periods(migrator, events_days=730, question_days=365)
        with psycopg.connect(migrator.conninfo()) as connection:
            row = connection.execute(
                "SELECT keep_events_days, keep_question_days FROM audit_settings"
            ).fetchone()
        assert row == (730, 365)
    finally:
        migrate.set_audit_periods(migrator, events_days=365, question_days=183)
    with pytest.raises(ValidationError):
        Settings(audit_keep_events_days=120, audit_keep_question_days=180)
    with pytest.raises(ValidationError):
        Settings(audit_keep_events_days=60)
