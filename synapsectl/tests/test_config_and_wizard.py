from pathlib import Path

import pytest
from pydantic import ValidationError

from synapsectl import config as cfg
from synapsectl import wizard
from synapsectl.config import SynapseConfig, Tier, TlsMode


def test_configuration_round_trips_through_toml(config: SynapseConfig, tmp_path: Path) -> None:
    path = tmp_path / "synapse.toml"
    cfg.save(config, path)
    assert cfg.load(path) == config


def test_unknown_keys_are_rejected(tmp_path: Path, config: SynapseConfig) -> None:
    path = tmp_path / "synapse.toml"
    path.write_text(cfg.dump(config) + "\n[instance_typo]\nx = 1\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        cfg.load(path)


@pytest.mark.parametrize(
    "change",
    [
        {"modules": {"enabled": ["reports"]}},  # listed but not available yet
        {"modules": {"enabled": ["no-such-module"]}},
        {"tls": {"mode": "acme"}},  # needs an email
        {"tls": {"mode": "provided"}},  # needs certificate and key
    ],
)
def test_invalid_choices_are_rejected(config: SynapseConfig, change: dict) -> None:  # type: ignore[type-arg]
    data = config.model_dump(mode="json") | change
    with pytest.raises(ValidationError):
        SynapseConfig.model_validate(data)


@pytest.mark.parametrize("hostname", ["Synapse.Example", "-bad.example", "a..b", "x" * 254])
def test_invalid_hostnames_are_rejected(config: SynapseConfig, hostname: str) -> None:
    data = config.model_dump(mode="json")
    data["instance"]["hostname"] = hostname
    with pytest.raises(ValidationError):
        SynapseConfig.model_validate(data)


def test_slugs_transliterate_turkish() -> None:
    assert wizard.slug_of("Çankırı İl Özel İdaresi") == "cankiri-il-ozel-idaresi"
    assert wizard.slug_of("!!!") == "organization"


def test_wizard_with_defaults_produces_a_valid_configuration() -> None:
    result = wizard.run(ask=lambda _prompt: "")
    assert result.instance.slug == "example-organization"
    assert result.instance.hostname == "synapse.example-organization.local"
    assert result.tls.mode is TlsMode.INTERNAL


def test_wizard_uses_the_answers() -> None:
    answers = iter(["Acme Hukuk", "", "ai.acme.example", "en", "cpu-32", "acme", "it@acme.example"])
    result = wizard.run(ask=lambda _prompt: next(answers))
    assert result.instance.slug == "acme-hukuk"
    assert result.instance.locale == "en"
    assert result.hardware is Tier.CPU_32
    assert result.tls.email == "it@acme.example"


def test_wizard_asks_for_certificate_files_for_provided_tls(tmp_path: Path) -> None:
    (tmp_path / "c.pem").write_text("C", encoding="utf-8")
    (tmp_path / "k.pem").write_text("K", encoding="utf-8")
    answers = iter(
        ["Acme", "", "", "", "", "provided", str(tmp_path / "c.pem"), str(tmp_path / "k.pem")]
    )
    result = wizard.run(ask=lambda _prompt: next(answers))
    assert result.tls.mode is TlsMode.PROVIDED
    assert result.tls.certificate == tmp_path / "c.pem"


def test_suggested_tier_follows_installed_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    def memory(gib: int) -> None:
        pages = {"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": gib * 1024**3 // 4096}
        monkeypatch.setattr("os.sysconf", lambda name: pages[name])

    memory(16)
    assert wizard.suggested_tier() is Tier.CPU_16
    memory(32)
    assert wizard.suggested_tier() is Tier.CPU_32
