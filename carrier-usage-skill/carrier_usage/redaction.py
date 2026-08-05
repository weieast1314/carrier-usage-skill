"""日志和错误信息的凭据及身份标识脱敏。"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

_PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "openid",
    "ticket",
    "token",
    "access_token",
    "password",
}


def mask_phone(value: str) -> str:
    """遮蔽 11 位中国大陆手机号。"""

    if re.fullmatch(r"1[3-9]\d{9}", value):
        return f"{value[:3]}****{value[-4:]}"
    return value


def redact_text(value: str, secrets: Iterable[str] = ()) -> str:
    """从自由文本中移除显式秘密并遮蔽手机号。"""

    redacted = value
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED]")
    return _PHONE_PATTERN.sub(lambda match: mask_phone(match.group(1)), redacted)


def redact_mapping(value: Mapping[str, object], secrets: Iterable[str] = ()) -> dict[str, object]:
    """递归遮蔽映射中的敏感键、显式秘密和手机号。"""

    secret_values = tuple(secrets)
    return {
        key: (
            "[REDACTED]"
            if key.casefold() in _SENSITIVE_KEYS
            else _redact_value(item, secret_values)
        )
        for key, item in value.items()
    }


def _redact_value(value: object, secrets: tuple[str, ...]) -> object:
    if isinstance(value, Mapping):
        string_key_mapping = {str(key): item for key, item in value.items()}
        return redact_mapping(string_key_mapping, secrets)
    if isinstance(value, list):
        return [_redact_value(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item, secrets) for item in value)
    if isinstance(value, str):
        return redact_text(value, secrets)
    return value
