from pathlib import Path

import pytest

from carrier_usage.account_registry import AccountRecord
from carrier_usage.config import AppConfig, load_config
from carrier_usage.errors import ConfigurationError


def test_rejects_credential_file_readable_by_other_users(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[china_unicom]\nsession_path="session.json"\n', encoding="utf-8")
    config_path.chmod(0o644)

    with pytest.raises(ConfigurationError, match="配置文件权限过宽"):
        load_config({}, config_path)


def test_requires_unicom_login_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    with pytest.raises(ConfigurationError, match="请先运行 login 命令扫码登录"):
        load_config({}, None)


def test_accepts_explicit_unicom_session_path(tmp_path: Path) -> None:
    session_path = tmp_path / "session.json"

    config = load_config({"CARRIER_USAGE_UNICOM_SESSION": str(session_path)}, None)

    assert config == AppConfig("china_unicom", 300, session_path)


def test_account_session_overrides_legacy_config(tmp_path: Path) -> None:
    account = AccountRecord("unicom-work", "工作联通", "china_unicom", None, tmp_path / "work.json")

    config = load_config({"CARRIER_USAGE_MIN_REFRESH_SECONDS": "300"}, account=account)

    assert config.provider == "china_unicom"
    assert config.unicom_session_path == account.session_path
