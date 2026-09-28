"""The audit chain against the real database, including deliberate tampering."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import psycopg
import pytest

from synapse.audit.chain import AuditEvent, head, record, verify
from synapse.dbadmin.roles import MIGRATOR
from synapse.kernel.database import Database
from tests.db.conftest import TestDatabase


async def new_tenant(db: Database) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    async with db.tenant_transaction(tenant_id) as connection:
        await connection.execute(
            "INSERT INTO tenants (id, slug, name) VALUES (%s, %s, 'Audit')",
            (tenant_id, f"a-{tenant_id.hex[:12]}"),
        )
    return tenant_id


async def append(db: Database, tenant_id: uuid.UUID, count: int) -> None:
    for number in range(count):
        async with db.tenant_transaction(tenant_id) as connection:
            await record(
                connection,
                tenant_id,
                AuditEvent("test.event", "success", details={"n": number, "text": "Çağrı"}),
                datetime.now(UTC),
            )


@pytest.fixture
async def admin(test_database: TestDatabase) -> AsyncIterator[psycopg.AsyncConnection]:
    """A superuser connection inside a transaction that is always rolled back."""
    connection = await psycopg.AsyncConnection.connect(
        test_database.admin_conninfo, dbname=test_database.name
    )
    try:
        yield connection
    finally:
        await connection.rollback()
        await connection.close()


async def test_chain_grows_and_verifies(api_db: Database) -> None:
    tenant = await new_tenant(api_db)
    await append(api_db, tenant, 5)
    async with api_db.tenant_transaction(tenant) as connection:
        result = await verify(connection, tenant)
        latest = await head(connection, tenant)
    assert result.ok
    assert result.events_checked == 5
    assert latest is not None
    assert latest.seq == 5


async def test_concurrent_writers_keep_the_sequence_gapless(api_db: Database) -> None:
    tenant = await new_tenant(api_db)

    async def one(number: int) -> None:
        async with api_db.tenant_transaction(tenant) as connection:
            await record(
                connection,
                tenant,
                AuditEvent("test.concurrent", "success", details={"n": number}),
                datetime.now(UTC),
            )

    await asyncio.gather(*(one(number) for number in range(20)))
    async with api_db.tenant_transaction(tenant) as connection:
        result = await verify(connection, tenant)
    assert result.ok
    assert result.events_checked == 20


async def test_a_rolled_back_action_leaves_no_event(api_db: Database) -> None:
    tenant = await new_tenant(api_db)
    with pytest.raises(RuntimeError):
        async with api_db.tenant_transaction(tenant) as connection:
            await record(connection, tenant, AuditEvent("test.x", "success"), datetime.now(UTC))
            raise RuntimeError("the action failed after its event was written")
    async with api_db.tenant_transaction(tenant) as connection:
        assert await head(connection, tenant) is None


async def test_modified_content_is_detected(
    api_db: Database, admin: psycopg.AsyncConnection
) -> None:
    tenant = await new_tenant(api_db)
    await append(api_db, tenant, 4)
    await admin.execute("ALTER TABLE audit_events DISABLE TRIGGER audit_events_immutable")
    await admin.execute(
        "UPDATE audit_events SET details = '{\"n\": 99}' WHERE tenant_id = %s AND seq = 3",
        (tenant,),
    )
    result = await verify(admin, tenant)
    assert not result.ok
    assert result.problem == "event 3 was modified"
    assert result.events_checked == 2


async def test_a_deleted_event_is_detected(
    api_db: Database, admin: psycopg.AsyncConnection
) -> None:
    tenant = await new_tenant(api_db)
    await append(api_db, tenant, 4)
    await admin.execute("ALTER TABLE audit_events DISABLE TRIGGER audit_events_immutable")
    await admin.execute("DELETE FROM audit_events WHERE tenant_id = %s AND seq = 2", (tenant,))
    result = await verify(admin, tenant)
    assert result.problem == "sequence gap before event 3"


async def test_a_forged_hash_is_detected(api_db: Database, admin: psycopg.AsyncConnection) -> None:
    tenant = await new_tenant(api_db)
    await append(api_db, tenant, 3)
    await admin.execute("ALTER TABLE audit_events DISABLE TRIGGER audit_events_immutable")
    # Rewriting content and storing a matching-looking hash is not enough: the next event's
    # prev_hash still points at the original.
    await admin.execute(
        "UPDATE audit_events SET details = '{}', hash = sha256('forged'::bytea) "
        "WHERE tenant_id = %s AND seq = 2",
        (tenant,),
    )
    result = await verify(admin, tenant)
    assert not result.ok
    assert result.problem == "event 2 was modified"


def test_runtime_roles_cannot_change_events(test_database: TestDatabase) -> None:
    settings = test_database.settings("synapse_api")
    with psycopg.connect(settings.conninfo()) as connection:
        for statement in (
            "UPDATE audit_events SET outcome = 'success'",
            "DELETE FROM audit_events",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(statement)
            connection.rollback()


async def test_even_the_owner_cannot_change_events(
    api_db: Database, test_database: TestDatabase
) -> None:
    tenant = await new_tenant(api_db)
    await append(api_db, tenant, 1)
    settings = test_database.settings(MIGRATOR)
    with psycopg.connect(settings.conninfo()) as connection:
        for statement in (
            "UPDATE audit_events SET outcome = 'failure'",
            "DELETE FROM audit_events",
            "TRUNCATE audit_events",
        ):
            # The owner is also bound by forced row-level security, so it must select the
            # tenant first; otherwise it would see no rows and the test would prove nothing.
            connection.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant),))
            with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                connection.execute(statement)
            connection.rollback()
