from pathlib import Path

import pytest

from synapsectl.config import Instance, Paths, SynapseConfig


@pytest.fixture
def config(tmp_path: Path) -> SynapseConfig:
    return SynapseConfig(
        instance=Instance(organization="Demo Kurum", slug="demo", hostname="synapse.demo.local"),
        paths=Paths(secrets_dir=tmp_path / "secrets", render_dir=tmp_path / "rendered"),
    )
