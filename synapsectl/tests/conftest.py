from pathlib import Path

import pytest

from synapsectl.config import Backup, Instance, Paths, SynapseConfig, save


@pytest.fixture
def config(tmp_path: Path) -> SynapseConfig:
    return SynapseConfig(
        instance=Instance(organization="Demo Kurum", slug="demo", hostname="synapse.demo.local"),
        paths=Paths(secrets_dir=tmp_path / "secrets", render_dir=tmp_path / "rendered"),
    )


@pytest.fixture
def setup(config: SynapseConfig, tmp_path: Path) -> tuple[SynapseConfig, Path]:
    """An installation with backups set up: an initialised repository, the secrets, its file."""
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "config").write_text("restic", encoding="utf-8")
    configured = SynapseConfig(
        instance=config.instance,
        paths=config.paths,
        backup=Backup(repository=repository, staging_dir=tmp_path / "staging"),
    )
    config.paths.secrets_dir.mkdir(parents=True)
    for name in ("postgres_superuser", "backup_password", "audit_signing_key"):
        (config.paths.secrets_dir / name).write_text(f"{name}-value\n", encoding="utf-8")
    config_file = tmp_path / "synapse.toml"
    save(configured, config_file)
    return configured, config_file
