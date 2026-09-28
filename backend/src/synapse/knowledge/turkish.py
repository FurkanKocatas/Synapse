"""Turkish-aware text helpers (ADR 0010: "never plain lower()").

Python's ``str.lower`` maps "I" to "i" and "İ" to "i" followed by a combining dot, both wrong
for Turkish, where "I" pairs with "ı" and "İ" with "i". Every place that folds case for search,
matching or statistics goes through ``lower`` here.
"""

import unicodedata

_UPPER_I = str.maketrans({"I": "ı", "İ": "i"})

# The letters of the Turkish alphabet plus the three that appear in loanwords and names.
LETTERS = frozenset("abcçdefgğhıijklmnoöprsştuüvyzqwxâîû")


def lower(text: str) -> str:
    return unicodedata.normalize("NFC", text.translate(_UPPER_I).lower())


def is_letter(ch: str) -> bool:
    return ch in LETTERS
