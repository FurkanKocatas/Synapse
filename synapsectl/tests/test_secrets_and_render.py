import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from synapsectl import models, render, secrets
from synapsectl.config import Models, SynapseConfig, Tier, Tls, TlsMode
from synapsectl.models import Accelerator


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


def test_only_the_web_front_can_reach_beyond_the_machine(config: SynapseConfig) -> None:
    rendered = render.compose(config)
    networks = rendered["networks"]
    assert networks["internal"]["internal"] is True
    assert networks["internal"]["ipam"] == {"config": [{"subnet": config.network.subnet}]}
    assert "internal" not in networks["edge"]
    on_edge = {
        name
        for name, service in rendered["services"].items()
        if "edge" in service.get("networks", [])
    }
    assert on_edge == {"web"}
    assert rendered["services"]["web"]["networks"] == ["internal", "edge"]


def test_only_the_web_front_publishes_ports(config: SynapseConfig) -> None:
    services = render.compose(config)["services"]
    published = {name for name, service in services.items() if "ports" in service}
    assert published == {"web"}
    assert services["web"]["ports"] == ["80:80", "443:443"]


def test_every_application_container_is_hardened(config: SynapseConfig) -> None:
    services = render.compose(config)["services"]
    for name in ("bootstrap", "migrate", "api", "worker", "scheduler", "web"):
        assert services[name]["read_only"] is True, name
        assert services[name]["cap_drop"] == ["ALL"], name
        assert services[name]["security_opt"] == ["no-new-privileges:true"], name


def test_every_container_logs_with_rotation(config: SynapseConfig) -> None:
    services = render.compose(config)["services"]
    for name, service in services.items():
        assert service["logging"] == {
            "driver": "json-file",
            "options": {"max-size": "10m", "max-file": "5"},
        }, name


def test_the_tenant_and_tier_are_applied(config: SynapseConfig) -> None:
    services = render.compose(config)["services"]
    assert services["api"]["environment"]["SYNAPSE_TENANT_ID"] == str(config.instance.tenant_id)
    assert services["api"]["volumes"] == ["blobs:/var/lib/synapse/blobs"]
    assert services["worker"]["volumes"] == ["blobs:/var/lib/synapse/blobs:ro"]
    assert services["worker"]["environment"]["SYNAPSE_DB_USER"] == "synapse_worker"
    # besides the API, only the scheduler writes them: it removes purged documents' files
    assert services["scheduler"]["volumes"] == ["blobs:/var/lib/synapse/blobs"]
    assert services["scheduler"]["environment"]["SYNAPSE_DB_USER"] == "synapse_scheduler"
    assert services["scheduler"]["secrets"] == ["db_synapse_scheduler", "audit_signing_key"]
    assert services["db"]["mem_limit"] == "2560m"
    big = render.compose(config.model_copy(update={"hardware": Tier.CPU_32}))["services"]
    assert big["db"]["mem_limit"] == "6g"


def test_the_api_knows_the_address_users_open(config: SynapseConfig) -> None:
    api = render.compose(config)["services"]["api"]["environment"]
    assert api["SYNAPSE_PUBLIC_URL"] == "https://synapse.demo.local"
    moved = config.model_copy(
        update={"network": config.network.model_copy(update={"https_port": 8443})}
    )
    services = render.compose(moved)["services"]
    assert services["api"]["environment"]["SYNAPSE_PUBLIC_URL"] == "https://synapse.demo.local:8443"
    assert services["web"]["environment"]["SYNAPSE_SITE_ADDRESS"] == "synapse.demo.local:8443"


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


def test_model_servers_are_hardened_internal_and_keyed(config: SynapseConfig) -> None:
    services = render.compose(config)["services"]
    for name in render.SERVERS:
        server = services[name]
        assert server["read_only"] is True, name
        assert server["cap_drop"] == ["ALL"], name
        assert server["security_opt"] == ["no-new-privileges:true"], name
        assert server["networks"] == ["internal"], name
        assert "ports" not in server, name
        assert server["user"] == "10001:10001", name
        assert server["volumes"] == [f"{config.models.dir}:/models:ro"], name
        assert server["image"] == models.SERVER_IMAGES["cpu"], name
        assert "devices" not in server, name
        assert "-ngl" not in server["command"], name
        (key,) = server["secrets"]
        assert server["command"][-2:] == ["--api-key-file", f"/run/secrets/{key}"], name
    assert services["llm-embed"]["command"][:2] == ["-m", "/models/bge-m3-f16.gguf"]
    assert services["llm-rerank"]["command"][:2] == ["-m", "/models/bge-reranker-v2-m3-f16.gguf"]
    chat = services["llm-chat"]["command"]
    for name in render.SERVERS:
        assert "--no-webui" in services[name]["command"], name
    assert chat[chat.index("--reasoning-budget") + 1] == "0"
    assert chat[chat.index("--cache-ram") + 1] == "0"


def test_vulkan_passes_the_gpu_and_its_groups_in(config: SynapseConfig) -> None:
    gpu = config.model_copy(
        update={"models": Models(accelerator=Accelerator.VULKAN, gpu_groups=(44, 992))}
    )
    services = render.compose(gpu)["services"]
    for name in render.SERVERS:
        server = services[name]
        assert server["image"] == models.SERVER_IMAGES["vulkan"], name
        assert server["devices"] == ["/dev/dri:/dev/dri"], name
        assert server["group_add"] == ["44", "992"], name
        assert server["command"][server["command"].index("-ngl") + 1] == "99", name
    assert services["llm-embed"]["command"][:2] == ["-m", "/models/bge-m3-q8_0.gguf"]
    with pytest.raises(ValidationError, match="gpu_groups"):
        Models(accelerator=Accelerator.VULKAN)


def test_the_api_and_the_worker_call_the_model_servers(config: SynapseConfig) -> None:
    rendered = render.compose(config)
    api, worker = rendered["services"]["api"], rendered["services"]["worker"]
    assert api["environment"]["SYNAPSE_EMBED_URL"] == "http://llm-embed:8080"
    assert api["environment"]["SYNAPSE_RERANK_URL"] == "http://llm-rerank:8080"
    assert api["environment"]["SYNAPSE_CHAT_URL"] == "http://llm-chat:8080"
    assert api["environment"]["SYNAPSE_CHAT_KEY_FILE"] == "/run/secrets/chat_key"
    assert {"embed_key", "rerank_key", "chat_key"} <= set(api["secrets"])
    # The worker only embeds.
    assert worker["environment"]["SYNAPSE_EMBED_URL"] == "http://llm-embed:8080"
    assert "SYNAPSE_CHAT_URL" not in worker["environment"]
    assert "chat_key" not in worker["secrets"]
    assert {"embed_key", "rerank_key", "chat_key"} <= set(rendered["secrets"])
