"""The text the product gave the corpus's pages that went to OCR, read from a stack's database: the
pages the scanned-document questions (scanned.jsonl) were written from and are checked against
(check.py --ocr-pages).

    python eval/golden/ocr_pages.py [--project synapse-golden] [--documents FILE] [--out FILE]

Read only (one SELECT as the database's owner, through ``docker exec``). The text stays under
eval/golden/work/, which is not committed: the scanned council minutes name officials.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCUMENTS = HERE.parent / "retrieval" / "work" / "product" / "documents.json"
OUT = HERE / "work" / "ocr-pages.jsonl"
# The current version of every document, each of its pages that needed OCR.
QUERY = """
SELECT json_build_object(
    'document_id', v.document_id, 'page', p.number, 'text_source', p.text_source,
    'engine', p.ocr_engine, 'extra_identifiers', p.extra_identifiers,
    'uncertain_identifiers', p.uncertain_identifiers, 'text', p.text)
FROM synapse.document_pages p
JOIN synapse.document_versions v ON v.tenant_id = p.tenant_id AND v.id = p.version_id
WHERE p.needs_ocr AND v.version = (
    SELECT max(w.version) FROM synapse.document_versions w
    WHERE w.tenant_id = v.tenant_id AND w.document_id = v.document_id)
ORDER BY v.document_id, p.number
"""


def main() -> int:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--project", default="synapse-golden")
    options.add_argument("--documents", type=Path, default=DOCUMENTS)
    options.add_argument("--out", type=Path, default=OUT)
    args = options.parse_args()
    corpus = json.loads(args.documents.read_text(encoding="utf-8"))["documents"]
    command = ["docker", "exec", f"{args.project}-db-1", "psql", "-U", "postgres", "-d", "synapse"]
    result = subprocess.run(  # noqa: S603  (fixed program; the project name is the operator's)
        [*command, "-At", "-v", "ON_ERROR_STOP=1", "-c", QUERY],
        capture_output=True,
        text=True,
        check=True,
    )
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in rows:
            row["doc"] = corpus.get(row.pop("document_id"))
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    engines = sorted({str(r["engine"]) for r in rows})
    print(f"{len(rows)} pages from {len({r['doc'] for r in rows})} documents; engines {engines}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
