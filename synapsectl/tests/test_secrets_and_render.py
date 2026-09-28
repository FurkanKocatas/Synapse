import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from synapsectl import render, secrets
from synapsectl.config import SynapseConfig, Tier, Tls, TlsMode


def test_secrets_are_private_and_generated_once(config: SynapseConfig) -> None:
    created = secrets.generate(config)
    assert set(created) == {secret.name for secret in secrets.REQUIRED}
    directory = config.paths.secrets_dir
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for secret in secrets.REQUIRED:
        assert stat.S_IMODE((directory / secret.name).stat().st_mode) == 0o400
    before = (directory / "csrf_key").read_text(encoding="utf-8")
    assert secrets.generate(config) == []
    assert (directory / "csrf_key").read_text(encoding="utf-8") == before


def test_admin_connection_uses_the_generated_superuser_password(config: SynapseConfig) -> None:
    secrets.generate(config)
    directory = config.paths.secrets_dir
    superuser = (directory / "postgres_superuser").read_text(encoding="utf-8").strip()
    conninfo = (directory / "admin_conninfo").read_text(encoding="utf-8").strip()
    assert conninfo == f"postgresql://postgres:{superuser}@db:5432/postgres"


def test_provided_certificates_are_copied_into_the_secrets(
    config: SynapseConfig, tmp_path: Path
) -> None:
    (tmp_path / "c.pem").write_text("CERT", encoding="utf-8")
    (tmp_path / "k.pem").write_text("KEY", encoding="utf-8")
    provided = config.model_copy(
        update={
            "tls": Tls(
                mode=TlsMode.PROVIDED,
                certificate=tmp_path / "c.pem",
                private_key=tmp_path / "k.pem",
            )
        }
    )
    secrets.generate(provided)
    assert (provided.paths.secrets_dir / "tls_certificate").read_text(encoding="utf-8") == "CERT"


def test_only_the_web_front_publishes_ports(config: SynapseConfig) -> None:
    services = render.compose(config)["services"]
    published = {name for name, service in services.items() if "ports" in service}
    assert published == {"web"}
    assert services["web"]["ports"] == ["80:80", "443:443"]


def test_every_application_container_is_hardened(config: SynapseConfig) -> None:
    services = render.compose(config)["services"]
    for name in ("bootstrap", "migrate", "api", "web"):
        assert services[name]["read_only"] is True, name
        assert services[name]["cap_drop"] == ["ALL"], name
        assert services[name]["security_opt"] == ["no-new-privileges:true"], name


def test_the_tenant_and_tier_are_applied(config: SynapseConfig) -> None:
    services = render.compose(config)["services"]
    assert services["api"]["environment"]["SYNAPSE_TENANT_ID"] == str(config.instance.tenant_id)
    assert services["db"]["mem_limit"] == "2560m"
    big = render.compose(config.model_copy(update={"hardware": Tier.CPU_32}))["services"]
    assert big["db"]["mem_limit"] == "6g"


@pytest.mark.parametrize(
    ("tls", "directive"),
    [
        (Tls(), "tls internal"),
        (Tls(mode=TlsMode.ACME, email="it@example.org"), "tls it@example.org"),
    ],
)
def test_tls_snippet_per_mode(config: SynapseConfig, tls: Tls, directive: str) -> None:
    snippet = render.tls_snippet(config.model_copy(update={"tls": tls}))
    assert snippet.startswith(render.HEADER)
    assert snippet.strip().endswith(directive)


def test_rendered_files_carry_the_header_and_a_manifest(config: SynapseConfig) -> None:
    rendered = render.render(config)
    render.write(config, rendered)
    for name in rendered.files:
        assert (
            (config.paths.render_dir / name).read_text(encoding="utf-8").startswith(render.HEADER)
        )
    assert (config.paths.render_dir / "manifest.json").exists()
    yaml.safe_load(rendered.files["compose.yml"])


@pytest.mark.skipif(shutil.which("docker") is None, reason="needs the docker CLI")
def test_docker_compose_accepts_the_rendered_file(config: SynapseConfig) -> None:
    secrets.generate(config)
    render.write(config, render.render(config))
    result = subprocess.run(  # noqa: S603
        ["docker", "compose", "-f", str(config.paths.render_dir / "compose.yml"), "config", "-q"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
