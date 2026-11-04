"""Whose documents an answer rests on: asked about one organisation, an answer must not rest on
another's.

Asked about an organisation the documents hold nothing of ("Trabzon Büyükşehir Belediyesi'nin
2024 faaliyet raporuna göre toplam personel sayısı"), the search finds another's document of the
same kind and the model answers from it: the golden set had Ordu's staff count given as
Trabzon's and Efeler's strategic aims as Erzurum's. Verification (verification.py) finds every
number in the cited source and is satisfied.

An organisation is named by a capitalised word right before a word of its kind: "Trabzon
Büyükşehir Belediyesi", "ORDU BÜYÜKŞEHİR BELEDİYESİ", "Ankara Barosu". An answer rests on
another's documents when the question names an organisation of a kind, its cited sources name
another of that kind, and the one asked about stands nowhere in them. A source that names no
organisation decides nothing: the pages of a strategic plan say "www.usak.bel.tr", not "Uşak
Belediyesi", and a training deck may not say whose it is at all. Names are compared without
Turkish letters, so an OCR'd "SILE BELEDIYESI" is Şile's. On the golden set's harness runs the
check refused the two answers that rested on another municipality's documents and none of the
other 79 answered questions naming an organisation (docs/benchmarks/answers.md).
"""

import re
from collections.abc import Sequence

from synapse.chat.verification import fold

# The words of a kind of organisation, plain, with the suffixes that keep them naming one:
# "belediyesi'nin", "barosu", not "belediyemiz" (our own).
_KINDS = (
    re.compile(r"belediye(?:si\w*)?"),
    re.compile(r"baro(?:su\w*)?"),
    re.compile(r"universite(?:si\w*)?"),
    re.compile(r"valili[kg]\w*"),
    re.compile(r"kaymakamli[kg]\w*"),
)
_METROPOLITAN = "buyuksehir"
# Capitalised words before a kind's word that do not name the organisation ("T.C. İLÇE
# BELEDİYESİ").
_GENERIC = frozenset({"t.c", "tc", "ilce", "il", "merkez", "ve", "ile", "bu", "her", "ilgili"})
_PUNCTUATION = ".,;:()\"'"
# Folded text without Turkish letters: Turkish lower case reads an OCR'd "BELEDIYESI" as
# "beledıyesı".
_PLAIN = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def other_organisation(question: str, sources: Sequence[str], citations: Sequence[int]) -> bool:
    """Whether the sources an answer to ``question`` cites (``citations``, numbered from 1) are
    another organisation's than the one the question names."""
    cited = " ".join(sources[n - 1] for n in citations if 1 <= n <= len(sources))
    text = _plain(cited)
    for kind in _KINDS:
        asked = _named(question, kind)
        if not asked:
            continue
        others = _named(cited, kind) - asked
        if others and any(re.search(rf"(?<!\w){re.escape(name)}", text) is None for name in asked):
            return True
    return False


def _named(text: str, kind: re.Pattern[str]) -> set[str]:
    """The organisations of ``kind`` that ``text`` names, by the capitalised word before the
    kind's word ("Büyükşehir" in between), plain."""
    tokens = text.split()
    names = set()
    for i, token in enumerate(tokens):
        if not token[:1].isupper() or not kind.fullmatch(_stem(token)):
            continue
        j = i - 1 if i and _stem(tokens[i - 1]) != _METROPOLITAN else i - 2
        if j < 0 or not tokens[j][:1].isupper():
            continue
        name = _stem(tokens[j])
        if name and name not in _GENERIC and not any(ch.isdigit() for ch in name):
            names.add(name)
    return names


def _stem(token: str) -> str:
    """A token plain, without the suffix an apostrophe sets off or the punctuation around it."""
    return _plain(token).strip(_PUNCTUATION).split("'")[0].strip(_PUNCTUATION)


def _plain(text: str) -> str:
    return fold(text).translate(_PLAIN)
