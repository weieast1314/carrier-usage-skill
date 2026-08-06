"""中国联通官方网页只读业务客户端。"""

from __future__ import annotations

import asyncio
import json
import re
from calendar import monthrange
from collections.abc import Awaitable, Callable, Mapping
from datetime import date
from pathlib import Path
from typing import NoReturn

import httpx

from carrier_usage.errors import (
    AuthenticationError,
    NetworkError,
    RateLimitError,
    SecondaryAuthenticationRequiredError,
    UpstreamChangedError,
)
from carrier_usage.providers.china_unicom_web_queries import (
    parse_balance,
    parse_bill_months,
    parse_contract_bill,
    parse_invoices,
    parse_monthly_bill,
    parse_payments,
    parse_rebates,
)
from carrier_usage.web_models import (
    BalanceInfo,
    ContractBill,
    InvoiceRecord,
    MonthlyBill,
    PaymentRecord,
    RebateRecord,
)
from carrier_usage.web_session import load_browser_state

BALANCE_URL = "https://mxx.client.10010.com/servicequerybusiness/balancenew/accountBalancenew.htm"
BALANCE_REFERER = "https://imgxx.client.10010.com/shengyuhuafeiwt2024/index.html#/"
BILL_MONTHS_URL = "https://m.client.10010.com/serviceimportantbusiness/phoneBill/queryMonths"
BILL_DETAIL_URL = "https://m.client.10010.com/serviceimportantbusiness/phoneBill/queryDetail"
BILL_REFERER = "https://img.client.10010.com/WThuafeiyuzhangdan/index.html#/"
PAYMENTS_URL = "https://upay.10010.com/npfweb/NpfQueryWeb/feeSearch/queryOrderNew"
PAYMENTS_REFERER = "https://upay.10010.com/upayWeb/home/feeSearch"
INVOICES_URL = "https://mxx.client.10010.com/serviceimportantbusiness/queryNew/einvoicelist.htm"
INVOICES_REFERER = "https://imgxx.client.10010.com/dianzifapiaowt2024/index.html#/"
GRANTS_URL = (
    "https://mxx.client.10010.com/servicequerybusiness/grantsAndContractRebates/contractRebate"
)
REBATES_URL = "https://mxx.client.10010.com/servicequerybusiness/rebatesAndGrants/queryDatas"
REBATES_REFERER = "https://imgxx.client.10010.com/fanfeiyuzengkuan/index.html#/"
CONTRACT_BILLS_URL = "https://m.client.10010.com/servicebusiness/query/queryFinancialCBDetail"
CONTRACT_BILLS_REFERER = "https://img.client.10010.com/jinrongzhangdanwt/index.html#/"
USAGE_DETAILS_URL = "https://iservice.10010.com/e4/miniservice/query/detailQuery.html"

# 联通接口已知表示"请求被限流/频控"的业务 code
UNICOM_RATE_LIMIT_CODES = frozenset(
    {
        "0002",  # 系统繁忙，请稍后再试
        "1003",  # 操作过于频繁
        "2001",  # 访问过于频繁
        "5001",  # 请求频率超限
        "busy",  # 部分接口用字符串 busy 表示限流
    }
)

_RATE_LIMIT_HINT_RE = re.compile(r"频繁|限流|限频|请求过快|操作过于|系统繁忙|稍后再试|try later", re.IGNORECASE)


def _looks_rate_limited(text: str) -> bool:
    """从响应文案中识别联通频控提示。"""
    return bool(_RATE_LIMIT_HINT_RE.search(text))


def raise_for_unicom_payload(payload: Mapping[str, object], query_name: str) -> None:
    """统一识别联通响应的限流 / 会话失效 / 结构变化。

    供 ChinaUnicomWebClient 与 ChinaUnicomWebProvider 复用，避免把上游频控
    误判为会话失效或响应结构变化。
    """
    status = payload.get("code", payload.get("status"))
    status_str = str(status)
    if status_str in {"999999", "1001", "0004"}:
        raise AuthenticationError(f"中国联通{query_name}查询会话已失效，请重新登录")
    if status_str != "0000" and status is not None:
        hint = str(payload.get("msg", payload.get("message", "")))
        if status_str in UNICOM_RATE_LIMIT_CODES or _looks_rate_limited(hint):
            raise RateLimitError(
                f"中国联通{query_name}查询被限流，请稍后重试（{hint or '请求过于频繁'}）"
            )
        raise UpstreamChangedError(f"中国联通{query_name}查询失败或响应结构已变化")


class ChinaUnicomWebClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        session_path: Path,
        max_retries: int = 3,
    ) -> None:
        self._client = client
        self._max_retries = max(1, int(max_retries))
        self._load_session(session_path)

    async def query_balance(self) -> BalanceInfo:
        payload = await self._post(BALANCE_URL, BALANCE_REFERER, {"version": "WT"})
        self._require_success(payload, "剩余话费")
        return parse_balance(payload)

    async def query_bill_months(self) -> tuple[date, ...]:
        payload = await self._post(BILL_MONTHS_URL, BILL_REFERER, {"version": "WT"})
        self._require_success(payload, "账单月份")
        return parse_bill_months(payload)

    async def query_bill(self, month: date) -> MonthlyBill:
        payload = await self._post(
            BILL_DETAIL_URL,
            BILL_REFERER,
            {"version": "WT", "month": month.strftime("%Y%m")},
        )
        self._require_success(payload, "月账单")
        return parse_monthly_bill(payload, month)

    async def query_payments(self, start: date, end: date) -> tuple[PaymentRecord, ...]:
        end_day = monthrange(end.year, end.month)[1]
        payload = await self._get(
            PAYMENTS_URL,
            PAYMENTS_REFERER,
            {
                "startDate": start.isoformat(),
                "endDate": end.replace(day=end_day).isoformat(),
                "pageFlag": "1",
                "queryType": "payfee",
                "webQueryFlag": "webquery",
            },
        )
        return parse_payments(payload)

    async def query_invoices(self, month: date) -> tuple[InvoiceRecord, ...]:
        payload = await self._get(
            INVOICES_URL,
            INVOICES_REFERER,
            {"version": "WT", "month": month.strftime("%Y%m")},
        )
        self._require_success_if_present(payload, "电子发票")
        return parse_invoices(payload)

    async def query_rebates(self) -> tuple[RebateRecord, ...]:
        grants_payload = await self._post(GRANTS_URL, REBATES_REFERER, {"version": "WT"})
        self._require_success(grants_payload, "赠款记录")
        rebates_payload = await self._post(
            REBATES_URL,
            REBATES_REFERER,
            {"version": "WT", "qrytype": "0"},
        )
        self._require_success(rebates_payload, "合约返赠")
        return parse_rebates(grants_payload, "grant") + parse_rebates(
            rebates_payload, "contract_rebate"
        )

    async def query_contract_bill(self, month: date) -> ContractBill:
        payload = await self._post(
            CONTRACT_BILLS_URL,
            CONTRACT_BILLS_REFERER,
            {"version": "WT", "writeoffmode": "3", "cycleid": month.strftime("%Y%m")},
        )
        self._require_success(payload, "金融合约账单")
        return parse_contract_bill(payload, month)

    async def query_usage_details(self, category: str, month: date) -> NoReturn:
        del category, month
        raise SecondaryAuthenticationRequiredError(
            f"详单查询需要在中国联通官方页面完成短信二次认证：{USAGE_DETAILS_URL}"
        )

    def _load_session(self, path: Path) -> None:
        state = load_browser_state(path)
        cookies = state.get("cookies")
        accepted = 0
        if isinstance(cookies, list):
            for item in cookies:
                if not isinstance(item, dict):
                    continue
                name, value, domain = item.get("name"), item.get("value"), item.get("domain")
                if not all(isinstance(part, str) for part in (name, value, domain)):
                    continue
                normalized = str(domain).lower().lstrip(".")
                if normalized != "10010.com" and not normalized.endswith(".10010.com"):
                    continue
                self._client.cookies.set(str(name), str(value), domain=str(domain))
                accepted += 1
        if accepted == 0:
            raise AuthenticationError("会话中没有中国联通官方 Cookie，请重新扫码登录")

    async def _post(self, url: str, referer: str, data: Mapping[str, str]) -> Mapping[str, object]:
        return await self._request(
            lambda: self._client.post(
                url,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": referer,
                },
                data=dict(data),
                timeout=15.0,
            )
        )

    async def _get(self, url: str, referer: str, params: Mapping[str, str]) -> Mapping[str, object]:
        return await self._request(
            lambda: self._client.get(
                url,
                headers={"Accept": "application/json, text/plain, */*", "Referer": referer},
                params=dict(params),
                timeout=15.0,
            )
        )

    async def _request(self, send: "Callable[[], Awaitable[httpx.Response]]") -> Mapping[str, object]:
        """执行请求并在被上游限流时做有限次指数退避重试。"""
        last_limit: RateLimitError | None = None
        for attempt in range(self._max_retries):
            try:
                response = await send()
                response.raise_for_status()
            except httpx.HTTPError as error:
                raise NetworkError("中国联通网页查询失败") from error
            try:
                payload = response.json()
            except json.JSONDecodeError as error:
                raise UpstreamChangedError("中国联通网页查询返回了无效 JSON") from error
            if not isinstance(payload, dict):
                raise UpstreamChangedError("中国联通网页查询响应结构已变化")
            payload = {str(key): value for key, value in payload.items()}
            try:
                self._require_success(payload, "网页")
            except RateLimitError as error:
                last_limit = error
                if attempt + 1 >= self._max_retries:
                    break
                backoff = self._backoff_seconds(attempt, error.retry_after)
                await asyncio.sleep(backoff)
                continue
            return payload
        # 重试耗尽后，若最后一次是限流则抛出，否则按结构变化处理
        if last_limit is not None:
            raise last_limit
        raise UpstreamChangedError("中国联通网页查询响应结构已变化")

    @staticmethod
    def _backoff_seconds(attempt: int, retry_after: int | None) -> int:
        if retry_after and retry_after > 0:
            return retry_after
        # 指数退避：2s, 4s, 8s ...
        return 2 ** (attempt + 1)

    @staticmethod
    def _require_success(payload: Mapping[str, object], query_name: str) -> None:
        raise_for_unicom_payload(payload, query_name)

    @classmethod
    def _require_success_if_present(cls, payload: Mapping[str, object], query_name: str) -> None:
        if "code" in payload or "status" in payload:
            cls._require_success(payload, query_name)
