"""Reading secrets from files.

Secrets are mounted as files (``/run/secrets/...``) and referenced by path in settings, never
passed as environment variable values (ADR 0013).
"""

from pathlib import Path


class SecretError(RuntimeError):
    """A required secret is missing or empty. Startup must stop; there are no defaults."""


def read_secret(path: Path) -> str:
    """Return the secret stored in ``path``, without the trailing newline editors add."""
    try:
        value = path.read_text(encoding="utf-8").rstrip("\r\n")
    except FileNotFoundError as error:
        raise SecretError(f"secret file not found: {path}") from error
    if not value:
        raise SecretError(f"secret file is empty: {path}")
    return value
