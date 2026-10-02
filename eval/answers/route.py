"""What the chat model calls messages the search found nothing good enough for (the product's
route, answering.ROUTE_SYSTEM): every unanswerable golden question must stay ``documents``
(refused), and so must the answerable ones below the refusal threshold; greetings and questions
of general knowledge should not.

    uv run --directory backend python ../eval/answers/route.py \\
        --refusal ../eval/answers/work/refusal-questions.jsonl

``--refusal`` is refusal.py's per-question file (each question's best reranker score). The model
is asked exactly as the product asks it, through the golden stack's chat server, holding the
harness's lock (~/synapse-ci/lock) so it never runs beside a measurement. Prints, per group, how
many messages got each kind, and every one that got the wrong kind.
"""

import argparse
import fcntl
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "retrieval"))
sys.path.insert(0, str(HERE.parent / "golden"))

from score import QUESTIONS  # noqa: E402
from synapse.chat import answering  # noqa: E402

LOCK = Path.home() / "synapse-ci" / "lock"
# Runs in the API container: the chat server's address and key are there.
CALL = """
import json, sys, httpx2
key = open("/run/secrets/chat_key").read().strip()
for line in sys.stdin:
    body = json.loads(line)
    response = httpx2.post("http://llm-chat:8080/v1/chat/completions", json=body,
                           headers={"Authorization": f"Bearer {key}"}, timeout=600)
    response.raise_for_status()
    print(json.dumps(response.json()["choices"][0]["message"]["content"]), flush=True)
"""
# Messages people send that are not questions to the documents, with the kind they should get.
PROBES = [
    ("conversation", "Sen kimsin?"),
    ("conversation", "Neler yapabiliyorsun?"),
    ("conversation", "Bugün nasılsın, keyfin yerinde mi?"),
    ("conversation", "Harika bir iş çıkardın, sağ ol"),
    ("conversation", "Bana yardım edebilir misin?"),
    ("conversation", "What can you do?"),
    ("general", "Fotosentez nedir?"),
    ("general", "Python'da bir listeyi nasıl sıralarım?"),
    ("general", "1250'nin yüzde 18'i kaçtır?"),
    ("general", "Bu cümleyi İngilizceye çevir: Toplantı yarın saat onda."),
    ("general", "Resmi bir izin dilekçesi nasıl yazılır, örnek verir misin?"),
    ("general", "Enflasyon ne demek?"),
    ("general", "Excel'de DÜŞEYARA nasıl kullanılır?"),
    ("general", "What is the difference between a law and a regulation?"),
]


def body(message: str) -> str:
    return json.dumps(
        {
            "messages": [
                {"role": "system", "content": answering.ROUTE_SYSTEM},
                {"role": "user", "content": message},
            ],
            "temperature": 0,
            "max_tokens": answering.ROUTE_TOKENS,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {"schema": answering.ROUTE_SCHEMA},
            },
        },
        ensure_ascii=False,
    )


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--refusal", type=Path, required=True)
    options.add_argument("--threshold", type=float, default=1.0)
    options.add_argument("--container", default="synapse-golden-api-1")
    args = options.parse_args()
    best = {
        r["id"]: r["best"]
        for r in (json.loads(line) for line in args.refusal.read_text().splitlines())
    }
    golden = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines()]
    cases: list[tuple[str, str, str]] = []  # (group, expected kind, message)
    for question in golden:
        if question["type"] == "unanswerable":
            cases.append(("unanswerable", "documents", question["question"]))
        elif (best.get(question["id"]) or 0.0) < args.threshold:
            cases.append(("answerable, below the threshold", "documents", question["question"]))
    cases += [(f"probe: {kind}", kind, message) for kind, message in PROBES]

    LOCK.parent.mkdir(exist_ok=True)
    with LOCK.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # The command is constant; the container is this machine's own.
        replies = subprocess.run(  # noqa: S603
            ["docker", "exec", "-i", args.container, "/app/.venv/bin/python", "-c", CALL],  # noqa: S607
            input="\n".join(body(message) for _, _, message in cases) + "\n",
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()

    counts: dict[str, Counter[str]] = {}
    wrong = []
    for (group, expected, message), reply in zip(cases, replies, strict=True):
        try:
            kind = json.loads(json.loads(reply)).get("kind", "documents")
        except ValueError, AttributeError:
            kind = "documents"
        counts.setdefault(group, Counter())[kind] += 1
        if kind != expected:
            wrong.append((group, expected, kind, message))
    for group, counted in counts.items():
        print(f"{group}: {sum(counted.values())}: {dict(counted)}")
    for group, expected, kind, message in wrong:
        print(f"WRONG {group}: expected {expected}, got {kind}: {message}")


if __name__ == "__main__":
    main()
