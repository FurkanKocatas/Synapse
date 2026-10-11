"""One-time recovery codes for when the authenticator is lost.

Ten codes of 80 random bits, stored with Argon2id as passwords are (ADR 0006; decided
2026-10-07), so a copy of the table gives no code and no offline guess is cheap. A typed code is
checked against each of the user's unused codes in turn; only one that looks like a code (16
letters and digits once dashes and spaces are gone) is tried, so a TOTP code costs no hashing.
Codes issued before 2026-10-11 were stored as unsalted SHA-256; they still work, compared in
constant time, until the user's next set replaces them.
"""

import base64
import hashlib
import hmac
import secrets
from collections.abc import Sequence
from uuid import UUID

from synapse.identity import passwords

CODE_COUNT = 10
_CODE_BYTES = 10  # 80 bits, 16 base32 characters
CODE_LENGTH = 16


def new_codes() -> list[str]:
    """Codes as shown to the user: 16 characters in four groups, e.g. ``ABCD-EFGH-IJKL-MNOP``."""
    codes = []
    for _ in range(CODE_COUNT):
        raw = base64.b32encode(secrets.token_bytes(_CODE_BYTES)).decode("ascii")
        codes.append("-".join(raw[i : i + 4] for i in range(0, CODE_LENGTH, 4)))
    return codes


def normalize(code: str) -> str:
    """Users may type codes with or without dashes and spaces, in any case."""
    return "".join(character for character in code.upper() if character.isalnum())


def looks_like_a_code(code: str) -> bool:
    typed = normalize(code)
    return len(typed) == CODE_LENGTH and typed.isascii()


def hash_code(code: str) -> str:
    return passwords.hash_password(normalize(code))


def matches(stored: str, code: str) -> bool:
    """Whether ``code`` is the one ``stored`` holds, Argon2id or (an older code) SHA-256."""
    typed = normalize(code)
    if stored.startswith("$argon2"):
        return passwords.verify_password(stored, typed)
    return hmac.compare_digest(stored, hashlib.sha256(typed.encode("ascii")).hexdigest())


def find(stored: Sequence[tuple[UUID, str]], code: str) -> UUID | None:
    """The ID of the unused code ``code`` is, among the user's ``stored`` (ID, hash) pairs."""
    if not looks_like_a_code(code):
        return None
    return next((code_id for code_id, held in stored if matches(held, code)), None)
