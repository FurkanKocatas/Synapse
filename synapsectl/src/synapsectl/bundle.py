"""The offline bundle (ADR 0012): a release in one directory, for machines without the internet.

    synapse-VERSION/
      manifest.json   the release's version, and every file: what it is, its SHA-256 and size
      SHA256SUMS      the same hashes, as ``sha256sum -c`` reads them
      images/         the release's images, the model servers' and restic's (``docker save``)
      models/         the model files of both accelerators (models.FILES)

``create`` makes one on a machine that has the release's images and model files (the vendor's);
``verify`` checks one, on any machine; ``load`` verifies it, loads its images into Docker and
puts the model files the installation needs into ``models.dir``. Then ``synapsectl upgrade`` (or
``apply``, on a new machine) runs the release.

The hashes find a bundle damaged on its way (a copy cut short, a bad disk), not one changed on
purpose: that needs the vendor's signature over the manifest, which ADR 0012 asks for and which
comes with the vendor's signing key.
"""

import hashlib
import json
import shutil
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from synapsectl import models
from synapsectl.apply import Runner, docker
from synapsectl.config import SynapseConfig
from synapsectl.render import RESTIC_IMAGE
from synapsectl.upgrade import IMAGES

MANIFEST = "manifest.json"
SUMS = "SHA256SUMS"
FORMAT = 1
CHUNK = 1 << 20


class BundleError(RuntimeError):
    """The bundle could not be made or loaded; the message says why."""


@dataclass(frozen=True)
class Entry:
    # Relative to the bundle, with forward slashes.
    path: str
    kind: Literal["image", "model"]
    # The image's reference, or the model file's name.
    name: str
    sha256: str
    size: int


def images(version: str) -> list[str]:
    """Every image a release runs: its own, the model servers' of both accelerators, restic's."""
    return [
        *(f"{name}:{version}" for name in IMAGES),
        *models.SERVER_IMAGES.values(),
        RESTIC_IMAGE,
    ]


def create(
    version: str,
    out: Path,
    *,
    model_dir: Path,
    files: Sequence[models.ModelFile] = models.FILES,
    run: Runner = docker,
    echo: Callable[[str], None] = print,
) -> Path:
    """Make ``out/synapse-VERSION``; returns it. Images not on this machine are pulled if they
    can be (the model servers' and restic's); every model file must be in ``model_dir``."""
    target = out / f"synapse-{version}"
    if target.exists():
        raise BundleError(f"{target} exists already")
    wrong = [
        problem
        for model in files
        for problem in models.problems(model_dir, _any(model), verify=True, files=[model])
    ]
    if wrong:
        raise BundleError(f"the model files in {model_dir} are not right: {'; '.join(wrong)}")
    partial = target.with_name(target.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    try:
        entries = _fill(partial, version, model_dir, files, run, echo)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    manifest = {
        "format": FORMAT,
        "version": version,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": [asdict(entry) for entry in entries],
    }
    (partial / MANIFEST).write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    sums = "".join(f"{entry.sha256}  {entry.path}\n" for entry in entries)
    (partial / SUMS).write_text(sums, encoding="utf-8")
    partial.rename(target)
    echo(f"== Bundle {target}: {len(entries)} files, {_gigabytes(entries)} GB")
    return target


def _fill(
    partial: Path,
    version: str,
    model_dir: Path,
    files: Sequence[models.ModelFile],
    run: Runner,
    echo: Callable[[str], None],
) -> list[Entry]:
    """Save the images and copy the model files into ``partial``; their entries."""
    (partial / "images").mkdir(parents=True)
    (partial / "models").mkdir()
    entries: list[Entry] = []
    for image in images(version):
        echo(f"== {image}")
        inspect = ["docker", "image", "inspect", "--format", "{{.Id}}", image]
        if run(inspect).returncode != 0 and run(["docker", "pull", image]).returncode != 0:
            raise BundleError(f"{image} is not on this machine and could not be pulled")
        path = f"images/{_file_name(image)}"
        saved = run(["docker", "save", "--output", str(partial / path), image])
        if saved.returncode != 0:
            raise BundleError(f"docker save {image} failed: {saved.stderr.strip()}")
        entries.append(_entry(partial, path, "image", image))
    for model in files:
        echo(f"== {model.name}")
        path = f"models/{model.name}"
        shutil.copyfile(model_dir / model.name, partial / path)
        entries.append(_entry(partial, path, "model", model.name))
    return entries


def verify(bundle: Path) -> tuple[str, list[str]]:
    """The bundle's version, and what is wrong with it: empty when every file listed is there,
    of its size and SHA-256, and nothing else is."""
    version, entries = _read(bundle)
    found: list[str] = []
    for entry in entries:
        path = bundle / entry.path
        if not path.is_file():
            found.append(f"{entry.path} missing")
        elif path.stat().st_size != entry.size:
            found.append(f"{entry.path} has {path.stat().st_size} bytes, not {entry.size}")
        elif _sha256(path) != entry.sha256:
            found.append(f"{entry.path} has the wrong SHA-256")
    listed = {entry.path for entry in entries}
    for part in ("images", "models"):
        for path in sorted((bundle / part).glob("*")):
            relative = path.relative_to(bundle).as_posix()
            if relative not in listed:
                found.append(f"{relative} is not in the manifest")
    sums = (bundle / SUMS).read_text(encoding="utf-8") if (bundle / SUMS).is_file() else ""
    expected = "".join(f"{entry.sha256}  {entry.path}\n" for entry in entries)
    if sums != expected:
        found.append(f"{SUMS} does not match the manifest")
    return version, found


def load(
    bundle: Path,
    config: SynapseConfig,
    *,
    run: Runner = docker,
    echo: Callable[[str], None] = print,
) -> str:
    """Verify the bundle, load its images and put the model files this installation's
    accelerator needs into ``models.dir``; returns the release's version. A damaged bundle
    loads nothing."""
    echo(f"== Check {bundle}")
    version, wrong = verify(bundle)
    if wrong:
        raise BundleError("the bundle is damaged, nothing was loaded:\n  " + "\n  ".join(wrong))
    _, entries = _read(bundle)
    for entry in entries:
        if entry.kind != "image":
            continue
        echo(f"== Load {entry.name}")
        loaded = run(["docker", "load", "--input", str(bundle / entry.path)])
        if loaded.returncode != 0:
            raise BundleError(f"docker load {entry.path} failed: {loaded.stderr.strip()}")
    accelerator = config.models.accelerator
    needed = {model.name for model in models.required(accelerator)}
    target = config.models.dir
    target.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        if entry.kind != "model" or entry.name not in needed:
            continue
        path = target / entry.name
        if path.is_file() and path.stat().st_size == entry.size and _sha256(path) == entry.sha256:
            echo(f"== {entry.name}: present")
            continue
        echo(f"== Copy {entry.name}")
        partial = path.with_name(path.name + ".part")
        shutil.copyfile(bundle / entry.path, partial)
        partial.replace(path)
    if config.images.version == version:
        echo(f"== Loaded {version}, the release this installation runs: run synapsectl apply")
    else:
        echo(f"== Loaded {version}: run synapsectl upgrade --to {version}")
    return version


def _read(bundle: Path) -> tuple[str, list[Entry]]:
    try:
        manifest = json.loads((bundle / MANIFEST).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise BundleError(f"{bundle} is not a bundle: {MANIFEST} is missing") from error
    except json.JSONDecodeError as error:
        raise BundleError(f"{bundle / MANIFEST} cannot be read: {error}") from error
    if manifest.get("format") != FORMAT:
        raise BundleError(f"{bundle} is a bundle of another format ({manifest.get('format')})")
    entries = [Entry(**item) for item in manifest["files"]]
    for entry in entries:
        # A manifest names files inside the bundle only.
        if entry.path.startswith("/") or ".." in Path(entry.path).parts:
            raise BundleError(f"{MANIFEST} names a file outside the bundle: {entry.path}")
    return str(manifest["version"]), entries


def _entry(root: Path, path: str, kind: Literal["image", "model"], name: str) -> Entry:
    file = root / path
    return Entry(path, kind, name, _sha256(file), file.stat().st_size)


def _file_name(image: str) -> str:
    """An image's file: its repository's last part and its tag, without the digest
    ("llama.cpp-server-b11243.tar")."""
    reference = image.split("@", 1)[0]
    return reference.rsplit("/", 1)[-1].replace(":", "-") + ".tar"


def _any(model: models.ModelFile) -> models.Accelerator:
    return next(iter(sorted(model.accelerators)))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def _gigabytes(entries: Sequence[Entry]) -> str:
    return f"{sum(entry.size for entry in entries) / 1e9:.1f}"
