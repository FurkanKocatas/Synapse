"""One-time recovery codes for when the authenticator is lost.

Each code carries 80 random bits, so a fast hash is enough: guessing is infeasible regardless
of hash speed, and a SHA-256 lookup avoids checking every stored code with a slow hash. (ADR
0006 mentions Argon2 for recovery codes; this deviation is recorded in docs/design/identity.md.)
"""

import base64
import hashlib
import secrets

CODE_COUNT = 10
_CODE_BYTES = 10  # 80 bits, 16 base32 characters


def new_codes() -> list[str]:
    """Codes as shown to the user: 16 characters in four groups, e.g. ``ABCD-EFGH-IJKL-MNOP``."""
    codes = []
    for _ in range(CODE_COUNT):
        raw = base64.b32encode(secrets.token_bytes(_CODE_BYTES)).decode("ascii")
        codes.append("-".join(raw[i : i + 4] for i in range(0, 16, 4)))
    return codes


def normalize(code: str) -> str:
    """Users may type codes with or without dashes and spaces, in any case."""
    return "".join(character for character in code.upper() if character.isalnum())


def hash_code(code: str) -> str:
    return hashlib.sha256(normalize(code).encode("ascii")).hexdigest()
