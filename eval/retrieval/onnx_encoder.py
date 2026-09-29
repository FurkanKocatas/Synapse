"""A sentence encoder on ONNX Runtime, full precision or int8 (embed.py ``--backend``).

What an ONNX Runtime adapter for the ``Embedder`` port (ADR 0009) would do, without the
sentence-transformers wrapper: the model's tokenizer, its ONNX graph, its own pooling (the CLS
token or the mean of the tokens, as its sentence-transformers configuration says) and unit
length. ``int8`` quantises the weights once, dynamically, with the recipe optimum calls
"avx2" (signed 8-bit weights per channel), into work/onnx/.
"""

import json
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from huggingface_hub import try_to_load_from_cache
from onnxruntime.quantization import QuantType, quantize_dynamic
from transformers import AutoTokenizer

WORK = Path(__file__).resolve().parent / "work"


def snapshot(name: str) -> Path:
    cached = try_to_load_from_cache(name, "config.json")
    if not isinstance(cached, str):
        raise SystemExit(f"{name} is not in the Hugging Face cache; run embed.py once online")
    return Path(cached).parent


class OnnxEncoder:
    def __init__(
        self, name: str, onnx_file: str, *, int8: bool, threads: int, max_tokens: int
    ) -> None:
        folder = snapshot(name)
        path = folder / onnx_file
        if int8:
            target = WORK / "onnx" / f"{name.replace('/', '--')}-int8.onnx"
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                quantize_dynamic(path, target, weight_type=QuantType.QInt8, per_channel=True)
            path = target
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.tokenizer = AutoTokenizer.from_pretrained(name)
        self.max_tokens = max_tokens
        pooling = json.loads((folder / "1_Pooling" / "config.json").read_text(encoding="utf-8"))
        self.cls = bool(pooling.get("pooling_mode_cls_token"))

    def encode(self, texts: list[str], batch_size: int = 16, **_: Any) -> np.ndarray:
        """Unit-length vectors in the given order (longest first inside, so batches pad to
        similar lengths). A graph whose first output is already one vector per text is used
        as it is; otherwise its token states are pooled."""
        order = sorted(range(len(texts)), key=lambda i: -len(texts[i]))
        out = np.zeros((len(texts), 0), np.float32)
        for start in range(0, len(order), batch_size):
            batch = order[start : start + batch_size]
            encoded = self.tokenizer(
                [texts[i] for i in batch],
                padding=True,
                truncation=True,
                max_length=self.max_tokens,
                return_tensors="np",
            )
            feed = {k: v.astype(np.int64) for k, v in encoded.items() if k in self.inputs}
            if "token_type_ids" in self.inputs and "token_type_ids" not in feed:
                # XLM-R's tokenizer has no segments; graphs exported from BERT code ask for them.
                feed["token_type_ids"] = np.zeros_like(feed["input_ids"])
            first = self.session.run(None, feed)[0]
            if first.ndim == 2:  # noqa: PLR2004  (batch, dimension): pooled already
                pooled = first
            elif self.cls:
                pooled = first[:, 0]
            else:
                mask = encoded["attention_mask"][..., None].astype(np.float32)
                pooled = (first * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1e-9)
            pooled = pooled / np.linalg.norm(pooled, axis=1, keepdims=True)
            if out.shape[1] == 0:
                out = np.zeros((len(texts), pooled.shape[1]), np.float32)
            out[batch] = pooled
        return out
