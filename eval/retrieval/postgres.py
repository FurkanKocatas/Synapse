"""The benchmark's lexical and dense runs from PostgreSQL, as the product will query it (step 7).

    uv run --directory backend python ../eval/retrieval/postgres.py [--parser light-context]
        [--model bge-m3@llama-vulkan-q8_0] [--questions FILE] [--conninfo-file FILE] [--reload]

Loads work/chunks-<parser>.jsonl into a database of its own (``synapse_eval``, on the server
``--conninfo-file`` names: by default the development database's superuser), each chunk as the
product indexes it: its lexical terms (knowledge/search.py, ``lexical_text``: five-letter
prefixes and whole identifiers, Turkish-lower-cased) in a BM25 index of pg_textsearch on the
``simple`` configuration, and the model's vectors at 16 bits with HNSW. Each question, turned
into terms the same way, gets its top 50 from each index and their reciprocal rank fusion. The
runs go to work/runs/<parser>[-<stem>]/extra/ as ``pg-bm25``, ``pg-dense`` and ``pg-rrf``, which
score.py scores next to the in-memory runs they should match, with the median milliseconds per
query.
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import psycopg
from psycopg import sql
from synapse.knowledge.search import lexical_text

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from score import CANDIDATES, QUESTIONS, WORK, fuse  # noqa: E402

DATABASE = "synapse_eval"
CONNINFO = HERE.parent.parent / ".dev" / "secrets" / "admin_conninfo"
# HNSW returns at most ef_search rows; the default (40) is below the 50 candidates.
EF_SEARCH = 200


def connect(conninfo: str, dbname: str) -> psycopg.Connection:
    return psycopg.connect(conninfo, dbname=dbname, autocommit=True)


def load(conninfo: str, texts: list[str], vectors: np.ndarray, *, reload: bool) -> None:
    with connect(conninfo, "postgres") as admin:
        exists = admin.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,)
        ).fetchone()
        if not exists:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE)))
    with connect(conninfo, DATABASE) as db:
        db.execute("CREATE EXTENSION IF NOT EXISTS vector")
        db.execute("CREATE EXTENSION IF NOT EXISTS pg_textsearch")
        db.execute(
            "CREATE TABLE IF NOT EXISTS chunks (id integer PRIMARY KEY, search text NOT NULL, "
            f"embedding halfvec({vectors.shape[1]}) NOT NULL)"
        )
        count = db.execute("SELECT count(*) FROM chunks").fetchone()
        if not reload and count == (len(texts),):
            return
        db.execute("DROP INDEX IF EXISTS chunks_bm25")
        db.execute("DROP INDEX IF EXISTS chunks_hnsw")
        db.execute("TRUNCATE chunks")
        with db.cursor().copy("COPY chunks (id, search, embedding) FROM STDIN") as copy:
            for index, (text, vector) in enumerate(zip(texts, vectors, strict=True)):
                literal = "[" + ",".join(f"{v:.6g}" for v in vector) + "]"
                copy.write_row((index, lexical_text(text), literal))
        started = time.perf_counter()
        db.execute(
            "CREATE INDEX chunks_bm25 ON chunks USING bm25 (search) WITH (text_config = 'simple')"
        )
        bm25_seconds = time.perf_counter() - started
        started = time.perf_counter()
        # A parallel build needs more shared memory than a development container has.
        db.execute("SET max_parallel_maintenance_workers = 0")
        db.execute("CREATE INDEX chunks_hnsw ON chunks USING hnsw (embedding halfvec_cosine_ops)")
        print(
            json.dumps(
                {
                    "chunks": len(texts),
                    "bm25_index_seconds": round(bm25_seconds, 1),
                    "hnsw_index_seconds": round(time.perf_counter() - started, 1),
                }
            )
        )


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--parser", default="light-context")
    options.add_argument("--model", default="bge-m3@llama-vulkan-q8_0")
    options.add_argument("--questions", type=Path, default=QUESTIONS)
    options.add_argument("--conninfo-file", type=Path, default=CONNINFO)
    options.add_argument("--reload", action="store_true")
    args = options.parse_args()
    conninfo = args.conninfo_file.read_text(encoding="utf-8").strip()
    texts = [
        json.loads(line)["text"]
        for line in (WORK / f"chunks-{args.parser}.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    vectors_dir = WORK / "emb" / args.parser / args.model
    load(conninfo, texts, np.load(vectors_dir / "chunks.npy"), reload=args.reload)

    questions = [
        json.loads(line)["question"]
        for line in args.questions.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    runs = WORK / "runs" / args.parser
    vectors_file = "questions.npy"
    if args.questions != QUESTIONS:
        runs = WORK / "runs" / f"{args.parser}-{args.questions.stem}"
        vectors_file = f"questions-{args.questions.stem}.npy"
    query_vectors = np.load(vectors_dir / vectors_file)

    lexical, dense, seconds = [], [], {"bm25": [], "dense": []}
    with connect(conninfo, DATABASE) as db:
        db.execute(f"SET hnsw.ef_search = {EF_SEARCH}")
        for question, vector in zip(questions, query_vectors, strict=True):
            started = time.perf_counter()
            rows = db.execute(
                "SELECT id FROM chunks ORDER BY search <@> to_bm25query(%s, 'chunks_bm25') "
                "LIMIT %s",
                (lexical_text(question), CANDIDATES),
            ).fetchall()
            seconds["bm25"].append(time.perf_counter() - started)
            lexical.append([row[0] for row in rows])
            literal = "[" + ",".join(f"{v:.6g}" for v in vector) + "]"
            started = time.perf_counter()
            rows = db.execute(
                "SELECT id FROM chunks ORDER BY embedding <=> %s::halfvec LIMIT %s",
                (literal, CANDIDATES),
            ).fetchall()
            seconds["dense"].append(time.perf_counter() - started)
            dense.append([row[0] for row in rows])
    (runs / "extra").mkdir(parents=True, exist_ok=True)
    for name, rankings in (
        ("pg-bm25", lexical),
        ("pg-dense", dense),
        ("pg-rrf", [fuse(a, b) for a, b in zip(lexical, dense, strict=True)]),
    ):
        (runs / "extra" / f"{name}.json").write_text(
            json.dumps({"rankings": rankings}), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "questions": len(questions),
                **{
                    f"{k}_ms_median": round(statistics.median(v) * 1000, 1)
                    for k, v in seconds.items()
                },
            }
        )
    )


if __name__ == "__main__":
    main()
