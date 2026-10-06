"""Upgrades with a scripted Docker: what is checked before anything changes, the backup first,
only the version line of synapse.toml changed, and the way back when apply stops."""

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from synapsectl import cli, upgrade
from synapsectl.apply import ApplyError
from synapsectl.config import Backup, Images, SynapseConfig, load, save

SNAPSHOT = "4f3c2b1a" + "0" * 56


class DockerImages:
    """``docker image inspect`` for the images on the machine: name:tag -> PostgreSQL major."""

    def __init__(self, present: dict[str, str]) -> None:
        self.present = present
        self.calls: list[list[str]] = []

    def __call__(
        self, args: Sequence[str], *, interactive: bool = False
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        assert list(args[:3]) == ["docker", "image", "inspect"], args
        image = args[-1]
        if image not in self.present:
            return subprocess.CompletedProcess(list(args), 1, "", "No such image")
        environment = f"PATH=/usr/bin\nPG_MAJOR={self.present[image]}\n"
        return subprocess.CompletedProcess(list(args), 0, environment, "")


def release(version: str, postgres: str = "18") -> dict[str, str]:
    return {f"{name}:{version}": postgres for name in upgrade.IMAGES}


class Steps:
    """The backup and apply an upgrade runs, recorded in order."""

    def __init__(self, *, failing_apply: bool = False) -> None:
        self.done: list[str] = []
        self.failing_apply = failing_apply

    def backup(self, config: SynapseConfig, config_file: Path, **_: Any) -> str:
        self.done.append(f"backup {config.images.version} {config_file.name}")
        return SNAPSHOT

    def apply(self, config: SynapseConfig, **_: Any) -> None:
        self.done.append(f"apply {config.images.version}")
        if self.failing_apply:
            raise ApplyError("Apply migrations: failed (exit 1)\nrelation exists")


@pytest.fixture
def installed(config: SynapseConfig, tmp_path: Path) -> tuple[SynapseConfig, Path]:
    """An installation on 1.0.0 with backups, its synapse.toml edited by hand."""
    configured = SynapseConfig(
        instance=config.instance,
        paths=config.paths,
        images=Images(version="1.0.0"),
        backup=Backup(repository=tmp_path / "repository", staging_dir=tmp_path / "staging"),
    )
    config_file = tmp_path / "synapse.toml"
    save(configured, config_file)
    text = config_file.read_text(encoding="utf-8")
    config_file.write_text(
        "# The installation of Demo\n" + text.replace("[images]", "[images]  # release")
    )
    config_file.chmod(0o640)
    return configured, config_file


def run_upgrade(
    installed: tuple[SynapseConfig, Path],
    images: DockerImages,
    steps: Steps,
    version: str = "1.1.0",
) -> SynapseConfig:
    configured, config_file = installed
    return upgrade.upgrade(
        configured,
        config_file,
        version,
        run=images,
        echo=lambda _: None,
        take_backup=steps.backup,
        bring_up=steps.apply,
    )


def test_an_upgrade_backs_up_then_changes_only_the_version_and_applies(
    installed: tuple[SynapseConfig, Path],
) -> None:
    _, config_file = installed
    before = config_file.read_text(encoding="utf-8")
    steps = Steps()
    upgraded = run_upgrade(installed, DockerImages(release("1.0.0") | release("1.1.0")), steps)
    assert steps.done == ["backup 1.0.0 synapse.toml", "apply 1.1.0"]
    assert upgraded.images.version == "1.1.0"
    after = config_file.read_text(encoding="utf-8")
    assert after == before.replace('version = "1.0.0"', 'version = "1.1.0"')
    assert after.startswith("# The installation of Demo\n")
    assert load(config_file).images.version == "1.1.0"
    assert config_file.stat().st_mode & 0o777 == 0o640
    assert not config_file.with_name("synapse.toml.partial").exists()


@pytest.mark.parametrize(
    ("present", "version", "refusal"),
    [
        (release("1.0.0"), "1.0.0", "runs 1.0.0 already"),
        (release("1.0.0"), "1.1.0", "not on this machine (synapse-app, synapse-web"),
        (release("1.0.0") | release("2.0.0", postgres="19"), "2.0.0", "PostgreSQL 19"),
    ],
)
def test_an_upgrade_is_refused_before_anything_changes(
    installed: tuple[SynapseConfig, Path], present: dict[str, str], version: str, refusal: str
) -> None:
    _, config_file = installed
    before = config_file.read_text(encoding="utf-8")
    steps = Steps()
    with pytest.raises(upgrade.UpgradeError, match=refusal.replace("(", r"\(")):
        run_upgrade(installed, DockerImages(present), steps, version)
    assert steps.done == []
    assert config_file.read_text(encoding="utf-8") == before


def test_an_upgrade_needs_backups(config: SynapseConfig, tmp_path: Path) -> None:
    config_file = tmp_path / "synapse.toml"
    save(config, config_file)
    steps = Steps()
    with pytest.raises(upgrade.UpgradeError, match="backups are not set up"):
        run_upgrade((config, config_file), DockerImages(release("dev") | release("1.1.0")), steps)
    assert steps.done == []


def test_a_stopped_upgrade_says_how_to_go_on_or_back(
    installed: tuple[SynapseConfig, Path],
) -> None:
    _, config_file = installed
    steps = Steps(failing_apply=True)
    with pytest.raises(upgrade.UpgradeError) as stopped:
        run_upgrade(installed, DockerImages(release("1.0.0") | release("1.1.0")), steps)
    message = str(stopped.value)
    assert "Apply migrations: failed" in message
    assert 'set [images] version = "1.0.0"' in message
    assert "synapsectl restore --snapshot 4f3c2b1a --replace --yes" in message
    # the new version stays written: apply can be run again once the cause is fixed
    assert load(config_file).images.version == "1.1.0"


def test_the_version_is_written_where_the_file_has_no_version_line(tmp_path: Path) -> None:
    config_file = tmp_path / "synapse.toml"
    config_file.write_text(
        '[instance]\norganization = "Demo"\nslug = "demo"\nhostname = "synapse.demo.local"\n'
        '\n[images]\n\n[models]\naccelerator = "cpu"\n',
        encoding="utf-8",
    )
    assert upgrade.set_version(config_file, "1.1.0").images.version == "1.1.0"
    without_table = tmp_path / "bare.toml"
    without_table.write_text(
        '[instance]\norganization = "Demo"\nslug = "demo"\nhostname = "synapse.demo.local"\n',
        encoding="utf-8",
    )
    assert upgrade.set_version(without_table, "1.1.0").images.version == "1.1.0"


def test_an_invalid_version_leaves_the_file_alone(
    installed: tuple[SynapseConfig, Path],
) -> None:
    _, config_file = installed
    before = config_file.read_text(encoding="utf-8")
    with pytest.raises(upgrade.UpgradeError, match="cannot set version"):
        upgrade.set_version(config_file, "1.1.0 latest")
    assert config_file.read_text(encoding="utf-8") == before
    assert not config_file.with_name("synapse.toml.partial").exists()


def test_the_upgrade_command(
    monkeypatch: pytest.MonkeyPatch,
    installed: tuple[SynapseConfig, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, config_file = installed
    asked: list[str] = []

    def upgraded(_loaded: SynapseConfig, _path: Path, version: str) -> None:
        asked.append(version)

    monkeypatch.setattr(upgrade, "upgrade", upgraded)
    assert cli.main(["--config", str(config_file), "upgrade", "--to", "1.1.0"]) == 0
    assert asked == ["1.1.0"]

    def refused(*_args: object) -> None:
        raise upgrade.UpgradeError("the installation runs 1.1.0 already")

    monkeypatch.setattr(upgrade, "upgrade", refused)
    assert cli.main(["--config", str(config_file), "upgrade", "--to", "1.1.0"]) == 1
    assert "runs 1.1.0 already" in capsys.readouterr().err
