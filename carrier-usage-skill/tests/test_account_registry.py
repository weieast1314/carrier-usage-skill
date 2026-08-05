import json
import stat
from pathlib import Path

import pytest
from carrier_usage.account_registry import (
    AccountRecord,
    AccountRegistry,
    migrate_legacy_session,
)
from carrier_usage.errors import AccountAmbiguousError, AccountConflictError, ConfigurationError
from carrier_usage.web_session import default_session_path, save_browser_state


def account(tmp_path: Path, identity: str, alias: str, phone: str) -> AccountRecord:
    return AccountRecord(identity, alias, "china_unicom", phone, tmp_path / f"{identity}.json")


def test_registry_resolves_explicit_then_provider_default_then_global(tmp_path: Path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    work = account(tmp_path, "unicom-work", "工作联通", "138****1234")
    home = account(tmp_path, "unicom-home", "家庭联通", "186****5678")
    registry.add(work)
    registry.add(home)
    registry.set_provider_default(home.id)
    registry.set_global_default(work.id)

    assert registry.resolve(account="工作联通") == work
    assert registry.resolve(provider="china_unicom") == home
    assert registry.resolve() == work
    assert stat.S_IMODE(registry.path.stat().st_mode) == 0o600


def test_registry_reports_masked_candidates_when_ambiguous(tmp_path: Path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.add(account(tmp_path, "unicom-work", "工作联通", "138****1234"))
    registry.add(account(tmp_path, "unicom-home", "家庭联通", "186****5678"))

    with pytest.raises(AccountAmbiguousError) as captured:
        registry.resolve(provider="china_unicom")

    assert "工作联通（138****1234）" in str(captured.value)
    assert "家庭联通（186****5678）" in str(captured.value)


def test_registry_rejects_duplicate_alias_and_unmasked_phone(tmp_path: Path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.add(account(tmp_path, "first", "工作联通", "138****1234"))
    with pytest.raises(AccountConflictError, match="别名"):
        registry.add(account(tmp_path, "second", "工作联通", "186****5678"))
    with pytest.raises(AccountConflictError, match="脱敏"):
        registry.add(account(tmp_path, "third", "家庭联通", "18612345678"))


def test_corrupt_registry_is_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "accounts.json"
    path.write_text("not json", encoding="utf-8")
    registry = AccountRegistry(path)
    with pytest.raises(ConfigurationError, match="无法读取"):
        registry.add(account(tmp_path, "first", "工作联通", "138****1234"))
    assert path.read_text(encoding="utf-8") == "not json"


def test_remove_clears_defaults_without_choosing_global(tmp_path: Path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    first = account(tmp_path, "first", "工作联通", "138****1234")
    second = account(tmp_path, "second", "家庭联通", "186****5678")
    registry.add(first)
    registry.add(second)
    registry.set_global_default(first.id)
    registry.set_provider_default(first.id)

    registry.remove(first.id)

    state = registry.load()
    assert state.global_default is None
    assert state.provider_defaults["china_unicom"] == second.id


def test_migrate_legacy_session_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    legacy = default_session_path("china_unicom")
    save_browser_state(legacy, {"cookies": []})
    registry = AccountRegistry(tmp_path / "config" / "accounts.json")

    first = migrate_legacy_session(registry)
    second = migrate_legacy_session(registry)

    assert first == second
    assert first is not None and first.alias == "我的联通"
    assert legacy.is_file()
    assert registry.resolve() == first


def test_registry_json_never_contains_full_phone(tmp_path: Path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.add(account(tmp_path, "first", "工作联通", "138****1234"))
    raw = json.loads(registry.path.read_text(encoding="utf-8"))
    assert raw["accounts"][0]["masked_phone"] == "138****1234"


def test_update_masked_phone_keeps_account_identity(tmp_path: Path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    original = AccountRecord("first", "工作联通", "china_unicom", None, tmp_path / "first.json")
    registry.add(original)

    updated = registry.update_masked_phone("first", "138****1234")

    assert updated.masked_phone == "138****1234"
    assert updated.id == original.id
