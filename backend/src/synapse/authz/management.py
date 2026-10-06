"""Managing groups, collections and grants on collections or single documents (ADR 0007).
Every change is audited (ADR 0008).

All functions run inside the caller's tenant transaction, so the change and its audit event
commit or roll back together. Database constraint errors become the typed errors below, which
the API maps to 404 and 409.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

import psycopg
from psycopg import AsyncConnection
from psycopg.rows import class_row

from synapse.audit import public as audit
from synapse.audit.public import AuditEvent
from synapse.authz.checks import DocumentPermission

PrincipalType = Literal["user", "group", "role"]
_PRINCIPAL_COLUMN = {
    "user": "principal_user_id",
    "group": "principal_group_id",
    "role": "principal_role",
}


# What a grant is on: its table and the column naming the collection or document.
GrantTarget = Literal["collection", "document"]
_GRANTS: dict[GrantTarget, tuple[str, str]] = {
    "collection": ("collection_grants", "collection_id"),
    "document": ("document_grants", "document_id"),
}


class NotFoundError(LookupError):
    """A referenced group, user, collection, document or grant does not exist in this tenant
    (a deleted document neither)."""


class ConflictError(ValueError):
    """The change conflicts with existing data (a duplicate name or membership)."""


@dataclass(frozen=True)
class Group:
    id: UUID
    name: str
    member_count: int


@dataclass(frozen=True)
class Collection:
    id: UUID
    parent_id: UUID | None
    name: str


@dataclass(frozen=True)
class Grant:
    id: UUID
    collection_id: UUID
    principal_type: PrincipalType
    principal: str
    permission: DocumentPermission


@dataclass(frozen=True)
class DocumentGrant:
    id: UUID
    document_id: UUID
    principal_type: PrincipalType
    principal: str
    permission: DocumentPermission


@dataclass(frozen=True)
class Actor:
    """Who makes the change, for the audit log and for automatic grants."""

    tenant_id: UUID
    user_id: UUID
    role: str
    ip: str | None
    now: datetime


async def _audit(connection: AsyncConnection, actor: Actor, event: AuditEvent) -> None:
    await audit.record(connection, actor.tenant_id, event, actor.now)


def _event(
    actor: Actor, action: str, target_type: str, target_id: object, **details: str
) -> AuditEvent:
    return AuditEvent(
        action,
        "success",
        actor_user_id=actor.user_id,
        actor_ip=actor.ip,
        target_type=target_type,
        target_id=str(target_id),
        details=details,
    )


async def _insert_returning_id(
    connection: AsyncConnection, statement: str, params: tuple[object, ...]
) -> UUID:
    try:
        async with connection.transaction():  # a savepoint, so the caller can go on after errors
            cursor = await connection.execute(statement + " RETURNING id", params)
            row = await cursor.fetchone()
    except psycopg.errors.UniqueViolation as error:
        raise ConflictError(str(error.diag.constraint_name)) from error
    except psycopg.errors.ForeignKeyViolation as error:
        raise NotFoundError(str(error.diag.constraint_name)) from error
    if row is None:  # pragma: no cover  (INSERT ... RETURNING always returns the row)
        raise RuntimeError("insert returned no row")
    return UUID(str(row[0]))


# Groups


async def list_groups(connection: AsyncConnection) -> list[Group]:
    async with connection.cursor(row_factory=class_row(Group)) as cursor:
        await cursor.execute(
            "SELECT g.id, g.name, count(m.user_id)::int AS member_count FROM groups g "
            "LEFT JOIN group_members m ON m.group_id = g.id GROUP BY g.id ORDER BY lower(g.name)"
        )
        return await cursor.fetchall()


@dataclass(frozen=True)
class Member:
    user_id: UUID
    display_name: str
    email: str


async def list_members(connection: AsyncConnection, group_id: UUID) -> list[Member]:
    exists = await connection.execute("SELECT 1 FROM groups WHERE id = %s", (group_id,))
    if await exists.fetchone() is None:
        raise NotFoundError("group")
    async with connection.cursor(row_factory=class_row(Member)) as cursor:
        await cursor.execute(
            "SELECT u.id AS user_id, u.display_name, u.email FROM group_members m "
            "JOIN users u ON u.tenant_id = m.tenant_id AND u.id = m.user_id "
            "WHERE m.group_id = %s ORDER BY lower(u.display_name)",
            (group_id,),
        )
        return await cursor.fetchall()


async def create_group(connection: AsyncConnection, actor: Actor, name: str) -> UUID:
    group_id = await _insert_returning_id(
        connection, "INSERT INTO groups (tenant_id, name) VALUES (%s, %s)", (actor.tenant_id, name)
    )
    await _audit(
        connection, actor, _event(actor, "authz.group.create", "group", group_id, name=name)
    )
    return group_id


async def add_member(
    connection: AsyncConnection, actor: Actor, group_id: UUID, user_id: UUID
) -> None:
    try:
        async with connection.transaction():
            await connection.execute(
                "INSERT INTO group_members (tenant_id, group_id, user_id) VALUES (%s, %s, %s)",
                (actor.tenant_id, group_id, user_id),
            )
    except psycopg.errors.UniqueViolation as error:
        raise ConflictError("already a member") from error
    except psycopg.errors.ForeignKeyViolation as error:
        raise NotFoundError(str(error.diag.constraint_name)) from error
    await _audit(
        connection,
        actor,
        _event(actor, "authz.group.member_add", "group", group_id, user_id=str(user_id)),
    )


async def remove_member(
    connection: AsyncConnection, actor: Actor, group_id: UUID, user_id: UUID
) -> None:
    cursor = await connection.execute(
        "DELETE FROM group_members WHERE group_id = %s AND user_id = %s", (group_id, user_id)
    )
    if cursor.rowcount == 0:
        raise NotFoundError("membership")
    await _audit(
        connection,
        actor,
        _event(actor, "authz.group.member_remove", "group", group_id, user_id=str(user_id)),
    )


# Collections


async def list_collections(connection: AsyncConnection, actor: Actor) -> list[Collection]:
    """Every collection, for an administrator. Anyone else sees those they manage, the only
    ones they may create collections in: the names of the others are not theirs to read."""
    query = "SELECT id, parent_id, name FROM collections "
    values: tuple[UUID, ...] = ()
    if actor.role != "admin":
        query += "WHERE id IN (SELECT collection_id FROM accessible_collections(%s, 'manage')) "
        values = (actor.user_id,)
    async with connection.cursor(row_factory=class_row(Collection)) as cursor:
        await cursor.execute(query + "ORDER BY lower(name)", values)
        return await cursor.fetchall()


async def _manages(connection: AsyncConnection, user_id: UUID, collection_id: UUID) -> bool:
    cursor = await connection.execute(
        "SELECT EXISTS (SELECT 1 FROM accessible_collections(%s, 'manage') "
        "WHERE collection_id = %s)",
        (user_id, collection_id),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


async def create_collection(
    connection: AsyncConnection, actor: Actor, name: str, parent_id: UUID | None
) -> UUID:
    """Create a collection. Its creator gets ``manage`` on it, unless the creator is an admin.

    Admins manage permissions but, like everyone else, read documents only through grants
    (ADR 0007); an editor who creates a collection needs to be able to use it. Anyone but an
    admin needs ``manage`` on the parent: otherwise a parent they cannot see is "not found".
    """
    if (
        parent_id is not None
        and actor.role != "admin"
        and not await _manages(connection, actor.user_id, parent_id)
    ):
        raise NotFoundError("collection")
    collection_id = await _insert_returning_id(
        connection,
        "INSERT INTO collections (tenant_id, parent_id, name, created_by) VALUES (%s, %s, %s, %s)",
        (actor.tenant_id, parent_id, name, actor.user_id),
    )
    details = {"name": name, "parent_id": str(parent_id) if parent_id else ""}
    await _audit(
        connection,
        actor,
        _event(actor, "authz.collection.create", "collection", collection_id, **details),
    )
    if actor.role != "admin":
        await add_grant(connection, actor, collection_id, "user", str(actor.user_id), "manage")
    return collection_id


# Grants


_PRINCIPAL = (
    "CASE WHEN principal_user_id IS NOT NULL THEN 'user' "
    "     WHEN principal_group_id IS NOT NULL THEN 'group' ELSE 'role' END AS principal_type, "
    "coalesce(principal_user_id::text, principal_group_id::text, principal_role) AS principal"
)


async def list_grants(connection: AsyncConnection, collection_id: UUID) -> list[Grant]:
    async with connection.cursor(row_factory=class_row(Grant)) as cursor:
        await cursor.execute(
            f"SELECT id, collection_id, {_PRINCIPAL}, permission "  # noqa: S608  (constant)
            "FROM collection_grants WHERE collection_id = %s ORDER BY granted_at",
            (collection_id,),
        )
        return await cursor.fetchall()


async def list_document_grants(
    connection: AsyncConnection, document_id: UUID
) -> list[DocumentGrant]:
    """The grants on the document itself; those on its collections are listed with them."""
    await _live_document(connection, document_id)
    async with connection.cursor(row_factory=class_row(DocumentGrant)) as cursor:
        await cursor.execute(
            f"SELECT id, document_id, {_PRINCIPAL}, permission "  # noqa: S608  (constant)
            "FROM document_grants WHERE document_id = %s ORDER BY granted_at",
            (document_id,),
        )
        return await cursor.fetchall()


async def add_grant(  # noqa: PLR0913  (the grant's parts, as the API takes them)
    connection: AsyncConnection,
    actor: Actor,
    target_id: UUID,
    principal_type: PrincipalType,
    principal: str,
    permission: DocumentPermission,
    *,
    target: GrantTarget = "collection",
) -> UUID:
    """Grant ``permission`` on the collection ``target_id``, everything inside it included,
    or with ``target="document"`` on that one document."""
    if target == "document":
        await _live_document(connection, target_id)
    table, id_column = _GRANTS[target]
    column = _PRINCIPAL_COLUMN[principal_type]
    try:
        value: object = principal if principal_type == "role" else UUID(principal)
    except ValueError as error:
        raise NotFoundError("principal") from error
    grant_id = await _insert_returning_id(
        connection,
        f"INSERT INTO {table} (tenant_id, {id_column}, {column}, permission, "  # noqa: S608  (names from fixed maps)
        "granted_by) VALUES (%s, %s, %s, %s, %s)",
        (actor.tenant_id, target_id, value, permission, actor.user_id),
    )
    await _audit(
        connection,
        actor,
        _event(
            actor,
            "authz.grant.add",
            target,
            target_id,
            grant_id=str(grant_id),
            principal_type=principal_type,
            principal=principal,
            permission=permission,
        ),
    )
    return grant_id


async def remove_grant(connection: AsyncConnection, actor: Actor, grant_id: UUID) -> None:
    """Remove a grant, on a collection or on a document."""
    removed: tuple[GrantTarget, tuple[object, ...]] | None = None
    for each, (table, id_column) in _GRANTS.items():
        cursor = await connection.execute(
            f"DELETE FROM {table} WHERE id = %s RETURNING {id_column}, permission",  # noqa: S608  (names from a fixed map)
            (grant_id,),
        )
        if (found := await cursor.fetchone()) is not None:
            removed = (each, found)
            break
    if removed is None:
        raise NotFoundError("grant")
    target, row = removed
    await _audit(
        connection,
        actor,
        _event(
            actor,
            "authz.grant.remove",
            target,
            row[0],
            grant_id=str(grant_id),
            permission=str(row[1]),
        ),
    )


async def _live_document(connection: AsyncConnection, document_id: UUID) -> None:
    cursor = await connection.execute(
        "SELECT 1 FROM documents WHERE id = %s AND deleted_at IS NULL", (document_id,)
    )
    if await cursor.fetchone() is None:
        raise NotFoundError("document")
