"""Ask the customer's questions through the installed system and write what came back.

    uv run --directory backend python ../eval/pilot/template.py questions.xlsx
    uv run --directory backend python ../eval/pilot/run.py questions.xlsx --base URL \\
        --email USER --password-file FILE [--out DIRECTORY]

Each question goes through ``POST /api/chat`` in a conversation of its own, as the page asks
it, and through ``POST /api/search`` for the first ten sources. Written to the output
directory: ``results.csv`` (every answer, its sources and its time, semicolon separated for a
Turkish Excel) and ``grading.xlsx``, the sheet the customer's lawyer grades. A question the
system did not answer is pre-graded "Reddedildi"; whether the expected document is among the
first ten sources is guessed from its file name, for the lawyer to check.
"""

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Any

import httpx2

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "answers"))
sys.path.insert(0, str(HERE.parent / "retrieval"))

from chat import ask  # noqa: E402
from product import signed_in  # noqa: E402
from sheets import Question, Result, read_questions, write_grading  # noqa: E402

TOP = 10


EXTENSION = re.compile(r"\.(pdf|docx?|xlsx?|pptx?|txt|jpe?g|png|tiff?)$", re.IGNORECASE)


def _name(text: str) -> str:
    return " ".join(EXTENSION.sub("", text.strip()).casefold().split())


def matches(expected: str, title: str) -> bool:
    """Whether a source's title is the expected document: the title is the uploaded file's name
    unless someone changed it, so either holds the other once case and extension are gone."""
    want, have = _name(expected), _name(title)
    return bool(want) and (want in have or have in want)


def _label(source: dict[str, Any]) -> str:
    start, end = source.get("page_start"), source.get("page_end")
    pages = "" if start is None else (f", s. {start}" if start == end else f", s. {start}-{end}")
    return f"{source.get('title', '')}{pages}"


def run_one(client: httpx2.Client, question: Question) -> tuple[Result, dict[str, Any]]:
    seen = ask(client, question.text)
    answer = seen.get("answer") or {"status": "failed", "text": "", "citations": []}
    sources = seen.get("sources") or []
    cited = [sources[n - 1] for n in answer.get("citations", []) if 1 <= n <= len(sources)]
    response = client.post("/api/search", json={"query": question.text, "limit": TOP})
    response.raise_for_status()
    top = response.json()["hits"][:TOP]
    in_top = any(matches(question.document, h["title"]) for h in top) if question.document else None
    result = Result(
        question=question,
        status=answer["status"],
        answer=answer.get("text", "") if answer["status"] == "answered" else "",
        sources=[_label(s) for s in (cited or sources)],
        document_in_top10=in_top,
        seconds=seen.get("seconds"),
    )
    record = {
        "first_token_seconds": seen.get("first_token_seconds"),
        "top10": " | ".join(_label(h) for h in top),
        "error": seen.get("error"),
    }
    return result, record


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("questions", type=Path)
    options.add_argument("--base", required=True)
    options.add_argument("--email", required=True)
    options.add_argument("--password-file", type=Path, required=True)
    options.add_argument("--out", type=Path, default=Path("pilot-run"))
    args = options.parse_args()
    questions = read_questions(args.questions)
    args.out.mkdir(parents=True, exist_ok=True)
    client = signed_in(args.base, args.email, args.password_file.read_text().strip())
    results = []
    with (args.out / "results.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(
            [
                "no",
                "question",
                "status",
                "answer",
                "sources",
                "expected_document",
                "document_in_top10",
                "seconds",
                "first_token_seconds",
                "top10",
                "error",
            ]
        )
        for question in questions:
            result, record = run_one(client, question)
            results.append(result)
            writer.writerow(
                [
                    question.number,
                    question.text,
                    result.status,
                    result.answer,
                    " | ".join(result.sources),
                    question.document,
                    result.document_in_top10,
                    result.seconds,
                    record["first_token_seconds"],
                    record["top10"],
                    record["error"],
                ]
            )
            handle.flush()
            print(f"{question.number:>3} {result.status:12} {result.seconds}s", flush=True)
    client.close()
    write_grading(args.out / "grading.xlsx", results)
    print(f"{len(results)} questions: {args.out / 'results.csv'}, {args.out / 'grading.xlsx'}")


if __name__ == "__main__":
    main()
