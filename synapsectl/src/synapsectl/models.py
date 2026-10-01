"""The model files an installation runs (ADR 0018), and getting them.

``models.dir`` holds GGUF files the llama.cpp servers read. Which ones depends on the
accelerator: on a GPU through Vulkan the encoders run with 8-bit weights, on the CPU with 16-bit
ones (8-bit is slower there); the chat model is the same file for both. Every file is pinned by
SHA-256 and size.

- The chat model is downloaded from its pinned Hugging Face revision.
- The encoders are converted from their pinned revisions with llama.cpp's own converter at the
  servers' build, in a throwaway container with the converter's dependencies pinned. The
  conversion is deterministic, so the SHA-256 also proves the file is the one measured in
  docs/benchmarks/embeddings.md.

An offline bundle carries the files ready-made; ``fetch`` is for building one, and for
development machines.
"""

import hashlib
import os
import subprocess
import tempfile
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO

# The llama.cpp build the servers run (render.py) and the converter comes from.
LLAMA_CPP_BUILD = "b11243"
SERVER_IMAGES = {
    "cpu": f"ghcr.io/ggml-org/llama.cpp:server-{LLAMA_CPP_BUILD}"
    "@sha256:f9115c95639e60abc09d4ea83b26fd4d56c66aa1174594393335a514da00c283",
    "vulkan": f"ghcr.io/ggml-org/llama.cpp:server-vulkan-{LLAMA_CPP_BUILD}"
    "@sha256:fb1b039d27638fb22a5e7e59e97729534e73fe621f430ef496666ec01ac0630b",
}
CONVERTER_IMAGE = (
    "python:3.12-slim-trixie"
    "@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f"
)
CHUNK = 1 << 20


class Accelerator(StrEnum):
    CPU = "cpu"
    VULKAN = "vulkan"


@dataclass(frozen=True)
class Download:
    url: str


@dataclass(frozen=True)
class Conversion:
    repo: str
    revision: str
    outtype: str
    # Files of the repository the converter does not read (other formats, pictures).
    skip: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelFile:
    role: str
    name: str
    sha256: str
    size: int
    accelerators: frozenset[Accelerator]
    source: Download | Conversion


BOTH = frozenset(Accelerator)
GPU = frozenset({Accelerator.VULKAN})
CPU = frozenset({Accelerator.CPU})
BGE_M3 = ("BAAI/bge-m3", "5617a9f61b028005a4858fdac845db406aefb181")
BGE_M3_SKIP = ("onnx/*", "imgs/*", "*.jpg", "colbert_linear.pt", "sparse_linear.pt")
RERANKER = ("BAAI/bge-reranker-v2-m3", "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e")
RERANKER_SKIP = ("assets/*",)

FILES = (
    ModelFile(
        "embedding",
        "bge-m3-q8_0.gguf",
        "b0d8d1f89742d614a0ac2712030ff3dfc6598dcbcd748cb7f56d2c88f58ccae9",
        634_553_856,
        GPU,
        Conversion(*BGE_M3, "q8_0", BGE_M3_SKIP),
    ),
    ModelFile(
        "embedding",
        "bge-m3-f16.gguf",
        "f9ef2726087200e0ed0e95952747aec5de2727cbadf36d2ba54c36cda5e4f524",
        1_157_671_296,
        CPU,
        Conversion(*BGE_M3, "f16", BGE_M3_SKIP),
    ),
    ModelFile(
        "reranking",
        "bge-reranker-v2-m3-q8_0.gguf",
        "2830daa69a85b28be14788556971ae8c76dcccfc2c5d02adf0102d307bc12e71",
        635_673_568,
        GPU,
        Conversion(*RERANKER, "q8_0", RERANKER_SKIP),
    ),
    ModelFile(
        "reranking",
        "bge-reranker-v2-m3-f16.gguf",
        "e4ba5c95a896a28197fd35d83034d0d886de543f4e90b1e1a0fe4c2ae0c86fd2",
        1_159_775_008,
        CPU,
        Conversion(*RERANKER, "f16", RERANKER_SKIP),
    ),
    ModelFile(
        "chat",
        "Qwen3.5-4B-Q4_K_M.gguf",
        "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4",
        2_740_937_888,
        BOTH,
        Download(
            "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/"
            "e87f176479d0855a907a41277aca2f8ee7a09523/Qwen3.5-4B-Q4_K_M.gguf"
        ),
    ),
)

# The converter's dependencies, as they were when the files above were made.
CONVERTER_REQUIREMENTS = """\
certifi==2026.7.22
charset-normalizer==3.5.2
filelock==4.0.7
fsspec==2026.9.0
hf-xet==1.6.0
huggingface-hub==0.36.2
idna==3.20
jinja2==3.1.6
markupsafe==3.0.3
mpmath==1.3.0
networkx==3.7
numpy==2.2.6
packaging==26.3
protobuf==4.25.9
pyyaml==6.0.3
regex==2026.9.29
requests==2.34.2
safetensors==0.8.0
sentencepiece==0.2.2
setuptools==81.0.0
sympy==1.14.0
tokenizers==0.22.2
torch==2.11.0+cpu
tqdm==4.70.1
transformers==4.57.6
typing-extensions==4.16.0
urllib3==2.8.0
"""

# Runs inside the converter container: llama.cpp's source at the build, the model's pinned
# revision, then the converter. Arguments: repository, revision, outtype, skipped patterns
# (comma-separated), output file.
CONVERT_SCRIPT = f"""
import io, subprocess, sys, tarfile, urllib.request
from huggingface_hub import snapshot_download
repo, revision, outtype, skip, out = sys.argv[1:6]
url = "https://github.com/ggml-org/llama.cpp/archive/refs/tags/{LLAMA_CPP_BUILD}.tar.gz"
with urllib.request.urlopen(url, timeout=600) as response:
    archive = tarfile.open(fileobj=io.BytesIO(response.read()), mode="r:gz")
    archive.extractall("/tmp/src", filter="data")
model = snapshot_download(
    repo, revision=revision, cache_dir="/tmp/hf", ignore_patterns=skip.split(",")
)
converter = "/tmp/src/llama.cpp-{LLAMA_CPP_BUILD}/convert_hf_to_gguf.py"
command = [sys.executable, converter, model, "--outtype", outtype, "--outfile", out]
subprocess.run(command, check=True)
"""


def gpu_groups(dri: Path = Path("/dev/dri")) -> tuple[int, ...]:
    """The groups that own the GPU's device files; empty when there is no GPU to render on."""
    try:
        nodes = [*dri.glob("renderD*"), *dri.glob("card*")]
        if not any(node.name.startswith("renderD") for node in nodes):
            return ()
        return tuple(sorted({node.stat().st_gid for node in nodes}))
    except OSError:
        return ()


def required(accelerator: Accelerator) -> list[ModelFile]:
    return [f for f in FILES if accelerator in f.accelerators]


def server_file(role: str, accelerator: Accelerator) -> str:
    """The file a role's server loads with this accelerator."""
    (match,) = [f.name for f in required(accelerator) if f.role == role]
    return match


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def problems(
    directory: Path, accelerator: Accelerator, *, verify: bool, files: Sequence[ModelFile] = FILES
) -> list[str]:
    """What is wrong with the model files; empty when every one is present (and, with
    ``verify``, has its SHA-256: reading 4 GB takes a while, so a size check is the default)."""
    found = []
    for model in files:
        if accelerator not in model.accelerators:
            continue
        path = directory / model.name
        if not path.is_file():
            found.append(f"{model.name} missing")
        elif path.stat().st_size != model.size:
            found.append(f"{model.name} has {path.stat().st_size} bytes, not {model.size}")
        elif verify and sha256_of(path) != model.sha256:
            found.append(f"{model.name} has the wrong SHA-256")
    return found


type Opener = Callable[[str], BinaryIO]
type Runner = Callable[[list[str]], subprocess.CompletedProcess[bytes]]


def _open(url: str) -> BinaryIO:
    if not url.startswith("https://"):
        raise ValueError(f"not an https address: {url}")
    response: BinaryIO = urllib.request.urlopen(url, timeout=600)  # noqa: S310  (https only)
    return response


def _run(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, check=True)  # noqa: S603  (a fixed docker command)


class FetchError(RuntimeError):
    pass


def fetch(
    directory: Path,
    accelerator: Accelerator,
    *,
    files: Sequence[ModelFile] = FILES,
    opener: Opener = _open,
    runner: Runner = _run,
    report: Callable[[str], None] = print,
) -> None:
    """Get every file the accelerator needs into ``directory``; files already right are kept."""
    directory.mkdir(parents=True, exist_ok=True)
    for model in files:
        if accelerator not in model.accelerators:
            continue
        path = directory / model.name
        if not problems(directory, accelerator, verify=True, files=[model]):
            report(f"{model.name}: present")
            continue
        partial = path.with_name(path.name + ".part")
        if isinstance(model.source, Download):
            report(f"{model.name}: downloading {model.size / 1e9:.1f} GB")
            _download(opener(model.source.url), partial)
        else:
            report(f"{model.name}: converting {model.source.repo} ({model.source.outtype})")
            runner(convert_command(model.source, directory, partial.name))
        if sha256_of(partial) != model.sha256:
            partial.unlink()
            raise FetchError(f"{model.name}: the result has the wrong SHA-256; removed")
        partial.replace(path)
        report(f"{model.name}: ready")


def _download(source: BinaryIO, target: Path) -> None:
    with source, target.open("wb") as out:
        while block := source.read(CHUNK):
            out.write(block)


def convert_command(source: Conversion, directory: Path, output: str) -> list[str]:
    """The throwaway container that converts one model into ``directory/output``. It runs as
    the calling user, so the file is theirs, with a virtual environment in its own /tmp."""
    requirements = Path(tempfile.gettempdir()) / "synapse-converter-requirements.txt"
    requirements.write_text(CONVERTER_REQUIREMENTS, encoding="utf-8")
    venv = "/tmp/venv"  # noqa: S108  (inside the throwaway container, which is the user's own)
    install = (
        f"python -m venv {venv} && {venv}/bin/pip install --quiet --no-cache-dir "
        "--index-url https://download.pytorch.org/whl/cpu "
        "--extra-index-url https://pypi.org/simple -r /requirements.txt"
    )
    convert = (
        f'{venv}/bin/python -c "$SCRIPT" {source.repo} {source.revision} {source.outtype} '
        f"{','.join(source.skip) or 'none'} /out/{output}"
    )
    return [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--env",
        "HOME=/tmp",
        "--env",
        f"SCRIPT={CONVERT_SCRIPT}",
        "--volume",
        f"{directory.resolve()}:/out",
        "--volume",
        f"{requirements}:/requirements.txt:ro",
        CONVERTER_IMAGE,
        "sh",
        "-c",
        f"set -e; {install}; {convert}",
    ]
