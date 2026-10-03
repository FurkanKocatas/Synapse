"""A whole-page vision-language OCR model, served by vLLM, over a benchmark's images.

    python eval/ocr/vlm.py --recipe NAME --images DIR [--images DIR] --out DIR \\
        [--base-url http://127.0.0.1:8000/v1] [--parallel 4]

Each recipe is the model card's own way of asking for a page (prompt, image size, output length);
docs/research/ocr.md lists why each model is a candidate. The server is started apart (vLLM's
``vllm serve``, see SERVE); every ``<page>.<condition>.(png|jpg)`` becomes
``<out>/<recipe>/<page>.<condition>.txt`` (the model's Markdown as plain text, plaintext.py) with
the raw reply in ``raw/`` and seconds per page in ``timings.json``. Pages already done are
skipped. Temperature 0: the same page gives the same text.
"""

import argparse
import asyncio
import base64
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plaintext import plain

IMAGES = frozenset({".png", ".jpg", ".jpeg"})
TIMEOUT = 1800


@dataclass(frozen=True)
class Recipe:
    model: str
    prompt: str
    max_tokens: int = 8192
    system: str | None = None
    # Sent with each request: the processor's image size, the chat template's switches.
    extra: dict[str, Any] = field(default_factory=dict)
    # How the server is started for it (vllm serve MODEL ...), and the name it serves it under.
    serve: tuple[str, ...] = ()
    served: str | None = None
    # The reply as plain text.
    text: Callable[[str], str] = plain


OVIS_PROMPT = (
    "\nExtract all readable content from the image in natural human reading order and output the "
    "result as a single Markdown document. For charts or images, represent them using an HTML "
    'image tag: <img src="images/bbox_{left}_{top}_{right}_{bottom}.jpg" />, where left, top, '
    "right, bottom are bounding box coordinates scaled to [0, 1000). Format formulas as LaTeX. "
    "Format tables as HTML: <table>...</table>. Transcribe all other text as standard Markdown. "
    "Preserve the original text without translation or paraphrasing."
)
# For general models, which have no OCR prompt of their own: transcription, not interpretation.
TRANSCRIBE = (
    "Transcribe all text in this document image exactly as it is written, in natural reading "
    "order, as Markdown. Write tables as HTML <table> elements. Keep every word, number, date and "
    "code character for character, in the original language and spelling; do not translate, "
    "correct, summarise or add anything. If a part is unreadable, leave it out."
)
DOTS_PROMPT = (
    "Please output the layout information from the PDF image, including each layout "
    "element's bbox, its category, and the corresponding text content within the "
    "bbox.\n"
    "\n"
    "1. Bbox format: [x1, y1, x2, y2]\n"
    "\n"
    "2. Layout Categories: The possible categories are ['Caption', 'Footnote', "
    "'Formula', 'List-item', 'Page-footer', 'Page-header', 'Picture', "
    "'Section-header', 'Table', 'Text', 'Title'].\n"
    "\n"
    "3. Text Extraction & Formatting Rules:\n"
    "    - Picture: For the 'Picture' category, the text field should be omitted.\n"
    "    - Formula: Format its text as LaTeX.\n"
    "    - Table: Format its text as HTML.\n"
    "    - All Others (Text, Title, etc.): Format their text as Markdown.\n"
    "\n"
    "4. Constraints:\n"
    "    - The output text must be the original text from the image, with no "
    "translation.\n"
    "    - All layout elements must be sorted according to human reading order.\n"
    "\n"
    "5. Final Output: The entire output must be a single JSON object.\n"
)
_TEXT_FIELD = re.compile(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"')


def layout_text(reply: str) -> str:
    """dots.mocr's layout JSON as plain text, in its reading order; when the JSON is cut off
    (the reply hit its length), the text fields it has."""
    try:
        elements = json.loads(reply)
        texts = [str(e.get("text") or "") for e in elements if e.get("category") != "Picture"]
    except ValueError, AttributeError:
        texts = [json.loads(f'"{m}"') for m in _TEXT_FIELD.findall(reply)]
    return "\n".join(plain(text) for text in texts if text)


def without_tail_loop(text: str) -> str:
    """OvisOCR2's own clean-up (its model card's ``_clean_truncated_repeats``): a reply that ran
    to its length repeating a unit of 1 to 200 characters at least 5 times keeps one."""
    n = len(text)
    if n < 8000:  # noqa: PLR2004  (the card's values throughout)
        return text
    for unit in range(1, min(200, n - 1) + 1):
        if text[n - 1] != text[n - 1 - unit]:
            continue
        match = 1
        i = n - 2
        while i >= unit and text[i] == text[i - unit]:
            match += 1
            i -= 1
        total = match + unit
        if total // unit >= 5 and total >= 100:  # noqa: PLR2004
            return text[: n - total + unit] + text[n - total % unit :]
    return text


RECIPES = {
    "ovisocr2": Recipe(
        "ATH-MaaS/OvisOCR2",
        OVIS_PROMPT,
        max_tokens=16384,
        text=lambda reply: plain(without_tail_loop(reply)),
        extra={
            "chat_template_kwargs": {"enable_thinking": False},
            "mm_processor_kwargs": {
                "images_kwargs": {"min_pixels": 448 * 448, "max_pixels": 2880 * 2880}
            },
        },
        serve=("--gpu-memory-utilization", "0.85", "--max-model-len", "24576"),
    ),
    "dots-mocr": Recipe(
        "rednote-hilab/dots.mocr",
        DOTS_PROMPT,
        max_tokens=16384,
        serve=(
            "--gpu-memory-utilization",
            "0.9",
            # The default context (131,072) leaves no room for its cache on 12 GB.
            "--max-model-len",
            "24576",
            "--chat-template-content-format",
            "string",
            "--served-model-name",
            "model",
            "--trust-remote-code",
        ),
        served="model",
        text=layout_text,
    ),
    "deepseek-ocr-2": Recipe(
        "deepseek-ai/DeepSeek-OCR-2",
        "<image>\n<|grounding|>Convert the document to markdown. ",
        serve=(
            "--trust-remote-code",
            "--gpu-memory-utilization",
            "0.9",
            "--max-model-len",
            "16384",
        ),
    ),
    # Does not fit 12 GB: 9.9 GiB of weights even in fp8, and vLLM's profiling spills into
    # system memory under WSL (shared GPU memory) and stalls.
    "qwen3-vl-8b": Recipe(
        "Qwen/Qwen3-VL-8B-Instruct",
        TRANSCRIBE,
        serve=(
            "--gpu-memory-utilization",
            "0.9",
            "--max-model-len",
            "16384",
            "--quantization",
            "fp8",
        ),
    ),
    "qwen3-vl-4b": Recipe(
        "Qwen/Qwen3-VL-4B-Instruct",
        TRANSCRIBE,
        serve=(
            "--gpu-memory-utilization",
            "0.85",
            "--max-model-len",
            "16384",
            "--quantization",
            "fp8",
        ),
    ),
}


def data_url(image: Path) -> str:
    kind = "jpeg" if image.suffix in {".jpg", ".jpeg"} else "png"
    return f"data:image/{kind};base64," + base64.b64encode(image.read_bytes()).decode()


async def read(client: httpx.AsyncClient, recipe: Recipe, image: Path) -> tuple[str, float]:
    content = [
        {"type": "image_url", "image_url": {"url": data_url(image)}},
        {"type": "text", "text": recipe.prompt},
    ]
    messages = [{"role": "user", "content": content}]
    if recipe.system:
        messages.insert(0, {"role": "system", "content": recipe.system})
    body = {
        "model": recipe.served or recipe.model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": recipe.max_tokens,
        **recipe.extra,
    }
    started = time.perf_counter()
    response = await client.post("/chat/completions", json=body, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"] or "", time.perf_counter() - started


async def run(args: argparse.Namespace) -> None:
    recipe = RECIPES[args.recipe]
    target = args.out / args.recipe
    (target / "raw").mkdir(parents=True, exist_ok=True)
    timings_file = target / "timings.json"
    timings = json.loads(timings_file.read_text()) if timings_file.exists() else {}
    images = sorted(
        p
        for folder in args.images
        for p in folder.iterdir()
        if p.suffix in IMAGES and not (target / f"{p.stem}.txt").exists()
    )
    gate = asyncio.Semaphore(args.parallel)
    done = 0
    async with httpx.AsyncClient(base_url=args.base_url) as client:

        async def one(image: Path) -> None:
            nonlocal done
            async with gate:
                try:
                    reply, seconds = await read(client, recipe, image)
                except httpx.HTTPError as error:
                    print(f"failed {image.stem}: {error}", flush=True)
                    return
            (target / "raw" / f"{image.stem}.md").write_text(reply, encoding="utf-8")
            (target / f"{image.stem}.txt").write_text(recipe.text(reply), encoding="utf-8")
            timings[image.stem] = round(seconds, 2)
            timings_file.write_text(json.dumps(timings, indent=1), encoding="utf-8")
            done += 1
            print(f"{done}/{len(images)} {image.stem} {seconds:.1f}s", flush=True)

        await asyncio.gather(*(one(image) for image in images))


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--recipe", choices=sorted(RECIPES), required=True)
    options.add_argument("--images", type=Path, action="append", default=[])
    options.add_argument("--out", type=Path, required=True)
    options.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    options.add_argument("--parallel", type=int, default=4)
    options.add_argument("--serve", action="store_true", help="print how to start the server")
    options.add_argument("--retext", action="store_true", help="write the text again from raw/")
    args = options.parse_args()
    if args.retext:
        recipe = RECIPES[args.recipe]
        target = args.out / args.recipe
        for raw in sorted((target / "raw").glob("*.md")):
            text = recipe.text(raw.read_text(encoding="utf-8"))
            (target / f"{raw.stem}.txt").write_text(text, encoding="utf-8")
        return
    if args.serve:
        recipe = RECIPES[args.recipe]
        print(" ".join(["vllm", "serve", recipe.model, *recipe.serve]))
        return
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
