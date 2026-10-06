"""``synapse audit verify`` and ``synapse audit checkpoint`` for operators and the scheduler."""

import asyncio
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg import AsyncConnection

from synapse.audit import public as audit
from synapse.kernel.config import Settings
from synapse.kernel.database import Database
from synapse.kernel.secrets import SecretError


class AuditCommandError(RuntimeError):
    """A problem the operator can fix; printed without a traceback."""


async def _with_tenant_connection(settings: Settings, action: str) -> str:
    if settings.tenant_id is None:
        raise AuditCommandError("SYNAPSE_TENANT_ID is not set")
    tenant_id = settings.tenant_id
    database = Database(settings.database(application_name="synapse-audit"), max_size=1)
    await database.open()
    try:
        async with database.tenant_transaction(tenant_id) as connection:
            if action == "verify":
                result = await audit.verify(connection, tenant_id)
                if result.ok:
                    result = await _with_checkpoints(connection, tenant_id, settings, result)
                return json.dumps(asdict(result))
            head = await audit.head(connection, tenant_id)
    finally:
        await database.close()
    if head is None:
        raise AuditCommandError("the audit log is empty; there is nothing to sign")
    checkpoint = audit.sign_head(signing_key(settings), head, datetime.now(UTC))
    return json.dumps(asdict(checkpoint))


async def _with_checkpoints(
    connection: AsyncConnection,
    tenant_id: UUID,
    settings: Settings,
    result: audit.VerificationResult,
) -> audit.VerificationResult:
    """The chain is intact; are the kept checkpoints still its own?"""
    public_key = signing_key(settings).public_key()
    found = await audit.verify_checkpoints(connection, tenant_id, public_key)
    return replace(
        result, ok=found.problem is None, problem=found.problem, checkpoints_checked=found.checked
    )


def signing_key(settings: Settings) -> Ed25519PrivateKey:
    try:
        return audit.load_signing_key(settings.audit_signing_key_file)
    except (SecretError, OSError) as error:
        raise AuditCommandError(f"cannot read the audit signing key: {error}") from error


def verify(settings: Settings) -> tuple[bool, str]:
    """Recompute the chain; returns whether it is intact and a JSON report."""
    report = asyncio.run(_with_tenant_connection(settings, "verify"))
    return bool(json.loads(report)["ok"]), report


def checkpoint(settings: Settings) -> str:
    """A signed checkpoint of the current chain head, as JSON."""
    return asyncio.run(_with_tenant_connection(settings, "checkpoint"))
