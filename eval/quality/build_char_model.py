"""Build the character trigram model used by the page quality check.

Training text: every born-digital PDF in the evaluation corpus (typeset Turkish, with the
English references some of them carry). Scanned PDFs are left out, since their text layers are
exactly what the check must catch. Only counts of three-letter sequences are kept, not text.

Usage (from the repository root, after eval/corpus/fetch.py):
    uv run --directory backend python ../eval/quality/build_char_model.py
"""

import csv
import json
from pathlib import Path

from synapse.knowledge.filetypes import MediaType
from synapse.knowledge.parsing import LightParser
from synapse.knowledge.quality import CharModel, build_model

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "eval" / "corpus"
OUTPUT = ROOT / "backend" / "src" / "synapse" / "knowledge" / "data" / "tr_char_trigrams.json"


def pdf_rows() -> list[dict[str, str]]:
    with (CORPUS / "manifest.csv").open(encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row["format"] == "PDF"]


def born_digital(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row["is_scanned"] == "no"]


def page_texts(row: dict[str, str]) -> list[str]:
    parsed = LightParser().parse(CORPUS / "files" / f"{row['id']}.pdf", MediaType.PDF)
    return [page.text for page in parsed.pages]


def train(rows: list[dict[str, str]]) -> CharModel:
    return build_model([text for row in rows for text in page_texts(row)])


def main() -> None:
    rows = born_digital(pdf_rows())
    model = train(rows)
    OUTPUT.write_text(
        json.dumps(
            {
                "source": f"eval/quality/build_char_model.py over {len(rows)} born-digital PDFs",
                "alphabet_size": model.alphabet_size,
                "bigrams": dict(sorted(model.bigrams.items())),
                "trigrams": dict(sorted(model.trigrams.items())),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{len(rows)} documents, {len(model.trigrams)} trigrams -> {OUTPUT}")


if __name__ == "__main__":
    main()
