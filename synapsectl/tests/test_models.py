"""The model files: which ones, checking them, getting them, and the GPU (models.py)."""

import hashlib
import io
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from synapsectl import cli, models, render
from synapsectl.models import Accelerator, Conversion, Download, ModelFile


def made(
    name: str, content: bytes, accelerators: frozenset[Accelerator], source: object
) -> ModelFile:
    digest = hashlib.sha256(content).hexdigest()
    return ModelFile("chat", name, digest, len(content), accelerators, source)  # type: ignore[arg-type]


CHAT = b"a chat model"
ENCODER = b"an encoder for the GPU"
FILES = (
    made("chat.gguf", CHAT, models.BOTH, Download("https://models.example/chat.gguf")),
    made("enc-q8.gguf", ENCODER, models.GPU, Conversion("org/enc", "abc123", "q8_0", ("onnx/*",))),
)


def test_every_accelerator_has_one_file_per_role() -> None:
    for accelerator in Accelerator:
        roles = sorted(f.role for f in models.required(accelerator))
        assert roles == ["chat", "embedding", "reranking"]
    assert models.server_file("embedding", Accelerator.VULKAN) == "bge-m3-q8_0.gguf"
    assert models.server_file("embedding", Accelerator.CPU) == "bge-m3-f16.gguf"
    assert models.server_file("chat", Accelerator.CPU) == models.server_file(
        "chat", Accelerator.VULKAN
    )


def test_problems_name_missing_short_and_wrong_files(tmp_path: Path) -> None:
    assert models.problems(tmp_path, Accelerator.VULKAN, verify=True, files=FILES) == [
        "chat.gguf missing",
        "enc-q8.gguf missing",
    ]
    # The CPU needs no GPU encoder.
    assert models.problems(tmp_path, Accelerator.CPU, verify=False, files=FILES) == [
        "chat.gguf missing"
    ]
    (tmp_path / "chat.gguf").write_bytes(CHAT[:-1])
    assert models.problems(tmp_path, Accelerator.CPU, verify=False, files=FILES) == [
        f"chat.gguf has {len(CHAT) - 1} bytes, not {len(CHAT)}"
    ]
    (tmp_path / "chat.gguf").write_bytes(CHAT.upper())
    # Same size: only verify sees it.
    assert models.problems(tmp_path, Accelerator.CPU, verify=False, files=FILES) == []
    assert models.problems(tmp_path, Accelerator.CPU, verify=True, files=FILES) == [
        "chat.gguf has the wrong SHA-256"
    ]


def test_fetch_downloads_converts_and_keeps_what_is_right(tmp_path: Path) -> None:
    opened: list[str] = []
    commands: list[list[str]] = []

    def opener(url: str) -> io.BytesIO:
        opened.append(url)
        return io.BytesIO(CHAT)

    def runner(command: list[str]) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        # The container writes the converted file into the mounted directory.
        out = next(v.split(":")[0] for v in command if v.endswith(":/out"))
        Path(out, "enc-q8.gguf.part").write_bytes(ENCODER)
        return subprocess.CompletedProcess(command, 0)

    reports: list[str] = []
    models.fetch(
        tmp_path,
        Accelerator.VULKAN,
        files=FILES,
        opener=opener,
        runner=runner,
        report=reports.append,
    )
    assert (tmp_path / "chat.gguf").read_bytes() == CHAT
    assert (tmp_path / "enc-q8.gguf").read_bytes() == ENCODER
    assert opened == ["https://models.example/chat.gguf"]
    assert len(commands) == 1
    assert not list(tmp_path.glob("*.part"))
    assert reports[-1] == "enc-q8.gguf: ready"
    # Again: everything is there and right, so nothing is fetched.
    models.fetch(
        tmp_path,
        Accelerator.VULKAN,
        files=FILES,
        opener=opener,
        runner=runner,
        report=reports.append,
    )
    assert len(opened) == 1
    assert len(commands) == 1


def test_a_file_with_the_wrong_digest_is_removed(tmp_path: Path) -> None:
    with pytest.raises(models.FetchError, match="wrong SHA-256"):
        models.fetch(
            tmp_path,
            Accelerator.CPU,
            files=FILES,
            opener=lambda _url: io.BytesIO(b"something else"),
            report=lambda _line: None,
        )
    assert list(tmp_path.iterdir()) == []


def test_downloads_are_https_only() -> None:
    with pytest.raises(ValueError, match="not an https address"):
        models._open("http://models.example/chat.gguf")


def test_the_converter_runs_pinned_and_as_the_caller(tmp_path: Path) -> None:
    source = Conversion("BAAI/bge-m3", "5617a9f", "q8_0", ("onnx/*", "imgs/*"))
    command = models.convert_command(source, tmp_path, "bge-m3-q8_0.gguf.part")
    assert command[:3] == ["docker", "run", "--rm"]
    assert command[command.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert models.CONVERTER_IMAGE in command
    assert "@sha256:" in models.CONVERTER_IMAGE
    assert f"{tmp_path.resolve()}:/out" in command
    script = next(c for c in command if c.startswith("SCRIPT="))
    assert f"refs/tags/{models.LLAMA_CPP_BUILD}.tar.gz" in script
    shell = command[-1]
    assert "-r /requirements.txt" in shell
    assert "BAAI/bge-m3 5617a9f q8_0 onnx/*,imgs/* /out/bge-m3-q8_0.gguf.part" in shell
    pinned = Path(
        command[command.index("--volume", command.index("--volume") + 1) + 1].split(":")[0]
    )
    assert "torch==2.11.0+cpu" in pinned.read_text(encoding="utf-8")


def test_gpu_groups_come_from_the_render_and_card_nodes(tmp_path: Path) -> None:
    assert models.gpu_groups(tmp_path) == ()
    (tmp_path / "card0").write_text("", encoding="utf-8")
    # A card without a render node is a display only.
    assert models.gpu_groups(tmp_path) == ()
    (tmp_path / "renderD128").write_text("", encoding="utf-8")
    assert models.gpu_groups(tmp_path) == (os.getgid(),)
    assert models.gpu_groups(tmp_path / "absent") == ()


def test_cli_checks_a_directory_without_a_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["--config", str(tmp_path / "none.toml"), "models", "check", "--dir", str(tmp_path)]
    assert cli.main([*arguments, "--accelerator", "cpu"]) == 1
    assert "bge-m3-f16.gguf missing" in capsys.readouterr().err
    for model in models.required(Accelerator.CPU):
        with (tmp_path / model.name).open("wb") as handle:
            handle.truncate(model.size)
    # Sparse files of the right sizes: present by size, wrong by digest (not read here: 5 GB).
    assert cli.main([*arguments, "--accelerator", "cpu"]) == 0
    assert "all present" in capsys.readouterr().out


DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def test_the_development_stack_runs_what_installations_run() -> None:
    stack = yaml.safe_load((DEPLOY / "compose.stack.yml").read_text(encoding="utf-8"))
    gpu = yaml.safe_load((DEPLOY / "compose.vulkan.yml").read_text(encoding="utf-8"))
    roles = {"llm-embed": "embedding", "llm-rerank": "reranking", "llm-chat": "chat"}
    for name, role in roles.items():
        cpu_command, gpu_command = (
            stack["services"][name]["command"],
            gpu["services"][name]["command"],
        )
        assert stack["services"][name]["image"] == models.SERVER_IMAGES["cpu"], name
        assert gpu["services"][name]["image"] == models.SERVER_IMAGES["vulkan"], name
        assert cpu_command[1] == f"/models/{models.server_file(role, Accelerator.CPU)}", name
        assert gpu_command[1] == f"/models/{models.server_file(role, Accelerator.VULKAN)}", name
        # Every argument too: the stack's chat server once lacked one installations had.
        _, key, arguments = render.SERVERS[name]
        tail = ["--api-key-file", f"/run/secrets/{key}"]
        assert cpu_command[2:] == [*arguments, *tail], name
        assert gpu_command[2:] == [*arguments, "-ngl", "99", *tail], name
