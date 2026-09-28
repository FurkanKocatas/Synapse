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


async def _create_tenant(settings: Settings, slug: str, name: str) -> uuid.UUID:
    database = Database(settings.database(application_name="synapse-cli"), max_size=1)
    await database.open()
    try:
        tenant_id = uuid.uuid4()
        async with database.tenant_transaction(tenant_id) as connection:
            await connection.execute(
                "INSERT INTO tenants (id, slug, name) VALUES (%s, %s, %s)", (tenant_id, slug, name)
            )
        return tenant_id
    finally:
        await database.close()


def create_tenant(settings: Settings, slug: str, name: str) -> uuid.UUID:
    return asyncio.run(_create_tenant(settings, slug, name))


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
