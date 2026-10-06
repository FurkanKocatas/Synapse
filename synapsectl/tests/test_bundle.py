"""Offline bundles with a scripted Docker: made with every image and model file and their hashes,
checked file by file, and loaded only when nothing in them is damaged."""

import hashlib
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from synapsectl import bundle, cli, models
from synapsectl.config import Images, Models, SynapseConfig, save


class Docker:
    """Images on a machine: inspect, pull, save (the file holds the image's name) and load."""

    def __init__(self, present: set[str], pullable: set[str] | None = None) -> None:
        self.present = set(present)
        self.pullable = pullable or set()
        self.loaded: list[str] = []
        self.calls: list[list[str]] = []

    def __call__(
        self, args: Sequence[str], *, interactive: bool = False
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        command, image = list(args[:3]), args[-1]
        ok = subprocess.CompletedProcess(list(args), 0, "", "")
        failed = subprocess.CompletedProcess(list(args), 1, "", "no such image")
        if command == ["docker", "image", "inspect"]:
            return ok if image in self.present else failed
        if command[:2] == ["docker", "pull"]:
            if image not in self.pullable:
                return failed
            self.present.add(image)
            return ok
        if command[:2] == ["docker", "save"]:
            Path(args[3]).write_text(f"image {image}", encoding="utf-8")
            return ok
        if command[:2] == ["docker", "load"]:
            self.loaded.append(Path(args[3]).read_text(encoding="utf-8").removeprefix("image "))
            return ok
        raise AssertionError(args)


def model_file(
    directory: Path, name: str, accelerators: frozenset[models.Accelerator]
) -> models.ModelFile:
    data = f"weights of {name}".encode()
    (directory / name).write_bytes(data)
    return models.ModelFile(
        "chat",
        name,
        hashlib.sha256(data).hexdigest(),
        len(data),
        accelerators,
        models.Download("https://example.org/" + name),
    )


@pytest.fixture
def source(tmp_path: Path) -> tuple[Path, list[models.ModelFile]]:
    directory = tmp_path / "models"
    directory.mkdir()
    files = [
        model_file(directory, "chat.gguf", models.BOTH),
        model_file(directory, "encoder-q8.gguf", models.GPU),
        model_file(directory, "encoder-f16.gguf", models.CPU),
    ]
    return directory, files


def made(tmp_path: Path, source: tuple[Path, list[models.ModelFile]]) -> tuple[Path, Docker]:
    ours = {f"{name}:2.0.0" for name in ("synapse-app", "synapse-web", "synapse-postgres")}
    docker = Docker(ours, pullable=set(bundle.images("2.0.0")) - ours)
    directory, files = source
    out = tmp_path / "out"
    out.mkdir()
    made = bundle.create("2.0.0", out, model_dir=directory, files=files, run=docker, echo=print)
    return made, docker


def test_a_bundle_holds_every_image_and_model_file_with_its_hash(
    tmp_path: Path, source: tuple[Path, list[models.ModelFile]]
) -> None:
    made_bundle, docker = made(tmp_path, source)
    assert made_bundle.name == "synapse-2.0.0"
    manifest = json.loads((made_bundle / bundle.MANIFEST).read_text(encoding="utf-8"))
    assert manifest["version"] == "2.0.0"
    paths = [entry["path"] for entry in manifest["files"]]
    assert paths[:3] == [
        "images/synapse-app-2.0.0.tar",
        "images/synapse-web-2.0.0.tar",
        "images/synapse-postgres-2.0.0.tar",
    ]
    assert f"images/llama.cpp-server-{models.LLAMA_CPP_BUILD}.tar" in paths
    assert "models/encoder-q8.gguf" in paths and "models/encoder-f16.gguf" in paths
    # The images missing here were pulled by their pinned references.
    assert ["docker", "pull", models.SERVER_IMAGES["cpu"]] in docker.calls
    sums = (made_bundle / bundle.SUMS).read_text(encoding="utf-8").splitlines()
    assert len(sums) == len(paths) and sums[0].endswith("  images/synapse-app-2.0.0.tar")
    assert bundle.verify(made_bundle) == ("2.0.0", [])
    with pytest.raises(bundle.BundleError, match="exists already"):
        bundle.create("2.0.0", tmp_path / "out", model_dir=source[0], files=source[1], run=docker)


def test_a_bundle_is_not_made_without_its_images_or_right_model_files(
    tmp_path: Path, source: tuple[Path, list[models.ModelFile]]
) -> None:
    directory, files = source
    with pytest.raises(bundle.BundleError, match="could not be pulled"):
        bundle.create("2.0.0", tmp_path, model_dir=directory, files=files, run=Docker(set()))
    (directory / "chat.gguf").write_bytes(b"other weights, same length!")
    with pytest.raises(bundle.BundleError, match=r"chat\.gguf"):
        bundle.create("2.0.0", tmp_path, model_dir=directory, files=files, run=Docker(set()))
    assert not list(tmp_path.glob("synapse-2.0.0*"))


def test_a_damaged_bundle_says_what_is_wrong_and_loads_nothing(
    tmp_path: Path,
    source: tuple[Path, list[models.ModelFile]],
    config: SynapseConfig,
) -> None:
    made_bundle, _ = made(tmp_path, source)
    (made_bundle / "images" / "synapse-web-2.0.0.tar").write_text("image synapse-web:2.0.1")
    (made_bundle / "models" / "chat.gguf").unlink()
    (made_bundle / "images" / "extra.tar").write_text("?")
    _, wrong = bundle.verify(made_bundle)
    assert wrong == [
        "images/synapse-web-2.0.0.tar has the wrong SHA-256",
        "models/chat.gguf missing",
        "images/extra.tar is not in the manifest",
    ]
    docker = Docker(set())
    with pytest.raises(bundle.BundleError, match="nothing was loaded"):
        bundle.load(made_bundle, config, run=docker)
    assert docker.calls == []
    with pytest.raises(bundle.BundleError, match="not a bundle"):
        bundle.verify(tmp_path)


def test_loading_puts_in_the_images_and_the_accelerators_model_files(
    tmp_path: Path,
    source: tuple[Path, list[models.ModelFile]],
    config: SynapseConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made_bundle, _ = made(tmp_path, source)
    monkeypatch.setattr(models, "FILES", tuple(source[1]))
    target = tmp_path / "installed-models"
    installed = config.model_copy(
        update={"models": Models(dir=target, accelerator=models.Accelerator.CPU)}
    )
    docker = Docker(set())
    messages: list[str] = []
    assert bundle.load(made_bundle, installed, run=docker, echo=messages.append) == "2.0.0"
    assert docker.loaded == bundle.images("2.0.0")
    # The CPU's files, not the GPU's encoder.
    assert sorted(p.name for p in target.iterdir()) == ["chat.gguf", "encoder-f16.gguf"]
    assert messages[-1] == "== Loaded 2.0.0: run synapsectl upgrade --to 2.0.0"
    # Again: what is there and right is kept.
    messages.clear()
    bundle.load(made_bundle, installed, run=Docker(set()), echo=messages.append)
    assert "== chat.gguf: present" in messages


def test_the_bundle_commands(
    tmp_path: Path,
    source: tuple[Path, list[models.ModelFile]],
    config: SynapseConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    made_bundle, _ = made(tmp_path, source)
    assert cli.main(["bundle", "verify", str(made_bundle)]) == 0
    assert "2.0.0: every file is right" in capsys.readouterr().out
    (made_bundle / "models" / "chat.gguf").write_text("x")
    assert cli.main(["bundle", "verify", str(made_bundle)]) == 1
    assert "models/chat.gguf has 1 bytes" in capsys.readouterr().err
    config_file = tmp_path / "synapse.toml"
    save(config.model_copy(update={"images": Images(version="2.0.0")}), config_file)
    assert cli.main(["--config", str(config_file), "bundle", "load", str(made_bundle)]) == 1
    assert "nothing was loaded" in capsys.readouterr().err
