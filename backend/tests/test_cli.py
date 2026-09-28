import pytest

from synapse import __version__
from synapse.cli import main


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_role_is_required() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([])
    assert exit_info.value.code == 2


def test_api_role_starts_uvicorn_with_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr("synapse.cli.uvicorn.run", lambda app, **kwargs: calls.append(kwargs))
    assert main(["api"]) == 0
    assert calls[0]["factory"] is True
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["forwarded_allow_ips"] == "127.0.0.1"
