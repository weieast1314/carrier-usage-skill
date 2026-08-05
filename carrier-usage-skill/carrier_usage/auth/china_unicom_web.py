"""通过中国联通官方网页完成交互式短信登录。"""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from carrier_usage.errors import AuthenticationError, ConfigurationError
from carrier_usage.web_session import save_browser_state

_ALLOWED_DOMAINS = ("10010.com", "chinaunicom.cn")
LOGIN_URL = "https://iservice.10010.com/e5/query.html"


def is_allowed_unicom_url(url: str) -> bool:
    """仅接受中国联通控制的 HTTPS 主域及其子域。"""

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not hostname:
        return False
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in _ALLOWED_DOMAINS)


def login_interactively(
    session_path: Path,
    *,
    prompt: Callable[[str], str] = input,
) -> None:
    """打开官方登录页，并在用户确认后保存浏览器状态。"""

    try:
        playwright_manager = _load_sync_playwright()
    except ModuleNotFoundError as error:
        raise ConfigurationError(
            "缺少网页登录组件，请安装 carrier-usage-skill[web-login]，"
            "然后执行 playwright install chromium"
        ) from error

    try:
        with playwright_manager as playwright:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context()
            try:
                page = context.new_page()
                page.goto(LOGIN_URL, wait_until="domcontentloaded")
                answer = prompt(
                    "请在中国联通查询页点击“请登录”，优先使用中国联通 APP 扫码登录。"
                    "登录成功后按回车保存会话，输入 q 取消："
                )
                if answer.strip().lower() in {"q", "quit", "取消"}:
                    raise AuthenticationError("中国联通网页登录已取消")
                final_page = context.pages[-1] if context.pages else page
                if not is_allowed_unicom_url(final_page.url):
                    raise AuthenticationError("登录后的页面不是中国联通官方页面，已拒绝保存会话")
                state = context.storage_state()
                if not state.get("cookies"):
                    raise AuthenticationError("未检测到中国联通登录会话，请确认登录成功后重试")
                save_browser_state(session_path, state)
            finally:
                context.close()
                browser.close()
    except AuthenticationError:
        raise
    except Exception as error:
        raise AuthenticationError("无法完成中国联通官方网页登录") from error


def _load_sync_playwright() -> Any:
    playwright_sync = import_module("playwright.sync_api")
    return playwright_sync.sync_playwright()
