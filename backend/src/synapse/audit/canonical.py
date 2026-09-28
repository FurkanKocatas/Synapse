"""Canonical serialization of audit events for hashing.

The hash must be reproducible from the stored row, years later, by the verifier. The encoding
is RFC 8785 (JSON Canonicalization Scheme) restricted to the value types audit events use:
strings, integers, booleans, null, lists and objects with ASCII keys. For those types JCS
equals ``json.dumps`` with sorted keys, no whitespace and literal Unicode. Floats are rejected,
because their JCS form needs a specific number formatting algorithm we have no reason to rely on.
"""

import json
from collections.abc import Mapping, Sequence

type JsonValue = str | int | bool | Sequence["JsonValue"] | Mapping[str, "JsonValue"] | None


class NotCanonicalError(ValueError):
    """The value contains something the audit encoding does not allow."""


def canonical_bytes(value: Mapping[str, JsonValue]) -> bytes:
    _check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _check(value: object) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        raise NotCanonicalError("floats are not allowed in audit events")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not (isinstance(key, str) and key.isascii()):
                raise NotCanonicalError(f"object keys must be ASCII strings: {key!r}")
            _check(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, bytes):
        for item in value:
            _check(item)
        return
    raise NotCanonicalError(f"type not allowed in audit events: {type(value).__name__}")
