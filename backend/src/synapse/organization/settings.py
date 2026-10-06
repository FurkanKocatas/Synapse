"""The organisation's settings: choices an administrator makes for everyone (v1 scope).

One row per tenant (``tenant_settings``, migration 0025), validated here: an unknown key or a
value out of range is refused, never stored to be ignored later. Every change is audited with
the keys it changed and their new values. Other packages read the keys they own from the row
(identity: ``mfa_required_roles``), with the same defaults as here.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from synapse.audit import public as audit
from synapse.kernel.database import Database

# Roles that may be asked to use a second factor; administrators always must (ADR 0006).
OptionalMfaRole = Literal["editor", "member", "auditor"]


class OrganizationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Roles that must sign in with a second factor, besides administrators.
    mfa_required_roles: list[OptionalMfaRole] = Field(default_factory=list, max_length=3)


class SettingsService:
    def __init__(self, database: Database, *, tenant_id: UUID) -> None:
        self._db = database
        self._tenant_id = tenant_id

    async def get(self) -> OrganizationSettings:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            return await _read(connection)

    async def update(
        self, settings: OrganizationSettings, *, user_id: UUID, ip: str | None, now: datetime
    ) -> OrganizationSettings:
        """Store the settings; audited with what changed (nothing changed, nothing recorded)."""
        stored = settings.model_copy(
            update={"mfa_required_roles": sorted(set(settings.mfa_required_roles))}
        )
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            before = (await _read(connection, lock=True)).model_dump()
            after = stored.model_dump()
            changed: dict[str, Any] = {k: v for k, v in after.items() if before.get(k) != v}
            if not changed:
                return stored
            await connection.execute(
                "INSERT INTO tenant_settings (tenant_id, settings, updated_at, updated_by) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (tenant_id) DO UPDATE SET "
                "settings = EXCLUDED.settings, updated_at = EXCLUDED.updated_at, "
                "updated_by = EXCLUDED.updated_by",
                (self._tenant_id, Jsonb(after), now, user_id),
            )
            await audit.record(
                connection,
                self._tenant_id,
                audit.AuditEvent(
                    "org.settings.change",
                    "success",
                    actor_user_id=user_id,
                    actor_ip=ip,
                    details={"changed": changed},
                ),
                now,
            )
        return stored


_READ = "SELECT settings FROM tenant_settings"
_READ_FOR_UPDATE = _READ + " FOR UPDATE"


async def _read(connection: AsyncConnection, *, lock: bool = False) -> OrganizationSettings:
    cursor = await connection.execute(_READ_FOR_UPDATE if lock else _READ)
    row = await cursor.fetchone()
    return OrganizationSettings.model_validate(row[0] if row else {})
