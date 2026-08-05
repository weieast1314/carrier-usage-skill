"""通过中国联通网上营业厅扫码会话查询账户汇总。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from carrier_usage.config import AppConfig
from carrier_usage.errors import (
    AuthenticationError,
    CarrierUsageError,
    NetworkError,
    UpstreamChangedError,
)
from carrier_usage.models import (
    AccountSnapshot,
    Allowance,
    AllowanceCategory,
    AllowanceScope,
    AllowanceUnit,
    Capability,
    CapabilityResult,
    LineUsage,
    PlanInfo,
    QueryScope,
    ResourceUsage,
    Status,
)
from carrier_usage.providers.base import AuthSession
from carrier_usage.providers.china_unicom_web_client import ChinaUnicomWebClient
from carrier_usage.providers.china_unicom_web_detail import (
    parse_web_allowances,
    parse_web_lines,
    parse_web_resources,
)
from carrier_usage.redaction import mask_phone
from carrier_usage.web_session import load_browser_state

WEB_SUMMARY_URL = "https://www.10010.com/mall/service/query/userinfoquery"
WEB_QUERY_REFERER = "https://iservice.10010.com/"
WEB_DETAIL_URL = "https://mxx.client.10010.com/servicequerybusiness/operationservice/queryOcsPackageFlowLeftContentRevisedInJune"
WEB_DISK_URL = (
    "https://mxx.client.10010.com/servicequerybusiness/operationservice/remainingQueryWebDiskTab"
)
WEB_DETAIL_REFERER = "https://imgxx.client.10010.com/yuliangchaxunsfwt/index.html#/"


@dataclass(frozen=True, slots=True)
class WebAuthSession(AuthSession):
    """已加载到 HTTP 客户端但不暴露 Cookie 的网页登录会话。"""


class ChinaUnicomWebProvider:
    """使用中国联通 APP 扫码获得的网上营业厅会话。"""

    provider_id = "china_unicom"

    def __init__(self, config: AppConfig, client: httpx.AsyncClient) -> None:
        if config.unicom_session_path is None:
            raise AuthenticationError("缺少中国联通扫码登录会话")
        self._session_path = config.unicom_session_path
        self._client = client
        self._business_client: ChinaUnicomWebClient | None = None
        self._payload: Mapping[str, object] | None = None
        self._detail_payload: Mapping[str, object] | None = None
        self._disk_payload: Mapping[str, object] | None = None
        self._summary_fallback = False

    @classmethod
    def capabilities(cls) -> frozenset[Capability]:
        return frozenset(
            {
                Capability.ACCOUNT,
                Capability.BALANCE,
                Capability.BILLS,
                Capability.PAYMENTS,
                Capability.INVOICES,
                Capability.REBATES,
                Capability.CONTRACT_BILLS,
                Capability.USAGE_DETAILS_SECONDARY_AUTH,
                Capability.ALLOWANCES,
                Capability.PLAN,
                Capability.MEMBERS,
                Capability.RESOURCES,
            }
        )

    async def authenticate(self) -> WebAuthSession:
        state = load_browser_state(self._session_path)
        cookies = state.get("cookies")
        accepted = 0
        if isinstance(cookies, list):
            for item in cookies:
                if not isinstance(item, dict):
                    continue
                name, value, domain = item.get("name"), item.get("value"), item.get("domain")
                if not isinstance(name, str):
                    continue
                if not isinstance(value, str):
                    continue
                if not isinstance(domain, str):
                    continue
                normalized = domain.lower().lstrip(".")
                if normalized != "10010.com" and not normalized.endswith(".10010.com"):
                    continue
                self._client.cookies.set(name, value, domain=domain)
                accepted += 1
        if accepted == 0:
            raise AuthenticationError("会话中没有中国联通官方 Cookie，请重新扫码登录")
        self._business_client = ChinaUnicomWebClient(self._client, self._session_path)
        self._payload = await self._query_summary()
        return WebAuthSession(provider=self.provider_id)

    async def get_account(self) -> AccountSnapshot:
        payload = self._require_payload()
        user_info = _mapping(payload.get("userInfo"))
        phone = user_info.get("usernumber")
        masked = mask_phone(phone) if isinstance(phone, str) and phone.isdigit() else None
        balance = _find_decimal(payload, "话费")
        current_charges: Decimal | None = None
        if balance is None and self._business_client is not None:
            try:
                balance_info = await self._business_client.query_balance()
            except CarrierUsageError:
                pass
            else:
                balance = balance_info.remaining_cny
                current_charges = balance_info.consumed_cny
        points = _find_decimal(payload, "积分")
        return AccountSnapshot(
            masked,
            balance,
            current_charges,
            None,
            loyalty_points=int(points) if points is not None else None,
        )

    async def get_allowances(
        self, scope: QueryScope = QueryScope.OVERVIEW
    ) -> tuple[Allowance, ...]:
        if scope is QueryScope.OVERVIEW and self._summary_fallback:
            payload = await self._query_detail()
            return tuple(
                item
                for category in AllowanceCategory
                for item in parse_web_allowances(payload, category)
            )
        if scope in {QueryScope.DATA, QueryScope.VOICE, QueryScope.SMS, QueryScope.ALL}:
            payload = await self._query_detail()
            categories = {
                QueryScope.DATA: (AllowanceCategory.DATA,),
                QueryScope.VOICE: (AllowanceCategory.VOICE,),
                QueryScope.SMS: (AllowanceCategory.SMS,),
                QueryScope.ALL: tuple(AllowanceCategory),
            }[scope]
            return tuple(
                item for category in categories for item in parse_web_allowances(payload, category)
            )
        payload = self._require_payload()
        allowances: list[Allowance] = []
        for item in _data_list(payload):
            title = str(item.get("remainTitle") or "")
            number = _decimal(item.get("number"))
            unit = str(item.get("unit") or "")
            if number is None:
                continue
            if "流量" in title:
                remaining = _data_bytes(number, unit)
                category, allowance_unit = AllowanceCategory.DATA, AllowanceUnit.BYTE
            elif "语音" in title:
                remaining = int(number * 60) if unit in {"分钟", "分"} else int(number)
                category, allowance_unit = AllowanceCategory.VOICE, AllowanceUnit.SECOND
            elif "短信" in title:
                remaining = int(number)
                category, allowance_unit = AllowanceCategory.SMS, AllowanceUnit.COUNT
            else:
                continue
            allowances.append(
                Allowance(
                    category=category,
                    scope=AllowanceScope.GENERAL,
                    name=title,
                    unit=allowance_unit,
                    total=None,
                    used=None,
                    remaining=remaining,
                    overage=None,
                    unlimited=False,
                )
            )
        if not allowances:
            raise UpstreamChangedError("中国联通网页汇总中没有可识别的套餐余量")
        return tuple(allowances)

    async def get_plan(self) -> PlanInfo:
        user_info = _mapping(self._require_payload().get("userInfo"))
        name = user_info.get("packageName")
        return PlanInfo(
            status=Status.AVAILABLE if isinstance(name, str) and name else Status.PARTIAL,
            name=name if isinstance(name, str) and name else None,
        )

    async def get_subscriptions(self) -> CapabilityResult:
        return CapabilityResult(status=Status.UNSUPPORTED)

    async def get_lines(self) -> tuple[LineUsage, ...]:
        return parse_web_lines(await self._query_detail())

    async def get_resources(self) -> tuple[ResourceUsage, ...]:
        return parse_web_resources(await self._query_disk())

    async def _query_summary(self) -> Mapping[str, object]:
        try:
            response = await self._client.post(
                WEB_SUMMARY_URL,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": WEB_QUERY_REFERER,
                },
                timeout=15.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise NetworkError("中国联通网页汇总查询失败") from error
        if not response.content:
            detail = await self._query_detail()
            self._summary_fallback = True
            return {
                "userInfo": {
                    "usernumber": detail.get("mobile"),
                    "packageName": detail.get("packageName"),
                },
                "resource": {"dataList": []},
            }
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise UpstreamChangedError("中国联通网页汇总返回了无效 JSON") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("userInfo"), dict):
            raise AuthenticationError("中国联通扫码会话已失效，请重新登录")
        return {str(key): value for key, value in payload.items()}

    async def _query_detail(self) -> Mapping[str, object]:
        if self._detail_payload is None:
            self._detail_payload = await self._query_web_resource(
                WEB_DETAIL_URL, "中国联通网页余量明细查询失败"
            )
        return self._detail_payload

    async def _query_disk(self) -> Mapping[str, object]:
        if self._disk_payload is None:
            self._disk_payload = await self._query_web_resource(
                WEB_DISK_URL, "中国联通网页云盘查询失败"
            )
        return self._disk_payload

    async def _query_web_resource(self, url: str, network_message: str) -> Mapping[str, object]:
        try:
            response = await self._client.post(
                url,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": WEB_DETAIL_REFERER,
                },
                data={"version": "WT"},
                timeout=15.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise NetworkError(network_message) from error
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise UpstreamChangedError("中国联通网页明细返回了无效 JSON") from error
        if not isinstance(payload, dict) or str(payload.get("code")) != "0000":
            raise AuthenticationError("中国联通扫码会话已失效，请重新登录")
        return {str(key): value for key, value in payload.items()}

    def _require_payload(self) -> Mapping[str, object]:
        if self._payload is None:
            raise AuthenticationError("尚未验证中国联通扫码会话")
        return self._payload


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}


def _data_list(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    resource = _mapping(payload.get("resource"))
    items = resource.get("dataList")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _find_decimal(payload: Mapping[str, object], title_fragment: str) -> Decimal | None:
    for item in _data_list(payload):
        if title_fragment in str(item.get("remainTitle") or ""):
            return _decimal(item.get("number"))
    return None


def _data_bytes(number: Decimal, unit: str) -> int:
    multiplier = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
    }.get(unit.upper())
    if multiplier is None:
        raise UpstreamChangedError(f"中国联通返回了未知流量单位：{unit}")
    return int(number * multiplier)
