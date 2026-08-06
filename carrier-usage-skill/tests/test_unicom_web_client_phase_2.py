from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from carrier_usage.errors import SecondaryAuthenticationRequiredError
from carrier_usage.providers.china_unicom_web_client import (
    CONTRACT_BILLS_URL,
    PAYMENTS_URL,
    ChinaUnicomWebClient,
)
from carrier_usage.web_session import save_browser_state


def session_file(tmp_path: Path) -> Path:
    path = tmp_path / "session.json"
    save_browser_state(
        path,
        {"cookies": [{"name": "SESSION", "value": "private", "domain": ".10010.com"}]},
    )
    return path


@pytest.mark.asyncio
@respx.mock
async def test_query_payments_uses_read_only_get_and_date_range(tmp_path: Path) -> None:
    route = respx.get(PAYMENTS_URL).mock(return_value=httpx.Response(200, json={"orderList": []}))
    async with httpx.AsyncClient() as http:
        client = ChinaUnicomWebClient(http, session_file(tmp_path))
        assert await client.query_payments(date(2026, 7, 1), date(2026, 8, 1)) == ()
    query = route.calls.last.request.url.params
    assert query["startDate"] == "2026-07-01"
    assert query["queryType"] == "payfee"


@pytest.mark.asyncio
@respx.mock
async def test_query_contract_bill_posts_read_only_cycle(tmp_path: Path) -> None:
    route = respx.post(CONTRACT_BILLS_URL).mock(
        return_value=httpx.Response(
            200, json={"status": "0000", "data": {"allfree": "0", "billinfos": []}}
        )
    )
    async with httpx.AsyncClient() as http:
        client = ChinaUnicomWebClient(http, session_file(tmp_path))
        await client.query_contract_bill(date(2026, 8, 1))
    assert b"cycleid=202608" in route.calls.last.request.content
    assert b"writeoffmode=3" in route.calls.last.request.content


@pytest.mark.asyncio
async def test_usage_details_requires_official_secondary_auth_without_request(
    tmp_path: Path,
) -> None:
    async with httpx.AsyncClient() as http:
        client = ChinaUnicomWebClient(http, session_file(tmp_path))
        with pytest.raises(SecondaryAuthenticationRequiredError, match="短信二次认证"):
            await client.query_usage_details("data", date(2026, 8, 1))
