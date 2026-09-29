"""Fingerprints for duplicate chunks (ADR 0010, ingestion rule 8).

- ``content_hash``: SHA-256 of the text with case and spacing folded; equal hashes are the
  same chunk (the same regulation uploaded twice, a boilerplate paragraph on every page).
- ``simhash``: a 64-bit fingerprint over word triples; near-duplicates (a reissued decision
  with one date changed) differ in few bits, so search can show one of them and link the rest.
"""

import hashlib
import re

from synapse.knowledge.turkish import lower

SHINGLE = 3
BITS = 64
_WORD = re.compile(r"\w+")


def _words(text: str) -> list[str]:
    return _WORD.findall(lower(text))


def content_hash(text: str) -> bytes:
    return hashlib.sha256(" ".join(_words(text)).encode()).digest()


def simhash(text: str) -> int:
    """A signed 64-bit integer, so it fits a Postgres bigint."""
    words = _words(text)
    shingles = [" ".join(words[i : i + SHINGLE]) for i in range(max(1, len(words) - SHINGLE + 1))]
    weights = [0] * BITS
    for shingle in shingles:
        value = int.from_bytes(hashlib.blake2b(shingle.encode(), digest_size=8).digest(), "big")
        for bit in range(BITS):
            weights[bit] += 1 if value >> bit & 1 else -1
    fingerprint = sum(1 << bit for bit in range(BITS) if weights[bit] > 0)
    return fingerprint - (1 << BITS) if fingerprint >= 1 << (BITS - 1) else fingerprint


def distance(a: int, b: int) -> int:
    """Bits in which two fingerprints differ."""
    return ((a ^ b) & ((1 << BITS) - 1)).bit_count()
