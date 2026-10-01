"""The golden set against the product's own search, end to end (phase 4, step 7).

    uv run --directory backend python ../eval/retrieval/product.py upload --base URL \\
        --email EDITOR --password-file FILE
    uv run --directory backend python ../eval/retrieval/product.py score --base URL \\
        --email EDITOR --password-file FILE [--questions FILE]

A running stack (deploy/compose.stack.yml with the model servers) does the work, through its
API as an editor would:

- ``upload``: every corpus document in a format the product reads (eval/corpus/manifest.csv),
  under the name it was published with (so its context is the benchmark's), into a collection
  of its own; then waits until every version is ``ready`` or ``failed``, or nothing has moved
  for ten minutes. The corpus id of each document goes to work/product/documents.json.
- ``score``: each question through ``POST /api/search``, once for the fused first stage and once
  reranked, its hits mapped back to (corpus document, pages) and scored as score.py scores a
  run: Hit@1, Hit@10 and MRR@10 per question type, with the median seconds of a search.
  Every answer goes to work/product/<questions>.jsonl.

The product also reads the pages the benchmark's chunks leave out (those that need OCR), so it
searches more chunks than score.py's runs do.
"""

import argparse
import csv
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx2

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from score import QUESTIONS, TYPES, WORK, Golden, metrics  # noqa: E402

CORPUS = HERE.parent / "corpus"
OUT = WORK / "product"
FORMATS = {"PDF", "DOCX", "XLSX", "PPTX"}
DONE = {"ready", "failed"}
QUIET_SECONDS = 600


def signed_in(base: str, email: str, password: str) -> httpx2.Client:
    client = httpx2.Client(base_url=base, timeout=600, headers={"X-Synapse-Client": "web"})
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    client.headers["X-Synapse-CSRF"] = response.json()["csrf_token"]
    # The session cookie is Secure; the stack is reached over plain HTTP on loopback, where the
    # cookie jar would not send it back, so it goes as a header.
    client.headers["Cookie"] = "; ".join(f"{c.name}={c.value}" for c in response.cookies.jar)
    client.cookies.clear()
    return client


def upload(client: httpx2.Client) -> None:
    with (CORPUS / "manifest.csv").open(encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row["format"] in FORMATS]
    collection = client.post(
        "/api/admin/collections", json={"name": f"Golden corpus {time.strftime('%H%M%S')}"}
    )
    collection.raise_for_status()
    collection_id = collection.json()["id"]
    documents = {}
    for row in rows:
        name = Path(unquote(urlparse(row["source_url"]).path)).name
        data = (CORPUS / "files" / f"{row['id']}.{row['format'].lower()}").read_bytes()
        response = client.post(
            f"/api/collections/{collection_id}/documents", params={"filename": name}, content=data
        )
        if response.status_code != 201:  # noqa: PLR2004
            print(f"{row['id']}: {response.status_code} {response.text[:200]}")
            continue
        documents[response.json()["id"]] = row["id"]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "documents.json").write_text(
        json.dumps({"collection": collection_id, "documents": documents}, indent=1),
        encoding="utf-8",
    )
    print(f"uploaded {len(documents)} of {len(rows)}")
    wait(client, collection_id, len(documents))


def wait(client: httpx2.Client, collection_id: str, expected: int) -> None:
    started, last, last_change = time.monotonic(), None, time.monotonic()
    while True:
        listed = client.get(f"/api/collections/{collection_id}/documents").json()
        statuses: dict[str, int] = defaultdict(int)
        for document in listed:
            statuses[document["status"]] += 1
        summary = dict(sorted(statuses.items()))
        if summary != last:
            last, last_change = summary, time.monotonic()
            minutes = (time.monotonic() - started) / 60
            print(f"{minutes:6.1f} min {summary}", flush=True)
        if sum(statuses[s] for s in DONE) == expected:
            return
        if time.monotonic() - last_change > QUIET_SECONDS:
            print("nothing moved for ten minutes; scoring what is there")
            return
        time.sleep(30)


def score(client: httpx2.Client, questions_file: Path) -> None:
    mapping = json.loads((OUT / "documents.json").read_text(encoding="utf-8"))["documents"]
    questions = [
        json.loads(line)
        for line in questions_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ranks: dict[str, dict[str, list[int | None]]] = {
        "fused": defaultdict(list),
        "reranked": defaultdict(list),
    }
    seconds: dict[str, list[float]] = {"fused": [], "reranked": []}
    out = (OUT / f"{questions_file.stem}.jsonl").open("w", encoding="utf-8")
    for question in questions:
        if question["type"] == "unanswerable":
            continue
        golden = Golden(question)
        record: dict[str, Any] = {"id": question["id"], "type": question["type"]}
        for stage, rerank in (("fused", False), ("reranked", True)):
            started = time.perf_counter()
            response = client.post(
                "/api/search", json={"query": question["question"], "limit": 10, "rerank": rerank}
            )
            response.raise_for_status()
            seconds[stage].append(time.perf_counter() - started)
            body = response.json()
            hits = [
                {
                    "doc": mapping.get(hit["document_id"]),
                    "pages": [hit["page_start"], hit["page_end"]],
                }
                for hit in body["hits"]
            ]
            rank = golden.rank(list(range(len(hits))), hits)
            ranks[stage][question["type"]].append(rank)
            ranks[stage]["all"].append(rank)
            record[stage] = {"rank": rank, "hits": hits, "warnings": body["warnings"]}
        out.write(json.dumps(record, ensure_ascii=False) + "\n")
    out.close()
    print(
        f"{'stage':<10}"
        + "".join(f"{t[:10]:>12}" for t in (*TYPES, "all"))
        + f"{'mrr':>8}{'s/search':>10}"
    )
    for stage, by_type in ranks.items():
        cells = "".join(
            f"{metrics(by_type[t])['hit@1']:>6.2f}/{metrics(by_type[t])['hit@10']:.2f}"
            for t in (*TYPES, "all")
        )
        median = statistics.median(seconds[stage])
        print(f"{stage:<10}{cells}{metrics(by_type['all'])['mrr']:>8.3f}{median:>10.2f}")


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("action", choices=["upload", "score"])
    options.add_argument("--base", required=True)
    options.add_argument("--email", required=True)
    options.add_argument("--password-file", type=Path, required=True)
    options.add_argument("--questions", type=Path, default=QUESTIONS)
    args = options.parse_args()
    password = args.password_file.read_text(encoding="utf-8").strip()
    client = signed_in(args.base, args.email, password)
    try:
        if args.action == "upload":
            upload(client)
        else:
            score(client, args.questions)
    finally:
        client.close()


if __name__ == "__main__":
    main()
