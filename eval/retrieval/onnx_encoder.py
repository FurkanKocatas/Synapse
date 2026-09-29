"""A sentence encoder on ONNX Runtime, full precision or int8 (embed.py ``--backend``).

What an ONNX Runtime adapter for the ``Embedder`` port (ADR 0009) would do, without the
sentence-transformers wrapper: the model's tokenizer, its ONNX graph, its own pooling (the CLS
token or the mean of the tokens, as its sentence-transformers configuration says) and unit
length. ``int8`` quantises the weights once, dynamically, to signed 8-bit per channel with
their range reduced to 7 bits, into work/onnx/. Without the reduced range (the recipe optimum
calls "avx2"), a CPU with AVX2 but no VNNI (the reference machine's) overflows in the 8-bit
products: base-sized models' vectors fell to cosine 0.90 and 0.84 of full precision, and their
retrieval with them.
"""

import json
import shutil
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


def materialise(folder: Path, onnx_file: str, slug: str) -> Path:
    """A graph with its weights in a separate file, copied out of the Hugging Face cache:
    there both are symbolic links into a blob store, and ONNX Runtime refuses external data
    outside the model's own directory."""
    source = folder / onnx_file
    data = source.with_name(source.name + "_data")
    if not data.exists():
        return source
    target = WORK / "onnx" / slug / source.name
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(data.resolve(), target.with_name(data.name))
        shutil.copyfile(source.resolve(), target)
    return target


class OnnxEncoder:
    def __init__(
        self, name: str, onnx_file: str, *, int8: bool, threads: int, max_tokens: int
    ) -> None:
        folder = snapshot(name)
        slug = name.replace("/", "--")
        path = materialise(folder, onnx_file, slug)
        if int8:
            path = quantised(path, slug)
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


def quantised(path: Path, slug: str) -> Path:
    """The graph's weights to signed 8 bits per channel, range reduced to 7 (see above)."""
    target = WORK / "onnx" / f"{slug}-int8-reduced.onnx"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        quantize_dynamic(
            path, target, weight_type=QuantType.QInt8, per_channel=True, reduce_range=True
        )
    return target


class OnnxCrossEncoder:
    """A reranker on ONNX Runtime. No ONNX graph is published for the candidates, so the
    PyTorch weights are exported once (work/onnx/<model>/model.onnx)."""

    def __init__(self, name: str, *, int8: bool, threads: int, max_tokens: int) -> None:
        slug = name.replace("/", "--")
        path = WORK / "onnx" / slug / "model.onnx"
        if not path.exists():
            export_cross_encoder(name, path)
        if int8:
            path = quantised(path, slug)
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.tokenizer = AutoTokenizer.from_pretrained(name)
        self.max_tokens = max_tokens

    def predict(self, pairs: list[tuple[str, str]], **_: Any) -> np.ndarray:
        encoded = self.tokenizer(
            [q for q, _ in pairs],
            [d for _, d in pairs],
            padding=True,
            truncation=True,
            max_length=self.max_tokens,
            return_tensors="np",
        )
        feed = {k: v.astype(np.int64) for k, v in encoded.items() if k in self.inputs}
        logits: np.ndarray = self.session.run(None, feed)[0]
        return logits[:, 0]


def export_cross_encoder(name: str, path: Path) -> None:
    import torch  # noqa: PLC0415  (only to export once)
    from transformers import AutoModelForSequenceClassification  # noqa: PLC0415

    model = AutoModelForSequenceClassification.from_pretrained(name).eval()
    tokenizer = AutoTokenizer.from_pretrained(name)
    sample = tokenizer(["soru"], ["belge metni"], return_tensors="pt")
    path.parent.mkdir(parents=True, exist_ok=True)
    axes = {0: "batch", 1: "tokens"}
    torch.onnx.export(
        model,
        (sample["input_ids"], sample["attention_mask"]),
        str(path),
        input_names=["input_ids", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={"input_ids": axes, "attention_mask": axes, "logits": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
