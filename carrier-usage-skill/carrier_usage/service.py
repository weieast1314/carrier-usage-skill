"""Provider 查询编排和本地刷新保护。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from carrier_usage.errors import CarrierUsageError, RateLimitError, UnsupportedCapabilityError
from carrier_usage.models import (
    AccountSnapshot,
    Allowance,
    Capability,
    CapabilityResult,
    CarrierSnapshot,
    LineUsage,
    PlanInfo,
    QueryScope,
    ResourceUsage,
    Status,
)
from carrier_usage.providers.base import CarrierProvider


class RefreshGuard:
    """跨进程保存成功查询时间，避免过度请求运营商接口。"""

    def __init__(self, state_path: Path, minimum_seconds: int) -> None:
        self._state_path = state_path
        self._minimum_seconds = minimum_seconds

    def check(self, provider_id: str, now: datetime) -> None:
        previous = self._read().get(provider_id)
        if previous is None:
            return
        try:
            previous_time = datetime.fromisoformat(previous)
        except ValueError:
            return
        elapsed = (now - previous_time).total_seconds()
        if elapsed < self._minimum_seconds:
            wait_seconds = self._minimum_seconds - max(0, int(elapsed))
            raise RateLimitError(f"查询过于频繁，请在 {wait_seconds} 秒后重试")

    def record(self, provider_id: str, now: datetime) -> None:
        state = self._read()
        state[provider_id] = now.isoformat()
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._state_path.with_suffix(f"{self._state_path.suffix}.tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(self._state_path)

    def _read(self) -> dict[str, str]:
        if not self._state_path.is_file():
            return {}
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(key): value for key, value in raw.items() if isinstance(value, str)}


async def query_snapshot(
    provider: CarrierProvider,
    now: datetime,
    scope: QueryScope = QueryScope.OVERVIEW,
    *,
    account_id: str | None = None,
    account_alias: str | None = None,
) -> CarrierSnapshot:
    """认证一次，按范围获取 Provider 声明支持的数据。"""

    capabilities = provider.capabilities()
    if Capability.ACCOUNT not in capabilities:
        raise UnsupportedCapabilityError("当前运营商不支持账户查询")

    await provider.authenticate()
    account = await provider.get_account()
    allowances: tuple[Allowance, ...] = ()
    plan = PlanInfo(status=Status.UNSUPPORTED)
    subscriptions = CapabilityResult(status=Status.UNSUPPORTED)
    lines: tuple[LineUsage, ...] = ()
    resources: tuple[ResourceUsage, ...] = ()
    warnings: list[str] = []

    if Capability.ALLOWANCES in capabilities and scope in {
        QueryScope.OVERVIEW,
        QueryScope.DATA,
        QueryScope.VOICE,
        QueryScope.SMS,
        QueryScope.ALL,
    }:
        try:
            allowances = await provider.get_allowances(scope)
        except CarrierUsageError:
            if scope is QueryScope.OVERVIEW:
                raise
            warnings.append("用量明细查询失败")

    if scope in {QueryScope.OVERVIEW, QueryScope.ALL}:
        if Capability.PLAN in capabilities:
            try:
                plan = await provider.get_plan()
            except CarrierUsageError:
                if scope is QueryScope.OVERVIEW:
                    raise
                warnings.append("套餐信息查询失败")
        if Capability.SUBSCRIPTIONS in capabilities:
            try:
                subscriptions = await provider.get_subscriptions()
            except CarrierUsageError:
                warnings.append("增值业务查询失败")
        elif scope is QueryScope.OVERVIEW:
            warnings.append("当前运营商不支持查询增值业务")

    if scope in {QueryScope.MEMBERS, QueryScope.ALL}:
        if Capability.MEMBERS in capabilities:
            try:
                lines = await provider.get_lines()
            except CarrierUsageError:
                warnings.append("成员用量查询失败")
        else:
            warnings.append("当前运营商不支持查询成员用量")

    if scope in {QueryScope.RESOURCES, QueryScope.ALL}:
        if Capability.RESOURCES in capabilities:
            try:
                resources = await provider.get_resources()
            except CarrierUsageError:
                warnings.append("其他资源查询失败")
        else:
            warnings.append("当前运营商不支持查询其他资源")

    return CarrierSnapshot(
        schema_version="1.0",
        provider=provider.provider_id,
        account=account,
        plan=plan,
        allowances=allowances,
        subscriptions=subscriptions,
        queried_at=now,
        account_id=account_id,
        account_alias=account_alias,
        lines=lines,
        resources=resources,
        warnings=tuple(warnings),
    )


def account_with_phone(account: AccountSnapshot, phone_masked: str | None) -> AccountSnapshot:
    """保留给需要分步补充号码的 Provider 使用。"""

    return AccountSnapshot(
        phone_masked=phone_masked,
        balance_cny=account.balance_cny,
        current_charges_cny=account.current_charges_cny,
        amount_due_cny=account.amount_due_cny,
        loyalty_points=account.loyalty_points,
    )
