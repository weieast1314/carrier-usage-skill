"""从环境变量和本地 TOML 文件加载安全配置。"""

from __future__ import annotations

import os
import stat
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from carrier_usage.account_registry import AccountRecord
from carrier_usage.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class AppConfig:
    provider: str
    min_refresh_seconds: int
    unicom_session_path: Path | None = None


def load_config(
    env: Mapping[str, str] | None = None,
    path: Path | None = None,
    account: AccountRecord | None = None,
) -> AppConfig:
    """按“环境变量 > TOML > 默认值”的优先级加载配置。"""

    source_env = os.environ if env is None else env
    file_config = _load_toml(path)
    carrier = _mapping(file_config.get("carrier"))
    unicom = _mapping(file_config.get("china_unicom"))

    provider = (
        account.provider
        if account
        else source_env.get(
            "CARRIER_USAGE_PROVIDER", _string(carrier.get("provider")) or "china_unicom"
        )
    )
    session_text = source_env.get(
        "CARRIER_USAGE_UNICOM_SESSION",
        _string(unicom.get("session_path")) or "",
    ).strip()
    session_path = (
        account.session_path
        if account
        else (Path(session_text).expanduser() if session_text else None)
    )
    refresh_text = source_env.get(
        "CARRIER_USAGE_MIN_REFRESH_SECONDS",
        str(carrier.get("min_refresh_seconds", 300)),
    )

    try:
        min_refresh_seconds = int(refresh_text)
    except (TypeError, ValueError) as error:
        raise ConfigurationError("最小刷新间隔必须是整数秒") from error
    if min_refresh_seconds < 60:
        raise ConfigurationError("最小刷新间隔不能少于 60 秒")
    if provider == "china_unicom" and session_path is None:
        from carrier_usage.web_session import default_session_path

        default_path = default_session_path(provider)
        session_path = default_path if default_path.is_file() else None
    if provider == "china_unicom" and session_path is None:
        raise ConfigurationError("缺少中国联通登录会话，请先运行 login 命令扫码登录")

    return AppConfig(
        provider=provider,
        min_refresh_seconds=min_refresh_seconds,
        unicom_session_path=session_path,
    )


def _load_toml(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    if not path.is_file():
        raise ConfigurationError(f"配置文件不存在：{path}")
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ConfigurationError("配置文件权限过宽，请设置为仅当前用户可读写（0600）")
    try:
        with path.open("rb") as stream:
            loaded = tomllib.load(stream)
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError("配置文件不是有效的 TOML") from error
    return dict(loaded)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None
