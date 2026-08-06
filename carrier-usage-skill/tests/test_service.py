from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from carrier_usage.errors import NetworkError, RateLimitError
from carrier_usage.models import (
    AccountSnapshot,
    Allowance,
    AllowanceCategory,
    AllowanceScope,
    AllowanceUnit,
    Capability,
    CapabilityResult,
    LineRole,
    LineUsage,
    PlanInfo,
    QueryScope,
    ResourceUsage,
    Status,
)
from carrier_usage.providers.base import AuthSession
from carrier_usage.service import RefreshGuard, query_snapshot


class FakeProvider:
    provider_id = "fake_carrier"

    def __init__(self) -> None:
        self.authentication_count = 0

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.ACCOUNT, Capability.ALLOWANCES, Capability.PLAN})

    async def authenticate(self) -> AuthSession:
        self.authentication_count += 1
        return AuthSession(provider=self.provider_id)

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot("138****8000", Decimal("42.15"), Decimal("19.00"), None)

    async def get_allowances(
        self, scope: QueryScope = QueryScope.OVERVIEW
    ) -> tuple[Allowance, ...]:
        return (
            Allowance(
                AllowanceCategory.DATA,
                AllowanceScope.GENERAL,
                "通用流量",
                AllowanceUnit.BYTE,
                10 * 1024**3,
                3 * 1024**3,
                7 * 1024**3,
                0,
                False,
            ),
        )

    async def get_plan(self) -> PlanInfo:
        return PlanInfo(Status.AVAILABLE, "测试套餐", Decimal("29.00"))

    async def get_subscriptions(self) -> CapabilityResult:
        raise AssertionError("不支持的能力不应被调用")

    async def get_lines(self) -> tuple[LineUsage, ...]:
        return ()

    async def get_resources(self) -> tuple[ResourceUsage, ...]:
        return ()


class ScopedProvider(FakeProvider):
    def __init__(self, *, fail_resources: bool = False) -> None:
        super().__init__()
        self.calls: set[str] = set()
        self.fail_resources = fail_resources

    def capabilities(self) -> frozenset[Capability]:
        return frozenset(
            {
                Capability.ACCOUNT,
                Capability.ALLOWANCES,
                Capability.PLAN,
                Capability.MEMBERS,
                Capability.RESOURCES,
            }
        )

    async def get_account(self) -> AccountSnapshot:
        self.calls.add("account")
        return await super().get_account()

    async def get_allowances(
        self, scope: QueryScope = QueryScope.OVERVIEW
    ) -> tuple[Allowance, ...]:
        self.calls.add("allowances")
        return await super().get_allowances(scope)

    async def get_plan(self) -> PlanInfo:
        self.calls.add("plan")
        return await super().get_plan()

    async def get_lines(self) -> tuple[LineUsage, ...]:
        self.calls.add("lines")
        return (LineUsage("138****8001", LineRole.SECONDARY, ()),)

    async def get_resources(self) -> tuple[ResourceUsage, ...]:
        self.calls.add("resources")
        if self.fail_resources:
            raise NetworkError("资源接口不可用")
        return (ResourceUsage("联通云盘", "普通会员", 1, 2, "生效中"),)


@pytest.mark.asyncio
async def test_query_snapshot_authenticates_once_and_marks_unsupported_capability() -> None:
    provider = FakeProvider()
    now = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

    snapshot = await query_snapshot(provider, now)

    assert provider.authentication_count == 1
    assert snapshot.schema_version == "1.0"
    assert snapshot.provider == "fake_carrier"
    assert snapshot.subscriptions.status is Status.UNSUPPORTED
    assert snapshot.warnings == ("当前运营商不支持查询增值业务",)


def test_refresh_guard_rejects_queries_inside_minimum_interval(tmp_path: Path) -> None:
    guard = RefreshGuard(tmp_path / "query-state.json", minimum_seconds=300)
    first = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    guard.record("fake_carrier", first)

    with pytest.raises(RateLimitError, match="请在 1 秒后重试"):
        guard.check("fake_carrier", first + timedelta(seconds=299))

    guard.check("fake_carrier", first + timedelta(seconds=300))


@pytest.mark.asyncio
async def test_members_scope_only_queries_account_and_lines() -> None:
    provider = ScopedProvider()

    snapshot = await query_snapshot(provider, datetime(2026, 8, 4, tzinfo=UTC), QueryScope.MEMBERS)

    assert provider.calls == {"account", "lines"}
    assert snapshot.allowances == ()
    assert snapshot.lines[0].phone_masked == "138****8001"


@pytest.mark.asyncio
async def test_all_scope_keeps_results_when_resources_fail() -> None:
    provider = ScopedProvider(fail_resources=True)

    snapshot = await query_snapshot(provider, datetime(2026, 8, 4, tzinfo=UTC), QueryScope.ALL)

    assert snapshot.account.phone_masked == "138****8000"
    assert snapshot.allowances
    assert "其他资源查询失败" in snapshot.warnings


@pytest.mark.asyncio
async def test_snapshot_carries_local_account_identity() -> None:
    snapshot = await query_snapshot(
        FakeProvider(),
        datetime(2026, 8, 4, tzinfo=UTC),
        account_id="unicom-work",
        account_alias="工作联通",
    )

    assert snapshot.account_id == "unicom-work"
    assert snapshot.account_alias == "工作联通"


def test_refresh_guard_isolates_accounts(tmp_path: Path) -> None:
    guard = RefreshGuard(tmp_path / "query-state.json", 300)
    now = datetime(2026, 8, 4, tzinfo=UTC)
    guard.record("china_unicom:unicom-work", now)

    guard.check("china_unicom:unicom-home", now)
