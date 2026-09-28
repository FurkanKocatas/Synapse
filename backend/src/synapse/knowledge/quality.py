"""Per-page text quality for Turkish (ADR 0010, ingestion rule 3).

A page can have a text layer and still be useless: scanners write their own OCR into PDFs, and
bad OCR looks like "Bcledi;-e meclisi ilc itgili görcvlcri". Such pages must be OCR'd again, so
every page gets two signals:

- **How the lower-case words look:** the average log-probability of their letters under a
  character trigram model built from the born-digital documents of the evaluation corpus
  (``data/tr_char_trigrams.json``, built by ``eval/quality/build_char_model.py``). Their
  English references are included, so English passages are not mistaken for bad OCR. Wrong
  letters ("c" for "e", "ı" runs for "m") give trigrams neither language has. Only lower-case
  words count: names, places and acronyms are written with capitals.
- **OCR artefacts inside words:** commas, semicolons, "|" or "\\" between letters
  ("Bc,ledi.ve", "sorum|ulukları"), a lower-case "ıı" (Turkish words never have one), and case
  changes in the middle of a long word ("BELEDiyrsi", "sERDivAN"). Slashes, dots and digits
  between letters are left alone: "mg/kg", "T.C.", "HbA1c" are real. A suffix after an
  apostrophe ("KHK'nin") and each part of a hyphenated word ("SARS-CoV-2") is judged on its
  own.

The thresholds are set on the evaluation corpus; see docs/benchmarks/page-quality.md.
"""

import json
import math
import re
from dataclasses import dataclass
from functools import cache
from importlib import resources

from synapse.knowledge import turkish

# Letters in lower-case words below which the character score is not trusted.
MIN_LETTERS = 80
MIN_WORDS = 20
# Words shorter than this carry too few trigrams to judge.
MIN_WORD_LETTERS = 3
# Set by two-fold cross-validation on the evaluation corpus (docs/benchmarks/page-quality.md).
MIN_CHAR_SCORE = -4.2
MAX_ARTEFACTS = 0.03

_WORD = re.compile(r"\S+")
_EDGE_PUNCTUATION = "()[]{}<>\"'«»“”‘’.,;:!?-\u2013\u2014*•"
# Punctuation OCR leaves between two letters: "Bc,ledi.ve", "sorum|ulukları".
_INNER = re.compile(r"[^\W\d_][,;|\\][^\W\d_]")
# Apostrophes separate suffixes ("KHK'nin"), hyphens join parts ("SARS-CoV-2"); each part is
# judged on its own.
_PARTS = re.compile(r"['’\-]")
# Case changes count only in words at least this long; short ones are units and formulas.
MIN_CASE_CHECK = 6


@dataclass(frozen=True)
class CharModel:
    trigrams: dict[str, int]
    bigrams: dict[str, int]
    alphabet_size: int

    def log_prob(self, a: str, b: str, c: str) -> float:
        # Add-one smoothing over the alphabet (plus the word boundary).
        numerator = self.trigrams.get(a + b + c, 0) + 1
        denominator = self.bigrams.get(a + b, 0) + self.alphabet_size
        return math.log2(numerator / denominator)


@dataclass(frozen=True)
class Quality:
    letters: int  # letters in lower-case words: the evidence behind char_score
    char_score: float  # mean log2-probability per letter; higher looks more Turkish
    artefacts: float  # share of words with OCR artefacts
    needs_ocr: bool
    reason: str | None  # "not_turkish_like", "ocr_artefacts" or None


def letter_runs(text: str) -> list[str]:
    """Lower-cased runs of Turkish letters, each padded with a space as the word boundary."""
    runs: list[str] = []
    current: list[str] = []
    for ch in turkish.lower(text):
        if turkish.is_letter(ch):
            current.append(ch)
        elif current:
            runs.append(" " + "".join(current) + " ")
            current = []
    if current:
        runs.append(" " + "".join(current) + " ")
    return runs


def words(text: str) -> list[str]:
    """Words with their surrounding punctuation stripped; only those containing a letter."""
    stripped = (word.strip(_EDGE_PUNCTUATION) for word in _WORD.findall(text))
    return [word for word in stripped if any(ch.isalpha() for ch in word)]


def is_lower_word(word: str) -> bool:
    return len(word) >= MIN_WORD_LETTERS and all(turkish.is_letter(ch) for ch in word)


def char_score(model: CharModel, lower_words: list[str]) -> tuple[float, int]:
    total, count = 0.0, 0
    for word in lower_words:
        run = f" {word} "
        for i in range(len(run) - 2):
            total += model.log_prob(run[i], run[i + 1], run[i + 2])
            count += 1
    return (total / count if count else 0.0), count


def is_artefact(word: str) -> bool:
    if _INNER.search(word) or "ıı" in word:
        return True
    return any(_case_chaos(part) for part in _PARTS.split(word))


def _case_chaos(part: str) -> bool:
    """Lower, Capitalized and UPPER are fine; a case change inside a long word is not."""
    letters = [ch for ch in part if ch.isalpha()]
    if len(letters) < MIN_CASE_CHECK:
        return False
    rest = letters[1:]
    return any(ch.isupper() for ch in rest) and any(ch.islower() for ch in letters)


def assess(text: str, model: CharModel | None = None) -> Quality:
    model = model or default_model()
    all_words = words(text)
    lower = [word for word in all_words if is_lower_word(word)]
    score, letters = char_score(model, lower)
    artefacts = sum(map(is_artefact, all_words)) / len(all_words) if all_words else 0.0
    if letters >= MIN_LETTERS and score < MIN_CHAR_SCORE:
        return Quality(letters, score, artefacts, needs_ocr=True, reason="not_turkish_like")
    if len(all_words) >= MIN_WORDS and artefacts > MAX_ARTEFACTS:
        return Quality(letters, score, artefacts, needs_ocr=True, reason="ocr_artefacts")
    return Quality(letters, score, artefacts, needs_ocr=False, reason=None)


@cache
def default_model() -> CharModel:
    raw = resources.files("synapse.knowledge.data").joinpath("tr_char_trigrams.json").read_text()
    data = json.loads(raw)
    return CharModel(
        trigrams=data["trigrams"], bigrams=data["bigrams"], alphabet_size=data["alphabet_size"]
    )


def build_model(texts: list[str], *, min_count: int = 2) -> CharModel:
    trigrams: dict[str, int] = {}
    bigrams: dict[str, int] = {}
    for text in texts:
        for run in letter_runs(text):
            for i in range(len(run) - 2):
                key = run[i : i + 3]
                trigrams[key] = trigrams.get(key, 0) + 1
                bigrams[key[:2]] = bigrams.get(key[:2], 0) + 1
    kept = {key: n for key, n in trigrams.items() if n >= min_count}
    return CharModel(trigrams=kept, bigrams=bigrams, alphabet_size=len(turkish.LETTERS) + 1)
