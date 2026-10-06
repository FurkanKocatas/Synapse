"""Office files cannot make the parser read other files or expand entities (ASVS V1.5.1).

Each case puts an entity in a real Word, Excel or PowerPoint package: an external one naming a
file on this machine, and the "billion laughs" of nested ones. Parsing may refuse the file;
it must never put the file's contents, or the expansion, into the text.
"""

import io
import re
import xml.parsers.expat
import zipfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import pytest

from synapse.knowledge.filetypes import MediaType
from synapse.knowledge.parsing import LightParser, ParseError
from tests import knowledge_samples as samples

HIDDEN_TEXT = "GIZLI-DOSYA-ICERIGI-4711"
LAUGHS = (
    '<!ENTITY lol "lol">'
    + "".join(f'<!ENTITY lol{n} "{f"&lol{n - 1};" * 10}">' for n in range(2, 7))
).replace("&lol1;", "&lol;")

CASES = [
    (samples.word, "word/document.xml", "Kabul edildi", MediaType.DOCX),
    (samples.spreadsheet, "xl/worksheets/sheet1.xml", "Personel", MediaType.XLSX),
    (samples.slides, "ppt/slides/slide1.xml", "KVKK Eğitimi", MediaType.PPTX),
]


def with_entity(package: bytes, part: str, marker: str, declarations: str, use: str) -> bytes:
    """``package`` with ``declarations`` in a DOCTYPE of ``part`` and ``marker`` replaced by
    ``use``."""
    out = io.BytesIO()
    changed = False
    with (
        zipfile.ZipFile(io.BytesIO(package)) as source,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for item in source.infolist():
            data = source.read(item)
            if item.filename == part:
                text = data.decode("utf-8")
                assert marker in text, part
                start = text.index("?>") + 2 if text.startswith("<?xml") else 0
                found = re.match(r"\s*<([\w:]+)", text[start:])
                assert found is not None
                doctype = f"<!DOCTYPE {found.group(1)} [{declarations}]>"
                text = text[:start] + doctype + text[start:].replace(marker, use, 1)
                data = text.encode("utf-8")
                changed = True
            target.writestr(item, data)
    assert changed, part
    return out.getvalue()


def text_as_entities_resolve(package: bytes, part: str) -> str:
    """The part's text as a parser that follows external entities reads it: the payload works."""
    texts: list[str] = []
    parser = xml.parsers.expat.ParserCreate()
    parser.SetParamEntityParsing(xml.parsers.expat.XML_PARAM_ENTITY_PARSING_ALWAYS)
    parser.CharacterDataHandler = texts.append

    def external(
        context: str, _base: str | None, system_id: str | None, _public: str | None
    ) -> int:
        assert system_id is not None
        parser.ExternalEntityParserCreate(context).Parse(
            Path(urlparse(system_id).path).read_bytes(),
            True,  # noqa: FBT003  (positional only)
        )
        return 1

    parser.ExternalEntityRefHandler = external
    with zipfile.ZipFile(io.BytesIO(package)) as source:
        parser.Parse(source.read(part), True)  # noqa: FBT003  (positional only)
    return "".join(texts)


def parsed_text(path: Path, media_type: MediaType) -> str:
    try:
        return repr(LightParser().parse(path, media_type))
    except ParseError:
        return ""  # refusing the file is safe too


@pytest.mark.parametrize(("build", "part", "marker", "media_type"), CASES)
def test_an_external_entity_is_never_read(
    tmp_path: Path, build: Callable[[], bytes], part: str, marker: str, media_type: MediaType
) -> None:
    hidden = tmp_path / "hidden.txt"
    hidden.write_text(HIDDEN_TEXT, encoding="utf-8")
    package = with_entity(
        build(), part, marker, f'<!ENTITY xxe SYSTEM "{hidden.as_uri()}">', "&xxe;"
    )
    assert HIDDEN_TEXT in text_as_entities_resolve(package, part)
    path = tmp_path / "evil"
    path.write_bytes(package)
    assert HIDDEN_TEXT not in parsed_text(path, media_type)


@pytest.mark.parametrize(("build", "part", "marker", "media_type"), CASES)
def test_nested_entities_are_not_expanded(
    tmp_path: Path, build: Callable[[], bytes], part: str, marker: str, media_type: MediaType
) -> None:
    path = tmp_path / "laughs"
    path.write_bytes(with_entity(build(), part, marker, LAUGHS, "&lol6;"))
    assert "lollollol" not in parsed_text(path, media_type)
