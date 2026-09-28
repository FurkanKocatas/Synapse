"""Permission checks. Each runs inside the caller's tenant transaction.

Document access is decided only by the SQL function ``accessible_documents``, so search, chat
and document endpoints can never disagree about who may see what.
"""

from typing import Literal
from uuid import UUID

from psycopg import AsyncConnection

DocumentPermission = Literal["read", "write", "manage"]

# Role permissions known to the code. The database table decides which role has which; this
# list only lets typos in route declarations fail at import time instead of denying silently.
ROLE_PERMISSIONS = frozenset(
    {"users.manage", "groups.manage", "collections.create", "settings.manage", "audit.read"}
)


class UnknownPermissionError(ValueError):
    """A route asked for a permission that does not exist."""


def check_known(permission: str) -> str:
    if permission not in ROLE_PERMISSIONS:
        raise UnknownPermissionError(permission)
    return permission


async def role_has_permission(connection: AsyncConnection, role: str, permission: str) -> bool:
    cursor = await connection.execute(
        "SELECT EXISTS (SELECT 1 FROM role_permissions WHERE role = %s AND permission = %s)",
        (role, check_known(permission)),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


async def accessible_document_ids(
    connection: AsyncConnection, user_id: UUID, permission: DocumentPermission
) -> set[UUID]:
    cursor = await connection.execute(
        "SELECT document_id FROM accessible_documents(%s, %s)", (user_id, permission)
    )
    return {row[0] for row in await cursor.fetchall()}


async def can_access_document(
    connection: AsyncConnection, user_id: UUID, document_id: UUID, permission: DocumentPermission
) -> bool:
    cursor = await connection.execute(
        "SELECT EXISTS (SELECT 1 FROM accessible_documents(%s, %s) WHERE document_id = %s)",
        (user_id, permission, document_id),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])
