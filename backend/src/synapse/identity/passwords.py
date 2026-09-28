"""Password hashing and policy.

Hashing: Argon2id with parameters stored inside each hash, so they can be raised later and
old hashes are upgraded on the next successful login (``needs_rehash``).

Policy: NIST SP 800-63B-4. Length is what matters; there are no composition rules and no
forced rotation. A password is rejected when it is too short or too long, or when it contains
words from the account's own context (email name, display name, organization).
"""

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# OWASP minimum for Argon2id. To be raised after benchmarking on the minimum target CPU, as
# long as a login stays under 250 ms (ADR 0006).
_HASHER = PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1, type=Type.ID)

MIN_LENGTH_SINGLE_FACTOR = 15
MIN_LENGTH_WITH_MFA = 8
# NIST asks to accept at least 64 characters. The upper bound stops hashing from becoming a
# denial-of-service vector with megabyte-sized "passwords".
MAX_LENGTH = 256
# Context words shorter than this are too common to reject on (e.g. "ab" in an email name).
_MIN_CONTEXT_WORD = 4

# A valid hash that matches no password: verifying against it when an account does not exist
# makes a failed login take as long as for an existing account, so timing reveals nothing.
_DUMMY_HASH = _HASHER.hash("synapse-dummy-password-for-timing-equalisation")


class PasswordPolicyError(ValueError):
    """The password does not meet the policy. ``code`` is a stable, translatable identifier."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-effort check. ``None`` (no account, or password login disabled) is always False."""
    if len(password) > MAX_LENGTH:
        return False
    try:
        return _HASHER.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except VerifyMismatchError, VerificationError, InvalidHashError:
        return False


def needs_rehash(password_hash: str) -> bool:
    return _HASHER.check_needs_rehash(password_hash)


def validate_password(password: str, *, mfa_enabled: bool, context_words: list[str]) -> None:
    """Raise :class:`PasswordPolicyError` if ``password`` may not be set."""
    minimum = MIN_LENGTH_WITH_MFA if mfa_enabled else MIN_LENGTH_SINGLE_FACTOR
    if len(password) < minimum:
        raise PasswordPolicyError("password_too_short")
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError("password_too_long")
    folded = password.casefold()
    for word in context_words:
        candidate = word.casefold().strip()
        if len(candidate) >= _MIN_CONTEXT_WORD and candidate in folded:
            raise PasswordPolicyError("password_contains_context")
