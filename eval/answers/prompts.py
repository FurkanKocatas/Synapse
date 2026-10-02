"""The answer prompt's variants against each other, on the questions they are meant to change.

    uv run --directory backend python ../eval/answers/prompts.py --base URL --email EDITOR \\
        --password-file FILE --answers ANSWERS_JSONL \\
        [--sample 20] [--variants current,strict] [--container synapse-golden-api-1]

A quicker loop than the whole harness (eval/harness/, two hours) for a change to the prompt:
each question is searched once through the stack's ``POST /api/search``, its context assembled
and its prompt written by the product's own functions (synapse.chat.answering), and the prompt
of every variant sent to the stack's chat server, through the API container, which has its
address and key. The questions come from a harness run's answers.jsonl (``--answers``): the
answerable ones the model refused, every unanswerable one, and ``--sample`` answered correctly
(fixed seed), to see what a variant breaks as well as what it mends. A variant changes the
product's sentence on when to refuse (``answering.WHEN_TO_REFUSE``).

Scored like the product: no answer when the model says the sources do not suffice or answers
"bulunamadı"; correct when the golden answer is in the answer (numbers read as numbers).
Verification is not applied (the retry would only blur what the prompt does). Takes the
harness's lock (~/synapse-ci/lock), so it never runs beside a measurement.

Writes eval/answers/work/prompts-<variant>.jsonl and prints, per variant: answerable refused,
answerable correct, unanswerable refused, on each group of questions.
"""

import argparse
import fcntl
import json
import random
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "retrieval"))
sys.path.insert(0, str(HERE.parent / "golden"))

from check import fold  # noqa: E402
from product import signed_in  # noqa: E402
from score import QUESTIONS  # noqa: E402
from synapse.chat import answering  # noqa: E402
from synapse.chat.numerals import numeric  # noqa: E402
from synapse.knowledge.public import Hit  # noqa: E402

LOCK = Path.home() / "synapse-ci" / "lock"
OUT = HERE / "work"
VARIANTS = {
    "current": answering.SYSTEM,
    # Until 2026-10-02: the model refused answerable questions whose answer stood in its
    # sources, a detail of the question missing from them.
    "strict": answering.SYSTEM.replace(
        answering.WHEN_TO_REFUSE,
        "Kaynaklar soruyu cevaplamaya yetmiyorsa sufficient alanını false yap ve tek cümle olarak "
        "'Belgelerde bulunamadı.' yaz. ",
    ),
    # The current prompt, and tables read by their row and column headings.
    "tables": answering.SYSTEM.replace(
        answering.WHEN_TO_REFUSE,
        "Sorulan bilgi kaynaklarda açıkça yazıyorsa, sorudaki her ayrıntı kaynaklarda geçmese de "
        "cevapla. Tablolarda değeri, sorudaki satır ve sütun başlıklarının kesiştiği hücreden al. "
        "Sorulan bilginin kendisi kaynaklarda yoksa sufficient alanını false yap ve tek cümle "
        "olarak 'Belgelerde bulunamadı.' yaz. ",
    ),
}
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


def hit(source: dict[str, Any]) -> Hit:
    return Hit(
        document_id=UUID(source["document_id"]),
        title=source["title"],
        version_id=uuid4(),
        version=source["version"],
        ordinal=0,
        kind=source["kind"],
        heading_path=tuple(source["heading_path"]),
        text=source["text"],
        page_start=source["page_start"],
        page_end=source["page_end"],
        context="",
        lexical_rank=None,
        dense_rank=None,
    )


def choose(answers: Path, sample: int) -> dict[str, str]:
    """Question id to its group: refused, unanswerable or answered."""
    records = [json.loads(line) for line in answers.read_text(encoding="utf-8").splitlines()]
    groups = dict.fromkeys(
        (r["id"] for r in records if r["type"] == "unanswerable"), "unanswerable"
    )
    answerable = [r for r in records if r["type"] != "unanswerable"]
    groups |= {r["id"]: "refused" for r in answerable if r["status"] != "answered"}
    right = sorted(r["id"] for r in answerable if r["correct"])
    picked = random.Random(7).sample(right, min(sample, len(right)))  # noqa: S311  (a sample)
    groups |= dict.fromkeys(picked, "answered")
    return groups


def correct(question: dict[str, Any], text: str) -> bool:
    folded = numeric(fold(text))
    parts = question.get("answer_parts") or [question.get("answer", "")]
    return all(numeric(fold(part)) in folded for part in parts)


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--base", required=True)
    options.add_argument("--email", required=True)
    options.add_argument("--password-file", type=Path, required=True)
    options.add_argument("--answers", type=Path, required=True)
    options.add_argument("--sample", type=int, default=20)
    options.add_argument("--variants", default=",".join(VARIANTS))
    options.add_argument("--container", default="synapse-golden-api-1")
    args = options.parse_args()
    variants = args.variants.split(",")
    groups = choose(args.answers, args.sample)
    questions = [
        q
        for q in (json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines())
        if q["id"] in groups
    ]
    LOCK.parent.mkdir(exist_ok=True)
    with LOCK.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        client = signed_in(args.base, args.email, args.password_file.read_text().strip())
        bodies, keys = [], []
        try:
            for question in questions:
                response = client.post(
                    "/api/search", json={"query": question["question"], "limit": 15}
                )
                response.raise_for_status()
                context = answering.assemble([hit(h) for h in response.json()["hits"]])
                if not context:
                    continue
                for variant in variants:
                    messages = answering.prompt(question["question"], context)
                    body = {
                        "messages": [
                            {"role": "system", "content": VARIANTS[variant]},
                            {"role": "user", "content": messages[1].content},
                        ],
                        "temperature": 0,
                        "max_tokens": answering.ANSWER_TOKENS,
                        "chat_template_kwargs": {"enable_thinking": False},
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {"schema": answering.schema(len(context))},
                        },
                    }
                    bodies.append(json.dumps(body, ensure_ascii=False))
                    keys.append((question, variant))
        finally:
            client.close()
        # The command is constant; the container is this machine's own.
        replies = subprocess.run(  # noqa: S603
            ["docker", "exec", "-i", args.container, "/app/.venv/bin/python", "-c", CALL],  # noqa: S607
            input="\n".join(bodies) + "\n",
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
    OUT.mkdir(exist_ok=True)
    tally: dict[tuple[str, str], list[int]] = {}
    handles = {v: (OUT / f"prompts-{v}.jsonl").open("w", encoding="utf-8") for v in variants}
    for (question, variant), raw in zip(keys, replies, strict=True):
        text, sufficient = answering.parse(json.loads(raw))
        answered = sufficient and bool(text) and answering.NOT_FOUND not in fold(text)
        right = answered and question["type"] != "unanswerable" and correct(question, text)
        group = groups[question["id"]]
        handles[variant].write(
            json.dumps(
                {
                    "id": question["id"],
                    "group": group,
                    "answered": answered,
                    "correct": right,
                    "answer": text,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        counts = tally.setdefault((variant, group), [0, 0, 0])
        counts[0] += 1
        counts[1] += answered
        counts[2] += right
    for handle in handles.values():
        handle.close()
    print(f"{'variant':<10} {'group':<13} {'n':>4} {'answered':>9} {'correct':>8}")
    for (variant, group), (n, answered_n, right_n) in sorted(tally.items()):
        print(f"{variant:<10} {group:<13} {n:>4} {answered_n:>9} {right_n:>8}")


if __name__ == "__main__":
    main()
