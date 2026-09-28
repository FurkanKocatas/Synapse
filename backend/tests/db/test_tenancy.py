"""Row-level security isolates tenants, and a missing tenant sees nothing (ADR 0005)."""

import uuid

import psycopg
import pytest

from synapse.kernel.database import Database


async def create_tenant(db: Database, slug: str) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    async with db.tenant_transaction(tenant_id) as connection:
        await connection.execute(
            "INSERT INTO tenants (id, slug, name) VALUES (%s, %s, %s)", (tenant_id, slug, slug)
        )
    return tenant_id


async def visible_tenant_ids(db: Database, tenant_id: uuid.UUID) -> list[uuid.UUID]:
    async with db.tenant_transaction(tenant_id) as connection:
        cursor = await connection.execute("SELECT id FROM tenants")
        return [row[0] for row in await cursor.fetchall()]


async def test_a_tenant_sees_only_itself(api_db: Database) -> None:
    first = await create_tenant(api_db, f"first-{uuid.uuid4().hex[:8]}")
    second = await create_tenant(api_db, f"second-{uuid.uuid4().hex[:8]}")
    assert await visible_tenant_ids(api_db, first) == [first]
    assert await visible_tenant_ids(api_db, second) == [second]


async def test_without_a_tenant_nothing_is_visible(api_db: Database) -> None:
    await create_tenant(api_db, f"hidden-{uuid.uuid4().hex[:8]}")
    async with api_db.system_transaction() as connection:
        cursor = await connection.execute("SELECT count(*) FROM tenants")
        assert await cursor.fetchone() == (0,)


async def test_writing_another_tenants_row_is_rejected(api_db: Database) -> None:
    mine = uuid.uuid4()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with api_db.tenant_transaction(mine) as connection:
            await connection.execute(
                "INSERT INTO tenants (id, slug, name) VALUES (%s, 'intruder', 'x')", (uuid.uuid4(),)
            )


async def test_tenant_setting_does_not_leak_between_transactions(api_db: Database) -> None:
    tenant = await create_tenant(api_db, f"leak-{uuid.uuid4().hex[:8]}")
    await visible_tenant_ids(api_db, tenant)
    # The pool hands out the same connections again; the setting was transaction-local.
    for _ in range(8):
        async with api_db.system_transaction() as connection:
            cursor = await connection.execute("SELECT app_current_tenant()")
            assert await cursor.fetchone() == (None,)
