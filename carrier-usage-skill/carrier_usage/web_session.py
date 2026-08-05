"""安全保存和读取浏览器登录会话。"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path

from carrier_usage.errors import ConfigurationError


def default_session_path(provider: str) -> Path:
    """返回 Provider 的默认本机会话路径。"""

    data_home = os.environ.get("XDG_DATA_HOME")
    root = Path(data_home) if data_home else Path("~/.local/share").expanduser()
    slug = provider.replace("_", "-")
    return root / "carrier-usage" / f"{slug}-session.json"


def save_browser_state(path: Path, state: Mapping[str, object]) -> None:
    """以原子替换和 0600 权限保存浏览器状态。"""

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(dict(state), stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def load_browser_state(path: Path) -> dict[str, object]:
    """读取权限安全的浏览器状态。"""

    if not path.is_file():
        raise ConfigurationError(f"会话文件不存在：{path}")
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ConfigurationError("会话文件权限过宽，请设置为仅当前用户可读写（0600）")
    try:
        with path.open(encoding="utf-8") as stream:
            loaded = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError("会话文件无法读取或格式无效") from error
    if not isinstance(loaded, dict):
        raise ConfigurationError("会话文件格式无效")
    return {str(key): value for key, value in loaded.items()}
