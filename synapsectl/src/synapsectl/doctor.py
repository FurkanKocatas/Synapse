"""``synapsectl doctor``: checks that an installation can run as configured (ADR 0012).

Each check reports OK, WARN or FAIL with a sentence an installer can act on. FAIL means the
installation will not work; WARN means it may work badly or is not hardened.
"""

import json
import os
import platform
import shutil
import socket
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from synapsectl.config import SynapseConfig, Tier
from synapsectl.models import SERVER_IMAGES, Accelerator, gpu_groups, problems
from synapsectl.render import render
from synapsectl.secrets import APP_UID, required_files

GIB = 1024**3
MIN_MEMORY = {Tier.CPU_16: 16, Tier.CPU_32: 32, Tier.GPU: 32}
MIN_FREE_DISK_GIB = 50


class Status(StrEnum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str


def _run(command: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)  # noqa: S603
    except OSError, subprocess.TimeoutExpired:
        return None


def check_docker() -> Check:
    engine = _run(["docker", "version", "--format", "{{.Server.Version}}"])
    if engine is None or engine.returncode != 0:
        return Check("docker", Status.FAIL, "Docker is not installed or its daemon is not running")
    compose = _run(["docker", "compose", "version", "--short"])
    if compose is None or compose.returncode != 0:
        return Check("docker", Status.FAIL, "the Docker Compose plugin is missing")
    return Check(
        "docker", Status.OK, f"engine {engine.stdout.strip()}, compose {compose.stdout.strip()}"
    )


def check_cpu(cpuinfo: Path = Path("/proc/cpuinfo")) -> Check:
    # llama.cpp's CPU kernels need AVX2 on x86 (docs/research/02-hardware-inference.md).
    if platform.machine().lower() not in {"x86_64", "amd64"}:
        return Check("cpu", Status.OK, f"{platform.machine()}: AVX2 does not apply")
    try:
        flags = cpuinfo.read_text(encoding="utf-8")
    except OSError:
        return Check("cpu", Status.WARN, "cannot read CPU flags; check AVX2 support by hand")
    if " avx2" not in flags:
        return Check("cpu", Status.FAIL, "the CPU has no AVX2; local models will not run")
    return Check("cpu", Status.OK, f"AVX2 present, {os.cpu_count()} logical CPUs")


def check_memory(config: SynapseConfig) -> Check:
    try:
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except ValueError, OSError:
        return Check("memory", Status.WARN, "cannot read the installed memory")
    tier = Tier(config.hardware)
    needed = MIN_MEMORY[tier]
    # Firmware and the kernel keep part of the RAM, so 16 GB machines report a little less.
    have = total / GIB
    if have < needed * 0.9:
        return Check(
            "memory", Status.FAIL, f"{have:.1f} GiB installed, tier {tier} needs {needed} GiB"
        )
    return Check("memory", Status.OK, f"{have:.1f} GiB installed")


def check_disk(path: Path) -> Check:
    existing = next(p for p in (path, *path.parents) if p.exists())
    free = shutil.disk_usage(existing).free / GIB
    if free < MIN_FREE_DISK_GIB:
        return Check("disk", Status.WARN, f"{free:.0f} GiB free, {MIN_FREE_DISK_GIB} recommended")
    return Check("disk", Status.OK, f"{free:.0f} GiB free")


def check_clock() -> Check:
    """The audit log, the logs and the backups carry the host's time: it must be kept right."""
    found = _run(["timedatectl", "show", "--property=NTPSynchronized", "--value"])
    if found is None or found.returncode != 0:
        return Check("clock", Status.WARN, "cannot tell whether NTP keeps the clock; check it")
    if found.stdout.strip() != "yes":
        return Check(
            "clock",
            Status.WARN,
            "NTP does not keep the clock: run timedatectl set-ntp true, with the "
            "organisation's time server in /etc/systemd/timesyncd.conf where there is one",
        )
    return Check("clock", Status.OK, "kept by NTP")


def check_port(port: int, *, running: bool) -> Check:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        in_use = probe.connect_ex(("127.0.0.1", port)) == 0
    if in_use and not running:
        return Check(f"port {port}", Status.FAIL, "already in use by another program")
    return Check(f"port {port}", Status.OK, "in use by Synapse" if in_use else "free")


def check_secrets(config: SynapseConfig) -> Check:
    directory = config.paths.secrets_dir
    problems = []
    for secret in required_files(config):
        path = directory / secret.name
        if not path.is_file() or path.stat().st_size == 0:
            problems.append(f"{secret.name} missing")
            continue
        info = path.stat()
        if info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            problems.append(f"{secret.name} readable by others")
        if os.geteuid() == 0 and info.st_uid != secret.owner_uid:
            problems.append(f"{secret.name} not owned by uid {secret.owner_uid}")
    if problems:
        return Check("secrets", Status.FAIL, "; ".join(problems) + " (run: synapsectl init)")
    return Check("secrets", Status.OK, f"{len(required_files(config))} files present, private")


def check_rendered(config: SynapseConfig) -> Check:
    root = config.paths.render_dir
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return Check("rendered files", Status.FAIL, "not rendered yet (run: synapsectl render)")
    expected = render(config)
    if json.loads(manifest_path.read_text(encoding="utf-8")) != json.loads(
        expected.manifest(config)
    ):
        return Check(
            "rendered files",
            Status.FAIL,
            "differ from what synapse.toml and this synapsectl version produce (run: render)",
        )
    edited = [
        name
        for name, content in expected.files.items()
        if not (root / name).exists() or (root / name).read_text(encoding="utf-8") != content
    ]
    if edited:
        return Check(
            "rendered files", Status.FAIL, f"edited by hand: {', '.join(edited)} (run: render)"
        )
    return Check("rendered files", Status.OK, "match synapse.toml")


def check_models(config: SynapseConfig) -> Check:
    directory, accelerator = config.models.dir, Accelerator(config.models.accelerator)
    found = problems(directory, accelerator, verify=False)
    if found:
        return Check("models", Status.FAIL, "; ".join(found) + " (run: synapsectl models fetch)")
    return Check("models", Status.OK, f"the {accelerator} files are in {directory}")


def check_gpu(config: SynapseConfig, dri: Path = Path("/dev/dri")) -> Check:
    groups = gpu_groups(dri)
    if Accelerator(config.models.accelerator) is Accelerator.CPU:
        if groups:
            return Check(
                "gpu",
                Status.WARN,
                "a GPU is present but the models run on the CPU; with models.accelerator = "
                f'"vulkan" and models.gpu_groups = {list(groups)}, embedding is twice as fast and '
                "reranking fits its 3-second budget (docs/benchmarks/embeddings.md)",
            )
        return Check("gpu", Status.OK, "no GPU; the models run on the CPU")
    if not groups:
        return Check("gpu", Status.FAIL, f"models.accelerator is vulkan but {dri} has no GPU")
    missing = sorted(set(groups) - set(config.models.gpu_groups))
    if missing:
        return Check(
            "gpu", Status.FAIL, f"models.gpu_groups lacks {missing}, which own {dri}'s devices"
        )
    # The server image itself, as the user and groups it runs with, must see the GPU.
    group_flags = [
        flag for group in config.models.gpu_groups for flag in ("--group-add", str(group))
    ]
    probe = _run(
        [
            *("docker", "run", "--rm", "--device", f"{dri}:/dev/dri"),
            *("--user", f"{APP_UID}:{APP_UID}", *group_flags),
            *(SERVER_IMAGES["vulkan"], "--list-devices"),
        ]
    )
    devices = [line.strip() for line in (probe.stdout if probe else "").splitlines()]
    found_gpu = next((line for line in devices if line.startswith("Vulkan0")), None)
    if probe is None or probe.returncode != 0 or found_gpu is None:
        return Check("gpu", Status.FAIL, "the Vulkan server image cannot see the GPU")
    return Check("gpu", Status.OK, found_gpu)


# A nightly backup older than this is reported.
BACKUP_MAX_AGE = timedelta(days=2)


def check_backup(config: SynapseConfig, now: datetime | None = None) -> Check:
    """Backups are set up, the repository is there and the last good one is recent. Only
    warnings: a missing backup must not stop apply from repairing the installation."""
    from synapsectl import backup  # noqa: PLC0415  (backup imports apply, which imports doctor)

    if config.backup.repository is None:
        return Check("backup", Status.WARN, "no backups are taken: set [backup] repository")
    if not (config.backup.repository / "config").exists():
        return Check(
            "backup",
            Status.WARN,
            f"{config.backup.repository} holds no repository (disk not mounted? run: "
            "synapsectl backup init)",
        )
    good = backup.last_good(config)
    if good is None:
        return Check("backup", Status.WARN, "no backup has succeeded yet (run: synapsectl backup)")
    latest = backup.read_status(config).get("backup", {})
    if not latest.get("ok", True):
        return Check("backup", Status.WARN, f"the last backup failed: {latest.get('detail')}")
    age = (now or datetime.now(UTC)) - good
    if age > BACKUP_MAX_AGE:
        return Check("backup", Status.WARN, f"the last good backup is {age.days} days old")
    return Check("backup", Status.OK, f"last good backup {good:%Y-%m-%d %H:%M}")


def run_checks(config: SynapseConfig, *, stack_running: bool = False) -> list[Check]:
    checks: list[Callable[[], Check]] = [
        check_docker,
        check_cpu,
        lambda: check_memory(config),
        lambda: check_disk(config.paths.render_dir),
        check_clock,
        lambda: check_port(config.network.http_port, running=stack_running),
        lambda: check_port(config.network.https_port, running=stack_running),
        lambda: check_secrets(config),
        lambda: check_rendered(config),
        lambda: check_models(config),
        lambda: check_gpu(config),
        lambda: check_backup(config),
    ]
    return [check() for check in checks]
