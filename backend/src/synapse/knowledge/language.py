"""A document language's conventions, as data (knowledge/data/language_<code>.json).

The words that mark sections ("kısım", "bölüm", "madde"), the abbreviations a full stop does not
end a sentence after, and the words of a table's summary chunk belong to the language of the
documents, not to the code: a tenant with other conventions, or another language, gets another
file.
"""

import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files


@dataclass(frozen=True)
class SummaryWords:
    table: str
    rows: str
    columns: str
    column_names: str
    row_labels: str


@dataclass(frozen=True)
class EntityWords:
    months: tuple[str, ...]
    numbered_law: str
    decision_words: tuple[str, ...]
    court_marks: tuple[str, ...]
    article_words: tuple[str, ...]
    article_suffixes: tuple[str, ...]
    article_noun: str
    parcel_block: str
    parcel: str
    # Symbol or word (lower case) to ISO 4217 code.
    currencies: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Language:
    ordinals: tuple[str, ...]
    part: str
    chapter: str
    article: str
    article_prefixes: tuple[str, ...]
    # The word before a page number in a footer ("Sayfa 3 / 40").
    page_word: str
    abbreviations: frozenset[str]
    table_summary: SummaryWords
    entities: EntityWords
    # The words a document names its kind with, each with the kind's name (metadata.py).
    document_kinds: tuple[tuple[str, str], ...]


@cache
def language(code: str = "tr") -> Language:
    data = json.loads(
        files("synapse.knowledge.data").joinpath(f"language_{code}.json").read_text("utf-8")
    )
    entities = data["entities"]
    return Language(
        ordinals=tuple(data["ordinals"]),
        part=data["part"],
        chapter=data["chapter"],
        article=data["article"],
        article_prefixes=tuple(data["article_prefixes"]),
        page_word=data["page_word"],
        abbreviations=frozenset(data["abbreviations"]),
        table_summary=SummaryWords(**data["table_summary"]),
        document_kinds=tuple((word, label) for word, label in data["document_kinds"]),
        entities=EntityWords(
            months=tuple(entities["months"]),
            numbered_law=entities["numbered_law"],
            decision_words=tuple(entities["decision_words"]),
            court_marks=tuple(entities["court_marks"]),
            article_words=tuple(entities["article_words"]),
            article_suffixes=tuple(entities["article_suffixes"]),
            article_noun=entities["article_noun"],
            parcel_block=entities["parcel_words"]["block"],
            parcel=entities["parcel_words"]["parcel"],
            currencies=tuple(entities["currencies"].items()),
        ),
    )
