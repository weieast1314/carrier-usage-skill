"""安全保存多运营商账户元数据并进行无歧义选择。"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from carrier_usage.errors import (
    AccountAmbiguousError,
    AccountConflictError,
    AccountNotFoundError,
    ConfigurationError,
)
from carrier_usage.web_session import default_session_path

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass(frozen=True, slots=True)
class AccountRecord:
    id: str
    alias: str
    provider: str
    masked_phone: str | None
    session_path: Path

    def __post_init__(self) -> None:
        if not _ID_PATTERN.fullmatch(self.id):
            raise AccountConflictError("账户 ID 只能包含小写字母、数字和连字符")
        if not self.alias.strip():
            raise AccountConflictError("账户别名不能为空")
        if self.masked_phone is not None and "*" not in self.masked_phone:
            raise AccountConflictError("账户号码必须使用脱敏形式")


@dataclass(frozen=True, slots=True)
class RegistryState:
    accounts: tuple[AccountRecord, ...] = ()
    global_default: str | None = None
    provider_defaults: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.provider_defaults is None:
            object.__setattr__(self, "provider_defaults", {})


def default_registry_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    return root / "carrier-usage" / "accounts.json"


def account_session_path(account_id: str) -> Path:
    root = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
    return root / "carrier-usage" / "sessions" / f"{account_id}.json"


class AccountRegistry:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_registry_path()

    def load(self) -> RegistryState:
        if not self.path.exists():
            return RegistryState()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            accounts = tuple(
                AccountRecord(
                    id=str(item["id"]),
                    alias=str(item["alias"]),
                    provider=str(item["provider"]),
                    masked_phone=str(item["masked_phone"]) if item.get("masked_phone") else None,
                    session_path=Path(str(item["session_path"])).expanduser(),
                )
                for item in raw.get("accounts", [])
            )
            defaults = {str(k): str(v) for k, v in raw.get("provider_defaults", {}).items()}
            global_default = raw.get("global_default")
            return RegistryState(
                accounts, str(global_default) if global_default else None, defaults
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError, AccountConflictError) as error:
            raise ConfigurationError(f"账户注册表无法读取，请检查或恢复：{self.path}") from error

    def list_accounts(self) -> tuple[AccountRecord, ...]:
        return self.load().accounts

    def add(self, account: AccountRecord) -> None:
        state = self.load()
        if any(item.id == account.id for item in state.accounts):
            raise AccountConflictError(f"账户 ID 已存在：{account.id}")
        if any(item.alias == account.alias for item in state.accounts):
            raise AccountConflictError(f"账户别名已存在：{account.alias}")
        self._save(
            RegistryState((*state.accounts, account), state.global_default, state.provider_defaults)
        )

    def rename(self, selector: str, alias: str) -> AccountRecord:
        target = self.resolve(account=selector)
        if any(item.alias == alias and item.id != target.id for item in self.list_accounts()):
            raise AccountConflictError(f"账户别名已存在：{alias}")
        replacement = AccountRecord(
            target.id, alias, target.provider, target.masked_phone, target.session_path
        )
        state = self.load()
        self._save(
            RegistryState(
                tuple(replacement if x.id == target.id else x for x in state.accounts),
                state.global_default,
                state.provider_defaults,
            )
        )
        return replacement

    def update_masked_phone(self, selector: str, masked_phone: str) -> AccountRecord:
        target = self.resolve(account=selector)
        replacement = AccountRecord(
            target.id, target.alias, target.provider, masked_phone, target.session_path
        )
        state = self.load()
        self._save(
            RegistryState(
                tuple(replacement if item.id == target.id else item for item in state.accounts),
                state.global_default,
                state.provider_defaults,
            )
        )
        return replacement

    def remove(self, selector: str) -> AccountRecord:
        target = self.resolve(account=selector)
        state = self.load()
        remaining = tuple(item for item in state.accounts if item.id != target.id)
        defaults = {k: v for k, v in (state.provider_defaults or {}).items() if v != target.id}
        same_provider = [item for item in remaining if item.provider == target.provider]
        if target.provider not in defaults and len(same_provider) == 1:
            defaults[target.provider] = same_provider[0].id
        global_default = None if state.global_default == target.id else state.global_default
        self._save(RegistryState(remaining, global_default, defaults))
        return target

    def set_global_default(self, selector: str) -> AccountRecord:
        target = self.resolve(account=selector)
        state = self.load()
        self._save(RegistryState(state.accounts, target.id, state.provider_defaults))
        return target

    def set_provider_default(self, selector: str) -> AccountRecord:
        target = self.resolve(account=selector)
        state = self.load()
        defaults = dict(state.provider_defaults or {})
        defaults[target.provider] = target.id
        self._save(RegistryState(state.accounts, state.global_default, defaults))
        return target

    def resolve(self, *, account: str | None = None, provider: str | None = None) -> AccountRecord:
        state = self.load()
        candidates = [
            item for item in state.accounts if provider is None or item.provider == provider
        ]
        if account is not None:
            matches = [
                item for item in candidates if account in {item.id, item.alias, item.masked_phone}
            ]
            return self._single(matches, account)
        default_id = (
            (state.provider_defaults or {}).get(provider) if provider else state.global_default
        )
        if default_id:
            matches = [item for item in candidates if item.id == default_id]
            if matches:
                return matches[0]
        return self._single(candidates, provider or "全部运营商")

    def _single(self, matches: list[AccountRecord], selector: str) -> AccountRecord:
        if not matches:
            raise AccountNotFoundError(f"未找到匹配账户：{selector}")
        if len(matches) > 1:
            choices = "、".join(
                f"{index}. {item.alias}（{item.masked_phone or '号码未知'}）[{item.provider}]"
                for index, item in enumerate(matches, 1)
            )
            raise AccountAmbiguousError(f"存在多个匹配账户，请明确选择：{choices}")
        return matches[0]

    def _save(self, state: RegistryState) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "global_default": state.global_default,
            "provider_defaults": state.provider_defaults or {},
            "accounts": [
                {
                    "id": x.id,
                    "alias": x.alias,
                    "provider": x.provider,
                    "masked_phone": x.masked_phone,
                    "session_path": str(x.session_path),
                }
                for x in state.accounts
            ],
        }
        descriptor, name = tempfile.mkstemp(
            prefix=".accounts.", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            self.path.chmod(0o600)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise


def migrate_legacy_session(
    registry: AccountRegistry, provider: str = "china_unicom"
) -> AccountRecord | None:
    existing = [item for item in registry.list_accounts() if item.provider == provider]
    if existing:
        return existing[0] if len(existing) == 1 else None
    legacy = default_session_path(provider)
    if not legacy.is_file():
        return None
    account = AccountRecord("china-unicom-default", "我的联通", provider, None, legacy)
    registry.add(account)
    registry.set_provider_default(account.id)
    registry.set_global_default(account.id)
    return account
