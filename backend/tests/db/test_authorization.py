"""Who may use which document: accessible_documents() against the real database (ADR 0007)."""

import uuid
from dataclasses import dataclass

import psycopg
import pytest

from synapse.authz.checks import accessible_document_ids, can_access_document, role_has_permission
from synapse.kernel.database import Database


@dataclass
class World:
    tenant: uuid.UUID
    ayse: uuid.UUID  # member, in the "legal" group
    mehmet: uuid.UUID  # member, no group
    editor: uuid.UUID
    admin: uuid.UUID
    legal_group: uuid.UUID
    root: uuid.UUID  # collection
    child: uuid.UUID  # collection inside root
    other: uuid.UUID  # unrelated collection
    doc_root: uuid.UUID
    doc_child: uuid.UUID
    doc_other: uuid.UUID


async def insert(connection: psycopg.AsyncConnection, sql: str, *params: object) -> uuid.UUID:
    cursor = await connection.execute(sql + " RETURNING id", params)
    row = await cursor.fetchone()
    assert row is not None
    return uuid.UUID(str(row[0]))


@pytest.fixture
async def world(api_db: Database) -> World:
    tenant = uuid.uuid4()
    async with api_db.tenant_transaction(tenant) as c:
        await c.execute(
            "INSERT INTO tenants (id, slug, name) VALUES (%s, %s, 'Authz')",
            (tenant, f"z-{tenant.hex[:12]}"),
        )
        user = "INSERT INTO users (tenant_id, email, display_name, role) VALUES (%s, %s, %s, %s)"
        ayse = await insert(c, user, tenant, "ayse@example.org", "Ayşe", "member")
        mehmet = await insert(c, user, tenant, "mehmet@example.org", "Mehmet", "member")
        editor = await insert(c, user, tenant, "editor@example.org", "Editor", "editor")
        admin = await insert(c, user, tenant, "admin@example.org", "Admin", "admin")
        legal = await insert(
            c, "INSERT INTO groups (tenant_id, name) VALUES (%s, %s)", tenant, "legal"
        )
        await c.execute(
            "INSERT INTO group_members (tenant_id, group_id, user_id) VALUES (%s, %s, %s)",
            (tenant, legal, ayse),
        )
        collection = "INSERT INTO collections (tenant_id, parent_id, name) VALUES (%s, %s, %s)"
        root = await insert(c, collection, tenant, None, "Decisions")
        child = await insert(c, collection, tenant, root, "2026")
        other = await insert(c, collection, tenant, None, "HR")
        document = "INSERT INTO documents (tenant_id, collection_id, title) VALUES (%s, %s, %s)"
        doc_root = await insert(c, document, tenant, root, "Rules")
        doc_child = await insert(c, document, tenant, child, "Decision 2026/35")
        doc_other = await insert(c, document, tenant, other, "Salaries")
    return World(
        tenant,
        ayse,
        mehmet,
        editor,
        admin,
        legal,
        root,
        child,
        other,
        doc_root,
        doc_child,
        doc_other,
    )


@dataclass(frozen=True)
class Grant:
    table: str  # collection_grants or document_grants
    target: uuid.UUID
    principal: str  # user, group or role
    value: object
    permission: str


async def grant(db: Database, w: World, g: Grant) -> None:
    table, target, principal, value, permission = (
        g.table,
        g.target,
        g.principal,
        g.value,
        g.permission,
    )
    column = {"user": "principal_user_id", "group": "principal_group_id", "role": "principal_role"}
    target_column = "collection_id" if table == "collection_grants" else "document_id"
    async with db.tenant_transaction(w.tenant) as c:
        await c.execute(
            f"INSERT INTO {table} (tenant_id, {target_column}, {column[principal]}, permission) "  # noqa: S608
            "VALUES (%s, %s, %s, %s)",
            (w.tenant, target, value, permission),
        )


async def visible(
    db: Database, w: World, user: uuid.UUID, permission: str = "read"
) -> set[uuid.UUID]:
    async with db.tenant_transaction(w.tenant) as c:
        return await accessible_document_ids(c, user, permission)  # type: ignore[arg-type]


async def test_without_grants_nobody_sees_anything_not_even_admins(
    api_db: Database, world: World
) -> None:
    for user in (world.ayse, world.mehmet, world.editor, world.admin):
        assert await visible(api_db, world, user) == set()


async def test_a_collection_grant_covers_its_subcollections(api_db: Database, world: World) -> None:
    await grant(api_db, world, Grant("collection_grants", world.root, "user", world.mehmet, "read"))
    assert await visible(api_db, world, world.mehmet) == {world.doc_root, world.doc_child}
    assert await visible(api_db, world, world.mehmet, "write") == set()


async def test_group_grants_apply_to_members_only(api_db: Database, world: World) -> None:
    await grant(
        api_db, world, Grant("collection_grants", world.child, "group", world.legal_group, "read")
    )
    assert await visible(api_db, world, world.ayse) == {world.doc_child}
    assert await visible(api_db, world, world.mehmet) == set()


async def test_role_grants_and_permission_levels(api_db: Database, world: World) -> None:
    await grant(api_db, world, Grant("collection_grants", world.other, "role", "editor", "manage"))
    for permission in ("read", "write", "manage"):
        assert await visible(api_db, world, world.editor, permission) == {world.doc_other}
    assert await visible(api_db, world, world.ayse) == set()


async def test_a_document_grant_covers_that_document_only(api_db: Database, world: World) -> None:
    await grant(
        api_db, world, Grant("document_grants", world.doc_other, "user", world.ayse, "read")
    )
    assert await visible(api_db, world, world.ayse) == {world.doc_other}
    async with api_db.tenant_transaction(world.tenant) as c:
        assert await can_access_document(c, world.ayse, world.doc_other, "read")
        assert not await can_access_document(c, world.ayse, world.doc_other, "write")
        assert not await can_access_document(c, world.ayse, world.doc_root, "read")


async def test_deleted_documents_disappear_immediately(api_db: Database, world: World) -> None:
    await grant(api_db, world, Grant("collection_grants", world.root, "user", world.mehmet, "read"))
    async with api_db.tenant_transaction(world.tenant) as c:
        await c.execute("UPDATE documents SET deleted_at = now() WHERE id = %s", (world.doc_child,))
    assert await visible(api_db, world, world.mehmet) == {world.doc_root}


async def test_disabled_users_see_nothing(api_db: Database, world: World) -> None:
    await grant(api_db, world, Grant("collection_grants", world.root, "user", world.mehmet, "read"))
    async with api_db.tenant_transaction(world.tenant) as c:
        await c.execute("UPDATE users SET status = 'disabled' WHERE id = %s", (world.mehmet,))
    assert await visible(api_db, world, world.mehmet) == set()


async def test_grants_cannot_point_into_another_tenant(api_db: Database, world: World) -> None:
    other_tenant_world_collection = world.root
    stranger = uuid.uuid4()
    async with api_db.tenant_transaction(stranger) as c:
        await c.execute(
            "INSERT INTO tenants (id, slug, name) VALUES (%s, %s, 'Other')",
            (stranger, f"s-{stranger.hex[:12]}"),
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        async with api_db.tenant_transaction(stranger) as c:
            await c.execute(
                "INSERT INTO collection_grants (tenant_id, collection_id, principal_role, "
                "permission) VALUES (%s, %s, 'member', 'read')",
                (stranger, other_tenant_world_collection),
            )


async def test_role_permission_catalogue(api_db: Database, world: World) -> None:
    async with api_db.tenant_transaction(world.tenant) as c:
        assert await role_has_permission(c, "admin", "users.manage")
        assert await role_has_permission(c, "auditor", "audit.read")
        assert not await role_has_permission(c, "admin", "audit.read")
        assert not await role_has_permission(c, "member", "users.manage")
