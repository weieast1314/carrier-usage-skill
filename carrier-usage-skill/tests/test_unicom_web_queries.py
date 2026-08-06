from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from carrier_usage.providers.china_unicom_web_client import (
    BALANCE_REFERER,
    BALANCE_URL,
    BILL_DETAIL_URL,
    ChinaUnicomWebClient,
)
from carrier_usage.providers.china_unicom_web_queries import (
    parse_balance,
    parse_bill_months,
    parse_monthly_bill,
)
from carrier_usage.web_session import save_browser_state

BALANCE_PAYLOAD = {
    "code": "0000",
    "queryTime": "2026-08-05 10:20:30",
    "curntbalancecust": "142.35",
    "newCarryOverArrears": "157.35",
    "newDepositForTheMonth": "20.00",
    "realfeecustnew": "35.00",
}


def session_file(tmp_path: Path) -> Path:
    path = tmp_path / "session.json"
    save_browser_state(
        path,
        {"cookies": [{"name": "SESSION", "value": "private", "domain": ".10010.com"}]},
    )
    return path


def test_parse_balance_maps_official_fields() -> None:
    result = parse_balance(BALANCE_PAYLOAD)
    assert result.remaining_cny == Decimal("142.35")
    assert result.carried_cny == Decimal("157.35")
    assert result.deposited_cny == Decimal("20.00")
    assert result.consumed_cny == Decimal("35.00")


@pytest.mark.asyncio
@respx.mock
async def test_query_balance_uses_read_only_official_endpoint(tmp_path: Path) -> None:
    route = respx.post(BALANCE_URL).mock(return_value=httpx.Response(200, json=BALANCE_PAYLOAD))
    async with httpx.AsyncClient() as http:
        client = ChinaUnicomWebClient(http, session_file(tmp_path))
        result = await client.query_balance()
    request = route.calls.last.request
    assert request.headers["referer"] == BALANCE_REFERER
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert request.content == b"version=WT"
    assert result.remaining_cny == Decimal("142.35")


def test_parse_bill_months_normalizes_official_year_month_items() -> None:
    payload = {"code": "0000", "data": {"months": [{"historyYear": "2026", "historyMonth": "8"}]}}
    assert parse_bill_months(payload) == (date(2026, 8, 1),)


def test_parse_monthly_bill_keeps_fee_semantics() -> None:
    payload = {
        "code": "0000",
        "data": {
            "totalprice": "47.25",
            "totalDiscount": "2.00",
            "totalspayfee": "45.25",
            "allpayfee": "45.25",
            "allnopayfee": "0.00",
            "adjustment": {"rebateDeduction": "0.00"},
            "acctBillList": [
                {"bill": {"integrateitem": "套餐费", "originalFee": "39.00", "payableFee": "37.00"}}
            ],
            "userBillList": [],
        },
    }
    bill = parse_monthly_bill(payload, date(2026, 8, 1))
    assert bill.consumed_cny == Decimal("45.25")
    assert bill.lines[0].name == "套餐费"


@pytest.mark.asyncio
@respx.mock
async def test_query_bill_posts_month_parameter(tmp_path: Path) -> None:
    route = respx.post(BILL_DETAIL_URL).mock(
        return_value=httpx.Response(
            200, json={"code": "0000", "data": {"totalspayfee": "0", "acctBillList": []}}
        )
    )
    async with httpx.AsyncClient() as http:
        client = ChinaUnicomWebClient(http, session_file(tmp_path))
        await client.query_bill(date(2026, 8, 1))
    assert b"month=202608" in route.calls.last.request.content
