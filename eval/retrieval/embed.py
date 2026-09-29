"""Embed the corpus chunks and the golden questions with one model (README.md).

    uv run --project eval/retrieval python eval/retrieval/embed.py MODEL [--parser light]
                                   [--threads 6] [--speed N] [--questions-only]
                                   [--backend torch|onnx|onnx-int8]

Runs in the environment of eval/retrieval/pyproject.toml, not the backend's. Reads
work/chunks-<parser>.jsonl (chunks.py) and eval/golden/questions.jsonl; writes, under
work/emb/<parser>/<MODEL>/, the unit-length vectors of the chunks and of the questions
(float32 .npy, in file order) and meta.json: the model's revision, the dimension, the seconds
to embed the corpus, the median milliseconds to embed one question alone, the process's peak
memory and the questions' SHA-256 (score.py refuses vectors of an older question set).

``--questions-only`` embeds the questions again after they changed, keeping the corpus's
vectors. ``--speed N`` only times N chunks drawn with a fixed seed and one question at a time,
and writes nothing: a full corpus takes up to hours per model, so speed is compared that way,
with nothing else running.

``--backend onnx`` runs the model's published ONNX graph on ONNX Runtime, ``onnx-int8`` the
same with its weights quantised to 8 bits (onnx_encoder.py); vectors go to
work/emb/<parser>/<MODEL>@<backend>/.

Every candidate's licence is allowed by ADR 0016 without review, and none needs remote code.
"""

import argparse
import hashlib
import json
import random
import resource
import statistics
import time
from pathlib import Path

import numpy as np
import torch
from huggingface_hub import try_to_load_from_cache
from onnx_encoder import OnnxEncoder
from sentence_transformers import SentenceTransformer

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
QUESTIONS = HERE.parent / "golden" / "questions.jsonl"
MAX_TOKENS = 512
TIMED_QUERIES = 50

# Prefixes as each model card prescribes for retrieval.
MODELS = {
    "e5-small": ("intfloat/multilingual-e5-small", "query: ", "passage: "),
    "e5-base": ("intfloat/multilingual-e5-base", "query: ", "passage: "),
    "e5-large": ("intfloat/multilingual-e5-large", "query: ", "passage: "),
    "bge-m3": ("BAAI/bge-m3", "", ""),
    "granite-278m": ("ibm-granite/granite-embedding-278m-multilingual", "", ""),
    "qwen3-0.6b": (
        "Qwen/Qwen3-Embedding-0.6B",
        "Instruct: Given a question, retrieve the passages that answer it\nQuery:",
        "",
    ),
}


# The ONNX graph each model publishes (there is none for qwen3-0.6b).
ONNX_FILES = {
    "e5-small": "onnx/model.onnx",
    "e5-base": "onnx/model.onnx",
    "e5-large": "onnx/model.onnx",
    "bge-m3": "onnx/model.onnx",
    "granite-278m": "model.onnx",
}


def revision(name: str) -> str:
    """The Hugging Face commit the cached weights came from (the snapshot's directory name)."""
    cached = try_to_load_from_cache(name, "config.json")
    return Path(cached).parent.name if isinstance(cached, str) else "unknown"


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("model", choices=sorted(MODELS))
    options.add_argument("--parser", default="light")
    options.add_argument("--threads", type=int, default=6)
    options.add_argument("--speed", type=int, default=0)
    options.add_argument("--questions-only", action="store_true")
    options.add_argument("--backend", choices=["torch", "onnx", "onnx-int8"], default="torch")
    args = options.parse_args()
    torch.set_num_threads(args.threads)
    name, query_prefix, passage_prefix = MODELS[args.model]
    chunks = [
        json.loads(line)
        for line in (WORK / f"chunks-{args.parser}.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    questions = [
        json.loads(line)
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    model: SentenceTransformer | OnnxEncoder
    if args.backend == "torch":
        model = SentenceTransformer(name, device="cpu")
        model.max_seq_length = MAX_TOKENS
    else:
        model = OnnxEncoder(
            name,
            ONNX_FILES[args.model],
            int8=args.backend == "onnx-int8",
            threads=args.threads,
            max_tokens=MAX_TOKENS,
        )
    if args.speed:
        speed(model, args, chunks, questions)
        return
    run = args.model if args.backend == "torch" else f"{args.model}@{args.backend}"
    out = WORK / "emb" / args.parser / run
    out.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(QUESTIONS.read_bytes()).hexdigest()
    if args.questions_only:
        queries = model.encode(
            [query_prefix + q["question"] for q in questions],
            batch_size=16,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        np.save(out / "questions.npy", queries.astype(np.float32))
        meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
        meta["questions_sha256"] = digest
        (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        print(json.dumps({"model": name, "questions": len(questions), "sha256": digest[:12]}))
        return

    started = time.perf_counter()
    passages = model.encode(
        [passage_prefix + c["text"] for c in chunks],
        batch_size=16,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    seconds = time.perf_counter() - started
    queries = model.encode(
        [query_prefix + q["question"] for q in questions],
        batch_size=16,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    single = []
    for q in questions[:TIMED_QUERIES]:
        tick = time.perf_counter()
        model.encode([query_prefix + q["question"]], normalize_embeddings=True)
        single.append((time.perf_counter() - tick) * 1000)

    np.save(out / "chunks.npy", passages.astype(np.float32))
    np.save(out / "questions.npy", queries.astype(np.float32))
    meta = {
        "model": name,
        "revision": revision(name),
        "dimension": int(passages.shape[1]),
        "chunks": len(chunks),
        "seconds": round(seconds, 1),
        "chunks_per_second": round(len(chunks) / seconds, 2),
        "query_ms_median": round(statistics.median(single), 1),
        "threads": args.threads,
        "backend": args.backend,
        "peak_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
        "questions_sha256": digest,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta))


def speed(
    model: SentenceTransformer | OnnxEncoder,
    args: argparse.Namespace,
    chunks: list[dict[str, str]],
    questions: list[dict[str, str]],
) -> None:
    _, query_prefix, passage_prefix = MODELS[args.model]
    sample = random.Random(7).sample(chunks, args.speed)
    texts = [passage_prefix + c["text"] for c in sample]
    model.encode(texts[:16], batch_size=16)  # warm-up
    started = time.perf_counter()
    model.encode(texts, batch_size=16, normalize_embeddings=True)
    seconds = time.perf_counter() - started
    single = []
    for q in questions[:TIMED_QUERIES]:
        tick = time.perf_counter()
        model.encode([query_prefix + q["question"]], normalize_embeddings=True)
        single.append((time.perf_counter() - tick) * 1000)
    tokens = sum(
        len(model.tokenizer(t, truncation=True, max_length=MAX_TOKENS)["input_ids"]) for t in texts
    )
    result = {
        "model": MODELS[args.model][0],
        "chunks": args.speed,
        "mean_tokens": round(tokens / args.speed),
        "chunks_per_second": round(args.speed / seconds, 2),
        "query_ms_median": round(statistics.median(single), 1),
        "threads": args.threads,
        "backend": args.backend,
        "peak_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
