import uuid
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from synapse.audit.anchor import Checkpoint, checkpoint_is_authentic, sign_head
from synapse.audit.canonical import NotCanonicalError, canonical_bytes
from synapse.audit.chain import AuditEvent, ChainHead, event_hash

NOW = datetime(2026, 9, 28, 12, 30, 15, 123456, tzinfo=UTC)


def test_canonical_form_sorts_keys_and_keeps_unicode() -> None:
    assert canonical_bytes({"b": 1, "a": {"y": [True, None], "x": "şİı"}}) == (
        '{"a":{"x":"şİı","y":[true,null]},"b":1}'.encode()
    )


@pytest.mark.parametrize("bad", [{"f": 1.5}, {1: "x"}, {"ç": 1}, {"b": b"bytes"}])
def test_values_outside_the_audit_encoding_are_rejected(bad: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(NotCanonicalError):
        canonical_bytes(bad)


def hash_for(event: AuditEvent, *, seq: int = 1, prev: bytes = bytes(32)) -> bytes:
    return event_hash(
        tenant_id=uuid.UUID(int=1),
        seq=seq,
        event_id=uuid.UUID(int=2),
        occurred_at=NOW,
        event=event,
        schema_version=1,
        prev_hash=prev,
    )


def test_every_field_changes_the_hash() -> None:
    base = AuditEvent("identity.login", "success", actor_ip="192.0.2.1", details={"k": "v"})
    variants = [
        AuditEvent("identity.logout", "success", actor_ip="192.0.2.1", details={"k": "v"}),
        AuditEvent("identity.login", "failure", actor_ip="192.0.2.1", details={"k": "v"}),
        AuditEvent("identity.login", "success", actor_ip="192.0.2.2", details={"k": "v"}),
        AuditEvent("identity.login", "success", actor_ip="192.0.2.1", details={"k": "w"}),
        AuditEvent(
            "identity.login", "success", actor_ip="192.0.2.1", details={"k": "v"}, target_id="x"
        ),
    ]
    reference = hash_for(base)
    assert all(hash_for(variant) != reference for variant in variants)
    assert hash_for(base, seq=2) != reference
    assert hash_for(base, prev=b"\x01" * 32) != reference


def test_checkpoints_verify_and_detect_tampering() -> None:
    key = Ed25519PrivateKey.generate()
    head = ChainHead(tenant_id=uuid.uuid4(), seq=42, hash=b"\xab" * 32)
    checkpoint = sign_head(key, head, NOW)
    assert checkpoint_is_authentic(key.public_key(), checkpoint)
    forged = Checkpoint(
        payload=checkpoint.payload.replace('"seq":42', '"seq":41'), signature=checkpoint.signature
    )
    assert not checkpoint_is_authentic(key.public_key(), forged)
    assert not checkpoint_is_authentic(Ed25519PrivateKey.generate().public_key(), checkpoint)
