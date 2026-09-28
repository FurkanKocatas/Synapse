"""Managing groups, collections and grants (ADR 0007). Every change is audited (ADR 0008).

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


class NotFoundError(LookupError):
    """A referenced group, user, collection or grant does not exist in this tenant."""


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


async def list_collections(connection: AsyncConnection) -> list[Collection]:
    async with connection.cursor(row_factory=class_row(Collection)) as cursor:
        await cursor.execute("SELECT id, parent_id, name FROM collections ORDER BY lower(name)")
        return await cursor.fetchall()


async def create_collection(
    connection: AsyncConnection, actor: Actor, name: str, parent_id: UUID | None
) -> UUID:
    """Create a collection. Its creator gets ``manage`` on it, unless the creator is an admin.

    Admins manage permissions but, like everyone else, read documents only through grants
    (ADR 0007); an editor who creates a collection needs to be able to use it.
    """
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


async def list_grants(connection: AsyncConnection, collection_id: UUID) -> list[Grant]:
    async with connection.cursor(row_factory=class_row(Grant)) as cursor:
        await cursor.execute(
            "SELECT id, collection_id, "
            "CASE WHEN principal_user_id IS NOT NULL THEN 'user' "
            "     WHEN principal_group_id IS NOT NULL THEN 'group' ELSE 'role' END "
            "  AS principal_type, "
            "coalesce(principal_user_id::text, principal_group_id::text, principal_role) "
            "  AS principal, permission "
            "FROM collection_grants WHERE collection_id = %s ORDER BY granted_at",
            (collection_id,),
        )
        return await cursor.fetchall()


async def add_grant(
    connection: AsyncConnection,
    actor: Actor,
    collection_id: UUID,
    principal_type: PrincipalType,
    principal: str,
    permission: DocumentPermission,
) -> UUID:
    column = _PRINCIPAL_COLUMN[principal_type]
    try:
        value: object = principal if principal_type == "role" else UUID(principal)
    except ValueError as error:
        raise NotFoundError("principal") from error
    grant_id = await _insert_returning_id(
        connection,
        f"INSERT INTO collection_grants (tenant_id, collection_id, {column}, permission, "  # noqa: S608  (column from a fixed map)
        "granted_by) VALUES (%s, %s, %s, %s, %s)",
        (actor.tenant_id, collection_id, value, permission, actor.user_id),
    )
    await _audit(
        connection,
        actor,
        _event(
            actor,
            "authz.grant.add",
            "collection",
            collection_id,
            grant_id=str(grant_id),
            principal_type=principal_type,
            principal=principal,
            permission=permission,
        ),
    )
    return grant_id


async def remove_grant(connection: AsyncConnection, actor: Actor, grant_id: UUID) -> None:
    cursor = await connection.execute(
        "DELETE FROM collection_grants WHERE id = %s RETURNING collection_id, permission",
        (grant_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise NotFoundError("grant")
    await _audit(
        connection,
        actor,
        _event(
            actor,
            "authz.grant.remove",
            "collection",
            row[0],
            grant_id=str(grant_id),
            permission=str(row[1]),
        ),
    )
