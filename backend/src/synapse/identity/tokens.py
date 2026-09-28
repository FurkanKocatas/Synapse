"""Session tokens and CSRF tokens.

The browser holds a random 256-bit session token in a cookie. The database stores only its
SHA-256, so a database leak does not reveal usable sessions. The CSRF token is derived from the
session token with a server-side key, so it needs no storage and changes with every session.
"""

import hashlib
import hmac
import secrets

TOKEN_BYTES = 32


def new_session_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_session_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def csrf_token(csrf_key: bytes, token_hash: bytes) -> str:
    return hmac.new(csrf_key, token_hash, "sha256").hexdigest()


def csrf_token_matches(csrf_key: bytes, token_hash: bytes, presented: str) -> bool:
    return hmac.compare_digest(csrf_token(csrf_key, token_hash), presented)
