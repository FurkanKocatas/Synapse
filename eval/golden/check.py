"""Check the golden set against the corpus (eval/golden/README.md).

    uv run --directory backend python ../eval/golden/check.py [--questions F] [--ocr-pages F]

Every question must be well formed, and every piece of evidence must be where it says: its
quote on the stated page of the document as the light parser reads it, and the answer inside
the quotes. Evidence marked ``"ocr": true`` (the scanned-document questions, scanned.jsonl) is on
a page that goes to OCR instead, and its quote is looked for in the text the product's OCR gave
that page (ocr_pages.py writes it from a stack); without that file such quotes are counted as
unchecked, not failed. Quotes and answers are compared after the normalisation search applies
too: NFC, Turkish lower case, typographic apostrophes, quotes and dashes as plain ones, any run
of white space as one space. Prints a summary and every failure; exits 1 if there is one.
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from synapse.knowledge.filetypes import MediaType
from synapse.knowledge.parsing import LightParser, Page
from synapse.knowledge.turkish import lower

HERE = Path(__file__).resolve().parent
CORPUS = HERE.parent / "corpus"
QUESTIONS = HERE / "questions.jsonl"
OCR_PAGES = HERE / "work" / "ocr-pages.jsonl"
TYPES = {"factual", "identifier", "table", "multi_document", "unanswerable"}
MEDIA = {
    "PDF": MediaType.PDF,
    "DOCX": MediaType.DOCX,
    "XLSX": MediaType.XLSX,
    "PPTX": MediaType.PPTX,
}
ID = re.compile(r"[a-z0-9]+-\d{2,3}")
MIN_QUOTE_WORDS = 5
MAX_QUOTE_WORDS = 40
# Written as code points: the repository forbids the dashes themselves in text.
DASHES = (chr(0x2013), chr(0x2014))
PLAIN = str.maketrans(
    {chr(c): "'" for c in (0x2018, 0x2019, 0x02BC)}
    | {chr(c): '"' for c in (0x201C, 0x201D)}
    | {chr(c): "-" for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212)}
)


def fold(text: str) -> str:
    return " ".join(lower(text).translate(PLAIN).split())


@cache
def manifest() -> dict[str, dict[str, str]]:
    with (CORPUS / "manifest.csv").open(encoding="utf-8") as handle:
        return {row["id"]: row for row in csv.DictReader(handle)}


@cache
def pages(doc: str) -> dict[int, Page]:
    row = manifest()[doc]
    path = CORPUS / "files" / f"{doc}.{row['format'].lower()}"
    parsed = LightParser().parse(path, MEDIA[row["format"]])
    return {page.number: page for page in parsed.pages}


@cache
def folded(doc: str, number: int) -> str:
    return fold(pages(doc)[number].text)


@cache
def ocr_pages(path: Path) -> dict[tuple[str, int], str]:
    """Each OCR'd page's text as the product read it, folded; empty without the file."""
    if not path.exists():
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {(row["doc"], row["page"]): fold(row["text"]) for row in rows if row.get("doc")}


@dataclass
class Report:
    failures: list[str]
    unchecked: int = 0
    ocr_text: Path = OCR_PAGES

    def fail(self, question: dict[str, Any], message: str) -> None:
        self.failures.append(f"{question.get('id', '?')}: {message}")


def check_evidence(question: dict[str, Any], report: Report) -> None:
    for item in question["evidence"]:
        doc, number, quote = item.get("doc"), item.get("page"), item.get("quote", "")
        if doc not in manifest():
            report.fail(question, f"unknown document {doc}")
            continue
        if manifest()[doc]["format"] not in MEDIA:
            report.fail(question, f"{doc} is a format the parser does not read")
            continue
        if not isinstance(number, int) or number not in pages(doc):
            report.fail(question, f"{doc} has no page {number}")
            continue
        count = len(quote.split())
        if not MIN_QUOTE_WORDS <= count <= MAX_QUOTE_WORDS:
            report.fail(question, f"quote of {count} words")
        if item.get("ocr"):
            check_ocr_quote(question, doc, number, quote, report)
            continue
        if pages(doc)[number].needs_ocr:
            report.fail(question, f"{doc} page {number} goes to OCR; its text layer is no anchor")
        if fold(quote) not in folded(doc, number):
            elsewhere = [n for n in pages(doc) if fold(quote) in folded(doc, n)]
            where = f" (found on page {elsewhere[0]})" if elsewhere else ""
            report.fail(question, f"quote not on {doc} page {number}{where}")


def check_ocr_quote(
    question: dict[str, Any], doc: str, number: int, quote: str, report: Report
) -> None:
    """A quote on a page that goes to OCR: in the product's OCR text of that page."""
    if not pages(doc)[number].needs_ocr:
        report.fail(question, f"{doc} page {number} has a usable text layer; it is no OCR evidence")
        return
    texts = ocr_pages(report.ocr_text)
    if not texts:
        report.unchecked += 1
        return
    if fold(quote) not in texts.get((doc, number), ""):
        elsewhere = [n for (d, n), text in texts.items() if d == doc and fold(quote) in text]
        where = f" (found on page {elsewhere[0]})" if elsewhere else ""
        report.fail(question, f"quote not in the OCR text of {doc} page {number}{where}")


def check_answer(question: dict[str, Any], report: Report) -> None:
    quotes = [fold(item.get("quote", "")) for item in question["evidence"]]
    kind = question["type"]
    if kind == "unanswerable":
        if question["evidence"] or question.get("answer"):
            report.fail(question, "an unanswerable question has no answer and no evidence")
        return
    if not question.get("answer") or not question["evidence"]:
        report.fail(question, "an answer and its evidence are required")
        return
    if kind == "multi_document":
        parts = question.get("answer_parts", [])
        if len(parts) < 2 or len({item["doc"] for item in question["evidence"]}) < 2:  # noqa: PLR2004
            report.fail(question, "multi_document needs two answer parts from two documents")
        for part in parts:
            if not any(fold(part) in quote for quote in quotes):
                report.fail(question, f"answer part {part!r} is in no quote")
    elif not any(fold(question["answer"]) in quote for quote in quotes):
        report.fail(question, "the answer is in no quote")


def check(questions: list[dict[str, Any]], ocr_text: Path = OCR_PAGES) -> Report:
    report = Report([], ocr_text=ocr_text)
    seen: set[str] = set()
    for question in questions:
        if not ID.fullmatch(str(question.get("id", ""))) or question["id"] in seen:
            report.fail(question, "missing, malformed or repeated id")
        seen.add(str(question.get("id")))
        if question.get("type") not in TYPES or not str(question.get("question", "")).strip():
            report.fail(question, "a type from the list and a question are required")
            continue
        if any(dash in json.dumps(question, ensure_ascii=False) for dash in DASHES):
            report.fail(question, "an em or en dash")
        question.setdefault("evidence", [])
        check_evidence(question, report)
        check_answer(question, report)
    return report


def main() -> int:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--questions", type=Path, default=QUESTIONS)
    options.add_argument("--ocr-pages", type=Path, default=OCR_PAGES)
    args = options.parse_args()
    lines = args.questions.read_text(encoding="utf-8").splitlines()
    questions = [json.loads(line) for line in lines if line.strip()]
    report = check(questions, args.ocr_pages)
    by_type = Counter(q.get("type") for q in questions)
    docs = {item["doc"] for q in questions for item in q.get("evidence", [])}
    sectors = Counter(manifest()[d]["sector"] for d in docs if d in manifest())
    print(f"{len(questions)} questions: {dict(sorted(by_type.items()))}")
    print(f"evidence in {len(docs)} documents: {dict(sorted(sectors.items()))}")
    for failure in report.failures:
        print(f"  {failure}", file=sys.stderr)
    if report.unchecked:
        print(f"{report.unchecked} OCR quotes not checked: no {args.ocr_pages} (ocr_pages.py)")
    print(f"{len(report.failures)} failures")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
