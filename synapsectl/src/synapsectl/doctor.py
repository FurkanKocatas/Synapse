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
from enum import StrEnum
from pathlib import Path

from synapsectl.config import SynapseConfig, Tier
from synapsectl.render import render
from synapsectl.secrets import required_files

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


def run_checks(config: SynapseConfig, *, stack_running: bool = False) -> list[Check]:
    checks: list[Callable[[], Check]] = [
        check_docker,
        check_cpu,
        lambda: check_memory(config),
        lambda: check_disk(config.paths.render_dir),
        lambda: check_port(config.network.http_port, running=stack_running),
        lambda: check_port(config.network.https_port, running=stack_running),
        lambda: check_secrets(config),
        lambda: check_rendered(config),
    ]
    return [check() for check in checks]
