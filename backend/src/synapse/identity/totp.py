"""TOTP second factor (RFC 6238) with encrypted secrets and replay protection.

Secrets are encrypted with AES-256-GCM under a key from a secret file (ADR 0013), bound to the
user's ID as associated data, so a ciphertext copied to another user's row does not decrypt.
Each accepted code's time step is stored; a code for that step or an earlier one is rejected,
so an intercepted code cannot be used twice.
"""

import os
import time
from dataclasses import dataclass
from uuid import UUID

import pyotp
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ISSUER = "Synapse"
STEP_SECONDS = 30
# Accept the previous and next step as well, for clock drift between phone and server.
VALID_WINDOW = 1
CODE_DIGITS = 6
KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12


@dataclass(frozen=True)
class AcceptedCode:
    step: int


class TotpCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise ValueError("TOTP encryption key must be 32 bytes")
        self._aead = AESGCM(key)

    def encrypt(self, user_id: UUID, secret: str) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, secret.encode("ascii"), user_id.bytes)

    def decrypt(self, user_id: UUID, ciphertext: bytes) -> str:
        nonce, body = ciphertext[:_NONCE_BYTES], ciphertext[_NONCE_BYTES:]
        return self._aead.decrypt(nonce, body, user_id.bytes).decode("ascii")


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, account_name: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=ISSUER)


def verify_code(
    secret: str, code: str, *, last_used_step: int | None, now: float | None = None
) -> AcceptedCode | None:
    """Return the accepted time step, or None if the code is wrong or already used."""
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == CODE_DIGITS):
        return None
    totp = pyotp.TOTP(secret)
    moment = time.time() if now is None else now
    current = int(moment // STEP_SECONDS)
    for step in range(current - VALID_WINDOW, current + VALID_WINDOW + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if pyotp.utils.strings_equal(totp.at(step * STEP_SECONDS), code):
            return AcceptedCode(step=step)
    return None
