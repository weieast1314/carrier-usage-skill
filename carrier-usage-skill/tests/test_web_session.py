import stat
from pathlib import Path

import pytest
from carrier_usage.errors import ConfigurationError
from carrier_usage.web_session import (
    default_session_path,
    load_browser_state,
    save_browser_state,
)


def test_default_session_path_uses_provider_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", "/tmp/carrier-usage-test-data")

    assert default_session_path("china_unicom") == Path(
        "/tmp/carrier-usage-test-data/carrier-usage/china-unicom-session.json"
    )


def test_save_and_load_browser_state_with_private_permissions(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "session.json"
    state = {"cookies": [{"name": "token", "value": "secret"}], "origins": []}

    save_browser_state(path, state)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_browser_state(path) == state


def test_load_rejects_permissions_that_allow_other_users(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    path.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    path.chmod(0o644)

    with pytest.raises(ConfigurationError, match="会话文件权限过宽"):
        load_browser_state(path)


def test_save_atomically_replaces_existing_state(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    save_browser_state(path, {"cookies": [], "version": 1})

    save_browser_state(path, {"cookies": [], "version": 2})

    assert load_browser_state(path)["version"] == 2
    assert list(tmp_path.glob(".*.tmp")) == []
