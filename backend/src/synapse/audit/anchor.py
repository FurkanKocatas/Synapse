"""Signed checkpoints of the chain head (ADR 0008).

A superuser could rewrite every audit row and recompute every hash. What they cannot do is
change a checkpoint that already left the machine: the scheduler signs the current head with
the instance's Ed25519 key and exports it (to the customer's administrator, syslog or a file).
Comparing an exported checkpoint with the live chain then reveals any rewrite.
"""

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from synapse.audit.chain import ChainHead


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
