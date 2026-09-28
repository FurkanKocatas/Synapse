"""Tenant and account creation for the installer and operators (``synapse tenant|user ...``).

The first administrator is created here, on the machine, never through a web endpoint that
would be open until someone uses it (ADR 0006).
"""

import asyncio
import getpass
import uuid
from datetime import timedelta
from pathlib import Path

from synapse.identity.public import (
    IdentityService,
    NewAccount,
    Role,
    SessionPolicy,
    TotpCipher,
)
from synapse.kernel.config import Settings
from synapse.kernel.database import Database
from synapse.kernel.secrets import read_key, read_secret


class CommandError(RuntimeError):
    """A problem the operator can fix; printed without a traceback."""


async def _create_tenant(
    settings: Settings, slug: str, name: str, tenant_id: uuid.UUID | None, *, if_missing: bool
) -> uuid.UUID:
    database = Database(settings.database(application_name="synapse-cli"), max_size=1)
    await database.open()
    try:
        tenant_id = tenant_id or uuid.uuid4()
        async with database.tenant_transaction(tenant_id) as connection:
            if if_missing:
                cursor = await connection.execute(
                    "SELECT slug FROM tenants WHERE id = %s", (tenant_id,)
                )
                existing = await cursor.fetchone()
                if existing is not None:
                    if existing[0] != slug:
                        raise CommandError(
                            f"tenant {tenant_id} exists with slug {existing[0]!r}, not {slug!r}"
                        )
                    return tenant_id
            await connection.execute(
                "INSERT INTO tenants (id, slug, name) VALUES (%s, %s, %s)", (tenant_id, slug, name)
            )
        return tenant_id
    finally:
        await database.close()


async def _active_admins(settings: Settings) -> int:
    if settings.tenant_id is None:
        raise CommandError("SYNAPSE_TENANT_ID is not set")
    database = Database(settings.database(application_name="synapse-cli"), max_size=1)
    await database.open()
    try:
        async with database.tenant_transaction(settings.tenant_id) as connection:
            cursor = await connection.execute(
                "SELECT count(*) FROM users WHERE role = 'admin' AND status = 'active'"
            )
            row = await cursor.fetchone()
            return int(row[0]) if row else 0
    finally:
        await database.close()


def active_admins(settings: Settings) -> int:
    """How many active administrators the tenant has; the installer creates the first one."""
    return asyncio.run(_active_admins(settings))


def create_tenant(
    settings: Settings,
    slug: str,
    name: str,
    *,
    tenant_id: uuid.UUID | None = None,
    if_missing: bool = False,
) -> uuid.UUID:
    """Create a tenant. With ``if_missing``, an existing tenant with this ID and slug is fine."""
    return asyncio.run(_create_tenant(settings, slug, name, tenant_id, if_missing=if_missing))


def read_new_password(password_file: Path | None) -> str:
    if password_file is not None:
        return read_secret(password_file)
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        raise CommandError("passwords do not match")
    return first


async def _create_user(
    settings: Settings, *, email: str, display_name: str, role: Role, locale: str, password: str
) -> uuid.UUID:
    if settings.tenant_id is None:
        raise CommandError("SYNAPSE_TENANT_ID is not set")
    database = Database(settings.database(application_name="synapse-cli"), max_size=1)
    await database.open()
    try:
        service = IdentityService(
            database,
            tenant_id=settings.tenant_id,
            csrf_key=read_key(settings.csrf_key_file),
            totp_cipher=TotpCipher(read_key(settings.totp_key_file)),
            policy=SessionPolicy(
                absolute_lifetime=timedelta(hours=settings.session_absolute_hours)
            ),
        )
        return await service.create_user(
            NewAccount(
                email=email, display_name=display_name, role=role, password=password, locale=locale
            )
        )
    finally:
        await database.close()


def create_user(
    settings: Settings, *, email: str, display_name: str, role: Role, locale: str, password: str
) -> uuid.UUID:
    return asyncio.run(
        _create_user(
            settings,
            email=email,
            display_name=display_name,
            role=role,
            locale=locale,
            password=password,
        )
    )
