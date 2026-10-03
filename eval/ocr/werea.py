"""Werea Turkish Enterprise Documents v2, test split, laid out as the OCR runners and measure.py
read a benchmark (docs/research/ocr.md, "Data for measuring").

    python eval/ocr/werea.py --source DIR --work DIR

The set (Apache-2.0, https://huggingface.co/datasets/Werea-co/werea-tr-doc-ocr-enterprise-v2)
holds 900 synthetic Turkish business documents, 12 kinds (powers of attorney, invoices, payslips,
title deeds, official letters, ...) each rendered clean, scanned or photographed. Every image is
a document of its own, so its name keeps its condition: ``truth/<stem>.txt`` is its truth (the
set's Markdown, as plain text) and ``images/<stem>.<condition>.jpg`` the page.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plaintext import plain


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--source", type=Path, required=True, help="the set's download")
    options.add_argument("--work", type=Path, required=True)
    args = options.parse_args()
    test = args.source / "test"
    (args.work / "truth").mkdir(parents=True, exist_ok=True)
    (args.work / "images").mkdir(parents=True, exist_ok=True)
    pages = []
    for line in (test / "metadata.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        stem = Path(record["file_name"]).stem
        condition = record["condition"]
        (args.work / "truth" / f"{stem}.txt").write_text(plain(record["text"]), encoding="utf-8")
        shutil.copyfile(
            test / record["file_name"], args.work / "images" / f"{stem}.{condition}.jpg"
        )
        pages.append({"name": stem, "kind": record["doc_type"], "condition": condition})
    (args.work / "pages.json").write_text(json.dumps(pages, indent=1), encoding="utf-8")
    print(len(pages), "pages")


if __name__ == "__main__":
    main()
