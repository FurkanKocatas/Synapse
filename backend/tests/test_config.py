import pytest
from pydantic import ValidationError

from synapse.kernel.config import LogFormat, Settings


def test_defaults_are_safe_for_local_use() -> None:
    settings = Settings()
    assert settings.api_host == "127.0.0.1"
    assert settings.log_format is LogFormat.JSON
    assert settings.trusted_proxy_ips == "127.0.0.1"


def test_values_come_from_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNAPSE_API_PORT", "9001")
    monkeypatch.setenv("SYNAPSE_LOG_LEVEL", "DEBUG")
    settings = Settings()
    assert settings.api_port == 9001
    assert settings.log_level == "DEBUG"


@pytest.mark.parametrize(
    ("name", "value"), [("SYNAPSE_API_PORT", "0"), ("SYNAPSE_LOG_LEVEL", "LOUD")]
)
def test_invalid_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


def test_settings_are_immutable() -> None:
    settings = Settings()
    with pytest.raises(ValidationError):
        settings.api_port = 1  # type: ignore[misc]


def test_an_empty_tenant_id_means_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNAPSE_TENANT_ID", "")
    assert Settings().tenant_id is None


def test_a_malformed_tenant_id_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNAPSE_TENANT_ID", "not-a-uuid")
    with pytest.raises(ValidationError):
        Settings()
