from pathlib import Path
from typing import Self

import pytest
from carrier_usage.auth.china_unicom_web import (
    LOGIN_URL,
    is_allowed_unicom_url,
    login_interactively,
)
from carrier_usage.errors import AuthenticationError, ConfigurationError


def test_login_starts_from_official_query_page() -> None:
    assert LOGIN_URL == "https://iservice.10010.com/e5/query.html"


@pytest.mark.parametrize(
    "url",
    [
        "https://uac.10010.com/oauth2/new_auth",
        "https://wap.10010.com/",
        "https://10010.com/",
        "https://qy.chinaunicom.cn/mobile-h5/login/login.html",
    ],
)
def test_accepts_only_official_unicom_https_urls(url: str) -> None:
    assert is_allowed_unicom_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://uac.10010.com/oauth2/new_auth",
        "https://10010.com.example.org/",
        "https://evil10010.com/",
        "javascript:alert(1)",
        "",
    ],
)
def test_rejects_non_official_or_non_https_urls(url: str) -> None:
    assert not is_allowed_unicom_url(url)


def test_login_reports_missing_optional_browser_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable() -> object:
        raise ModuleNotFoundError("playwright")

    monkeypatch.setattr("carrier_usage.auth.china_unicom_web._load_sync_playwright", unavailable)

    with pytest.raises(ConfigurationError, match="web-login"):
        login_interactively(tmp_path / "session.json")


def test_login_cancel_does_not_write_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_path = tmp_path / "session.json"
    fake = _FakePlaywright(final_url="https://wap.10010.com/home")
    monkeypatch.setattr("carrier_usage.auth.china_unicom_web._load_sync_playwright", lambda: fake)

    with pytest.raises(AuthenticationError, match="已取消"):
        login_interactively(session_path, prompt=lambda _: "q")

    assert not session_path.exists()


def test_login_saves_state_after_official_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_path = tmp_path / "session.json"
    fake = _FakePlaywright(final_url="https://wap.10010.com/home")
    monkeypatch.setattr("carrier_usage.auth.china_unicom_web._load_sync_playwright", lambda: fake)

    login_interactively(session_path, prompt=lambda _: "")

    assert session_path.is_file()
    assert "session-token" in session_path.read_text(encoding="utf-8")


def test_login_rejects_non_official_final_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_path = tmp_path / "session.json"
    fake = _FakePlaywright(final_url="https://example.org/phishing")
    monkeypatch.setattr("carrier_usage.auth.china_unicom_web._load_sync_playwright", lambda: fake)

    with pytest.raises(AuthenticationError, match="不是中国联通官方页面"):
        login_interactively(session_path, prompt=lambda _: "")

    assert not session_path.exists()


class _FakePage:
    def __init__(self, final_url: str) -> None:
        self.url = final_url

    def goto(self, url: str, *, wait_until: str) -> None:
        assert is_allowed_unicom_url(url)
        assert wait_until == "domcontentloaded"


class _FakeContext:
    def __init__(self, final_url: str) -> None:
        self.pages = [_FakePage(final_url)]

    def new_page(self) -> _FakePage:
        return self.pages[0]

    def storage_state(self) -> dict[str, object]:
        return {
            "cookies": [{"name": "session-token", "value": "secret"}],
            "origins": [],
        }

    def close(self) -> None:
        pass


class _FakeBrowser:
    def __init__(self, final_url: str) -> None:
        self.context = _FakeContext(final_url)

    def new_context(self) -> _FakeContext:
        return self.context

    def close(self) -> None:
        pass


class _FakeChromium:
    def __init__(self, final_url: str) -> None:
        self.browser = _FakeBrowser(final_url)

    def launch(self, *, headless: bool) -> _FakeBrowser:
        assert headless is False
        return self.browser


class _FakePlaywright:
    def __init__(self, final_url: str) -> None:
        self.chromium = _FakeChromium(final_url)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        pass
