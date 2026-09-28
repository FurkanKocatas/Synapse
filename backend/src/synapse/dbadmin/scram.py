"""SCRAM-SHA-256 password verifiers for PostgreSQL roles.

Sending ``ALTER ROLE ... PASSWORD 'secret'`` puts the plain password into the statement text,
which ends up in server logs whenever statement logging is on. Sending the verifier instead
means the server never sees the password at all. The format and derivation follow RFC 5802 and
RFC 7677, as implemented by PostgreSQL (src/common/scram-common.c).
"""

import base64
import hashlib
import hmac
import secrets

ITERATIONS = 4096  # PostgreSQL's default scram_iterations
SALT_BYTES = 16


def scram_sha256_verifier(password: str, *, salt: bytes | None = None) -> str:
    """Return ``SCRAM-SHA-256$<iterations>:<salt>$<StoredKey>:<ServerKey>`` for ``password``."""
    salt = salt if salt is not None else secrets.token_bytes(SALT_BYTES)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    client_key = hmac.digest(salted, b"Client Key", "sha256")
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.digest(salted, b"Server Key", "sha256")

    def b64(raw: bytes) -> str:
        return base64.b64encode(raw).decode("ascii")

    return f"SCRAM-SHA-256${ITERATIONS}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"
