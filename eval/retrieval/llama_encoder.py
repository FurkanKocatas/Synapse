"""A sentence encoder and a reranker on a llama.cpp server (``--backend llama``).

What a llama.cpp adapter for the ``Embedder`` and ``Reranker`` ports (ADR 0009) would do: the
model as GGUF on ``llama-server`` (``--embedding --pooling cls``, or ``--reranking``), on the CPU
or on a GPU through Vulkan. Texts are tokenized here with the model's own tokenizer, cut to the
same length as on the other backends and sent as token ids, so every backend reads the same
tokens. The server runs on this machine (README.md).
"""

import json
import urllib.request
from typing import Any

import numpy as np
from transformers import AutoTokenizer

# XLM-R pairs a question with a passage as <s> question </s></s> passage </s>.
PAIR_SPECIAL_TOKENS = 4


def post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=900) as response:
        reply: dict[str, Any] = json.loads(response.read())
    return reply


class LlamaEncoder:
    def __init__(self, name: str, *, url: str, max_tokens: int) -> None:
        self.tokenizer = AutoTokenizer.from_pretrained(name)
        self.url = url.rstrip("/")
        self.max_tokens = max_tokens

    def encode(self, texts: list[str], batch_size: int = 16, **_: Any) -> np.ndarray:
        """Unit-length vectors in the given order; one request per batch."""
        out = []
        for start in range(0, len(texts), batch_size):
            ids = self.tokenizer(
                texts[start : start + batch_size], truncation=True, max_length=self.max_tokens
            )["input_ids"]
            data = post(f"{self.url}/v1/embeddings", {"input": ids})["data"]
            vectors = np.array(
                [item["embedding"] for item in sorted(data, key=lambda item: item["index"])],
                np.float32,
            )
            out.append(vectors / np.linalg.norm(vectors, axis=1, keepdims=True))
        return np.concatenate(out)


class LlamaCrossEncoder:
    def __init__(self, name: str, *, url: str, max_tokens: int) -> None:
        self.tokenizer = AutoTokenizer.from_pretrained(name)
        self.url = url.rstrip("/")
        self.max_tokens = max_tokens

    def predict(self, pairs: list[tuple[str, str]], **_: Any) -> np.ndarray:
        """Scores of one question against its candidates, in one request. A passage too long
        for the pair to fit ``max_tokens`` is cut there, as the tokenizer cuts a pair's longer
        text, and sent as the text of its remaining tokens: the rerank endpoint takes text only."""
        question = pairs[0][0]
        if any(q != question for q, _ in pairs):
            raise ValueError("one question per call")
        room = self.max_tokens - PAIR_SPECIAL_TOKENS
        room -= len(self.tokenizer(question, add_special_tokens=False)["input_ids"])
        documents = []
        for _, text in pairs:
            # The model's tokenizer collapses runs of whitespace, llama.cpp's does not: a table
            # chunk with many line breaks came to 605 tokens there against 512 here.
            passage = " ".join(text.split())
            ids = self.tokenizer(passage, add_special_tokens=False)["input_ids"]
            documents.append(passage if len(ids) <= room else self.tokenizer.decode(ids[:room]))
        body = {"query": question, "documents": documents, "top_n": len(documents)}
        results = post(f"{self.url}/v1/rerank", body)["results"]
        scores = np.zeros(len(documents), np.float32)
        for item in results:
            scores[item["index"]] = item["relevance_score"]
        return scores
