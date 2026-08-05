import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx
from carrier_usage.config import AppConfig
from carrier_usage.models import (
    AllowanceCategory,
    AllowanceUnit,
    Capability,
    QueryScope,
    Status,
)
from carrier_usage.providers.china_unicom_web import (
    WEB_DETAIL_URL,
    WEB_DISK_URL,
    WEB_SUMMARY_URL,
    ChinaUnicomWebProvider,
)
from carrier_usage.providers.china_unicom_web_client import BALANCE_URL
from carrier_usage.web_session import save_browser_state


def write_session(path: Path) -> None:
    save_browser_state(
        path,
        {
            "cookies": [
                {
                    "name": "SESSION",
                    "value": "private",
                    "domain": ".10010.com",
                    "path": "/",
                    "secure": True,
                }
            ],
            "origins": [],
        },
    )


def load_fixture(name: str) -> dict[str, object]:
    fixture = Path(__file__).parent / "fixtures" / "unicom" / name
    return json.loads(fixture.read_text(encoding="utf-8"))


@pytest.mark.asyncio
@respx.mock
async def test_web_provider_parses_qr_login_summary(tmp_path: Path) -> None:
    session_path = tmp_path / "session.json"
    write_session(session_path)
    payload = {
        "userInfo": {
            "usernumber": "13800138000",
            "packageName": "测试套餐39元",
        },
        "resource": {
            "dataList": [
                {"remainTitle": "剩余话费", "number": "271.64", "unit": "元"},
                {"remainTitle": "剩余流量", "number": "93.72", "unit": "GB"},
                {"remainTitle": "剩余语音", "number": "999", "unit": "分钟"},
            ]
        },
    }
    route = respx.post(WEB_SUMMARY_URL).mock(
        return_value=httpx.Response(
            200,
            content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"content-type": "text/plain;charset=ISO-8859-1"},
        )
    )
    config = AppConfig("china_unicom", 300, session_path)
    async with httpx.AsyncClient() as client:
        provider = ChinaUnicomWebProvider(config, client)
        await provider.authenticate()
        account = await provider.get_account()
        plan = await provider.get_plan()
        allowances = await provider.get_allowances()

    request_headers = route.calls.last.request.headers
    assert request_headers["referer"] == "https://iservice.10010.com/"
    assert request_headers["accept"] == "application/json, text/plain, */*"
    assert request_headers["content-type"] == "application/x-www-form-urlencoded"
    assert account.phone_masked == "138****8000"
    assert account.balance_cny == Decimal("271.64")
    assert plan.status is Status.AVAILABLE
    assert plan.name == "测试套餐39元"
    assert plan.monthly_fee_cny is None
    assert allowances[0].category is AllowanceCategory.DATA
    assert allowances[0].unit is AllowanceUnit.BYTE
    assert allowances[0].remaining == int(Decimal("93.72") * 1024**3)
    assert allowances[1].category is AllowanceCategory.VOICE
    assert allowances[1].remaining == 999 * 60


@pytest.mark.asyncio
async def test_web_provider_rejects_session_without_official_cookies(tmp_path: Path) -> None:
    session_path = tmp_path / "session.json"
    save_browser_state(
        session_path,
        {
            "cookies": [{"name": "SESSION", "value": "private", "domain": ".example.org"}],
            "origins": [],
        },
    )
    config = AppConfig("china_unicom", 300, session_path)
    async with httpx.AsyncClient() as client:
        provider = ChinaUnicomWebProvider(config, client)
        with pytest.raises(Exception, match="会话中没有中国联通官方 Cookie"):
            await provider.authenticate()


@pytest.mark.asyncio
@respx.mock
async def test_web_provider_queries_detail_members_and_resources(tmp_path: Path) -> None:
    session_path = tmp_path / "session.json"
    write_session(session_path)
    summary = {
        "userInfo": {"usernumber": "13800138000", "packageName": "测试套餐"},
        "resource": {
            "dataList": [
                {"remainTitle": "可用积分", "number": "922", "unit": "分"},
                {"remainTitle": "剩余流量", "number": "93.60", "unit": "GB"},
            ]
        },
    }
    respx.post(WEB_SUMMARY_URL).mock(return_value=httpx.Response(200, json=summary))
    detail_route = respx.post(WEB_DETAIL_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("web_detail.json"))
    )
    disk_route = respx.post(WEB_DISK_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("web_disk.json"))
    )
    respx.post(BALANCE_URL).mock(return_value=httpx.Response(200, json={"code": "1001"}))

    config = AppConfig("china_unicom", 300, session_path)
    async with httpx.AsyncClient() as client:
        provider = ChinaUnicomWebProvider(config, client)
        await provider.authenticate()
        account = await provider.get_account()
        data = await provider.get_allowances(QueryScope.DATA)
        lines = await provider.get_lines()
        resources = await provider.get_resources()

    assert Capability.MEMBERS in provider.capabilities()
    assert Capability.RESOURCES in provider.capabilities()
    assert account.loyalty_points == 922
    assert data[0].total == 90 * 1024**3
    assert lines[0].phone_masked == "138****8000"
    assert resources[0].name == "联通云盘"
    assert detail_route.calls.last.request.content == b"version=WT"
    assert disk_route.calls.last.request.content == b"version=WT"


@pytest.mark.asyncio
@respx.mock
async def test_web_provider_falls_back_to_detail_when_summary_is_empty(
    tmp_path: Path,
) -> None:
    session_path = tmp_path / "session.json"
    write_session(session_path)
    respx.post(WEB_SUMMARY_URL).mock(
        return_value=httpx.Response(
            200, content=b"", headers={"content-type": "application/json;charset=UTF-8"}
        )
    )
    detail_route = respx.post(WEB_DETAIL_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("web_detail.json"))
    )
    respx.post(BALANCE_URL).mock(return_value=httpx.Response(200, json={"code": "1001"}))

    config = AppConfig("china_unicom", 300, session_path)
    async with httpx.AsyncClient() as client:
        provider = ChinaUnicomWebProvider(config, client)
        await provider.authenticate()
        account = await provider.get_account()
        plan = await provider.get_plan()
        allowances = await provider.get_allowances()

    assert detail_route.called
    assert account.phone_masked == "138****8000"
    assert account.balance_cny is None
    assert plan.name == "测试套餐39元"
    assert allowances[0].category is AllowanceCategory.DATA


@pytest.mark.asyncio
@respx.mock
async def test_web_provider_uses_dedicated_balance_when_summary_omits_it(
    tmp_path: Path,
) -> None:
    session_path = tmp_path / "session.json"
    write_session(session_path)
    summary = {
        "userInfo": {"usernumber": "13800138000", "packageName": "测试套餐"},
        "resource": {"dataList": []},
    }
    respx.post(WEB_SUMMARY_URL).mock(return_value=httpx.Response(200, json=summary))
    respx.post(BALANCE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "0000",
                "curntbalancecust": "142.35",
                "realfeecustnew": "35.00",
            },
        )
    )

    config = AppConfig("china_unicom", 300, session_path)
    async with httpx.AsyncClient() as client:
        provider = ChinaUnicomWebProvider(config, client)
        await provider.authenticate()
        account = await provider.get_account()

    assert account.balance_cny == Decimal("142.35")
    assert account.current_charges_cny == Decimal("35.00")


def test_web_provider_declares_read_only_business_capabilities() -> None:
    capabilities = ChinaUnicomWebProvider.capabilities()
    for expected in (
        Capability.BALANCE,
        Capability.BILLS,
        Capability.PAYMENTS,
        Capability.INVOICES,
        Capability.REBATES,
        Capability.CONTRACT_BILLS,
        Capability.USAGE_DETAILS_SECONDARY_AUTH,
    ):
        assert expected in capabilities
