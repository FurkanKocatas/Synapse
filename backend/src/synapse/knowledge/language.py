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
class Language:
    ordinals: tuple[str, ...]
    part: str
    chapter: str
    article: str
    article_prefixes: tuple[str, ...]
    abbreviations: frozenset[str]
    table_summary: SummaryWords


@cache
def language(code: str = "tr") -> Language:
    data = json.loads(
        files("synapse.knowledge.data").joinpath(f"language_{code}.json").read_text("utf-8")
    )
    return Language(
        ordinals=tuple(data["ordinals"]),
        part=data["part"],
        chapter=data["chapter"],
        article=data["article"],
        article_prefixes=tuple(data["article_prefixes"]),
        abbreviations=frozenset(data["abbreviations"]),
        table_summary=SummaryWords(**data["table_summary"]),
    )
