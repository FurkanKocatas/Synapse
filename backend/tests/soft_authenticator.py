"""A software WebAuthn authenticator for tests: real ES256 keys, CBOR and signatures.

It produces the JSON a browser sends after ``navigator.credentials.create()`` and ``.get()``,
so the tests run the real verification in the ``webauthn`` package instead of a stand-in.
"""

import base64
import hashlib
import json
import secrets
import struct
from dataclasses import dataclass, field
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

FLAG_USER_PRESENT = 0x01
FLAG_USER_VERIFIED = 0x04
FLAG_BACKUP_ELIGIBLE = 0x08
FLAG_BACKED_UP = 0x10
FLAG_ATTESTED_DATA = 0x40


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass
class SoftAuthenticator:
    origin: str
    rp_id: str
    user_verified: bool = True
    synced: bool = False
    key: ec.EllipticCurvePrivateKey = field(
        default_factory=lambda: ec.generate_private_key(ec.SECP256R1())
    )
    credential_id: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    sign_count: int = 0

    def _flags(self, *, attested: bool) -> int:
        flags = FLAG_USER_PRESENT | (FLAG_USER_VERIFIED if self.user_verified else 0)
        if self.synced:
            flags |= FLAG_BACKUP_ELIGIBLE | FLAG_BACKED_UP
        return flags | (FLAG_ATTESTED_DATA if attested else 0)

    def _cose_public_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps(
            {
                1: 2,
                3: -7,
                -1: 1,
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )

    def _client_data(self, kind: str, challenge: str, origin: str | None) -> bytes:
        return json.dumps(
            {
                "type": kind,
                "challenge": challenge,
                "origin": origin or self.origin,
                "crossOrigin": False,
            }
        ).encode()

    def create(self, options: dict[str, Any], *, origin: str | None = None) -> dict[str, Any]:
        """Answer registration options, as ``navigator.credentials.create()`` would."""
        rp_hash = hashlib.sha256(options["rp"]["id"].encode()).digest()
        attested = (
            bytes(16)  # AAGUID: none, as with attestation "none"
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self._cose_public_key()
        )
        auth_data = (
            rp_hash
            + bytes([self._flags(attested=True)])
            + struct.pack(">I", self.sign_count)
            + attested
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "attestationObject": b64url(attestation),
                "transports": ["internal", "hybrid"],
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }

    def get(self, options: dict[str, Any], *, origin: str | None = None) -> dict[str, Any]:
        """Answer authentication options, as ``navigator.credentials.get()`` would."""
        self.sign_count += 1
        rp_hash = hashlib.sha256(options["rpId"].encode()).digest()
        auth_data = (
            rp_hash + bytes([self._flags(attested=False)]) + struct.pack(">I", self.sign_count)
        )
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "authenticatorData": b64url(auth_data),
                "signature": b64url(signature),
                "userHandle": None,
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }
