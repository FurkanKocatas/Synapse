"""Signed checkpoints of the chain head (ADR 0008).

A superuser could rewrite every audit row and recompute every hash. What they cannot do is
change a checkpoint that already left the machine: the scheduler signs the current head with
the instance's Ed25519 key, every hour the head has moved, and keeps it in
``audit_checkpoints``, which every backup carries off the machine (an export to the customer's
administrator, syslog or a file is to come). Comparing a checkpoint with the live chain then
reveals any rewrite; one kept in the database alone still stops anyone who can change the
database but cannot read the key.
"""

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from psycopg import AsyncConnection

from synapse.audit.chain import ChainHead, head
from synapse.kernel.secrets import read_key


@dataclass(frozen=True)
class Checkpoint:
    payload: str  # canonical JSON: tenant, seq, hash, signed_at
    signature: str  # base64 of the Ed25519 signature over the payload bytes


def sign_head(key: Ed25519PrivateKey, head: ChainHead, now: datetime) -> Checkpoint:
    payload = json.dumps(
        {
            "tenant_id": str(head.tenant_id),
            "seq": head.seq,
            "hash": head.hash.hex(),
            "signed_at": now.astimezone(UTC).isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    signature = key.sign(payload.encode("utf-8"))
    return Checkpoint(payload=payload, signature=base64.b64encode(signature).decode("ascii"))


def checkpoint_is_authentic(public_key: Ed25519PublicKey, checkpoint: Checkpoint) -> bool:
    try:
        public_key.verify(base64.b64decode(checkpoint.signature), checkpoint.payload.encode())
    except InvalidSignature, ValueError:
        return False
    return True


def load_signing_key(path: Path) -> Ed25519PrivateKey:
    """The instance's signing key: a 32-byte Ed25519 seed, created by the installer. Raises
    ``SecretError`` or ``OSError`` when it cannot be read."""
    return Ed25519PrivateKey.from_private_bytes(read_key(path))


@dataclass(frozen=True)
class CheckpointsChecked:
    checked: int
    problem: str | None = None


async def store_checkpoint(
    connection: AsyncConnection, tenant_id: UUID, key: Ed25519PrivateKey, now: datetime
) -> Checkpoint | None:
    """Sign the chain's head and keep the checkpoint; None when the chain is empty or its head
    has a checkpoint already."""
    current = await head(connection, tenant_id)
    if current is None:
        return None
    checkpoint = sign_head(key, current, now)
    cursor = await connection.execute(
        "INSERT INTO audit_checkpoints (tenant_id, seq, payload, signature, signed_at) "
        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (tenant_id, current.seq, checkpoint.payload, checkpoint.signature, now),
    )
    return checkpoint if cursor.rowcount else None


async def verify_checkpoints(
    connection: AsyncConnection, tenant_id: UUID, public_key: Ed25519PublicKey
) -> CheckpointsChecked:
    """Every kept checkpoint: signed with this key, and naming the hash the chain still has at
    its event. Stops at the first problem."""
    cursor = await connection.execute(
        "SELECT c.seq, c.payload, c.signature, e.hash FROM audit_checkpoints c "
        "LEFT JOIN audit_events e ON e.tenant_id = c.tenant_id AND e.seq = c.seq "
        "WHERE c.tenant_id = %s ORDER BY c.seq",
        (tenant_id,),
    )
    checked = 0
    for seq, payload, signature, event_hash in await cursor.fetchall():
        if not checkpoint_is_authentic(public_key, Checkpoint(payload, signature)):
            return CheckpointsChecked(checked, f"the checkpoint of event {seq} is not signed")
        signed = json.loads(payload)
        if signed["tenant_id"] != str(tenant_id) or signed["seq"] != seq:
            return CheckpointsChecked(checked, f"the checkpoint of event {seq} names another")
        if event_hash is None:
            return CheckpointsChecked(
                checked,
                f"event {seq} is missing, though signed on {signed['signed_at']}: the chain "
                "was cut",
            )
        if signed["hash"] != bytes(event_hash).hex():
            return CheckpointsChecked(
                checked,
                f"event {seq} differs from its checkpoint of {signed['signed_at']}: "
                "the chain was rewritten",
            )
        checked += 1
    return CheckpointsChecked(checked)
