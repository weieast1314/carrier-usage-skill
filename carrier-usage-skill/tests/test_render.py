import json
from datetime import UTC, datetime

import pytest
from carrier_usage.models import (
    AccountSnapshot,
    Allowance,
    AllowanceCategory,
    AllowanceScope,
    AllowanceUnit,
    CapabilityResult,
    CarrierSnapshot,
    LineRole,
    LineUsage,
    PlanInfo,
    ResourceUsage,
    Status,
)
from carrier_usage.render import (
    _allowance_summary,
    render_json,
    render_summary,
    snapshot_to_dict,
)
from carrier_usage.service import query_snapshot
from tests.test_service import FakeProvider


@pytest.mark.asyncio
async def test_json_uses_strings_for_decimal_values() -> None:
    snapshot = await query_snapshot(FakeProvider(), datetime(2026, 8, 3, 12, 0, tzinfo=UTC))

    result = json.loads(render_json(snapshot))

    assert result["account"]["balance_cny"] == "42.15"
    assert result["plan"]["monthly_fee_cny"] == "29.00"
    assert result["queried_at"] == "2026-08-03T12:00:00+00:00"


@pytest.mark.asyncio
async def test_summary_is_chinese_and_keeps_phone_masked() -> None:
    snapshot = await query_snapshot(FakeProvider(), datetime(2026, 8, 3, 12, 0, tzinfo=UTC))

    summary = render_summary(snapshot)

    assert "运营商账户：138****8000" in summary
    assert "账户余额：42.15 元" in summary
    assert "测试套餐（29.00 元/月）" in summary
    assert "通用流量：已用 3.00 GB，剩余 7.00 GB" in summary


@pytest.mark.parametrize(
    ("category", "unit", "remaining", "expected"),
    [
        (AllowanceCategory.DATA, AllowanceUnit.BYTE, 2 * 1024**3, "剩余流量：剩余 2.00 GB"),
        (AllowanceCategory.VOICE, AllowanceUnit.SECOND, 600, "剩余语音：剩余 10 分钟"),
        (AllowanceCategory.SMS, AllowanceUnit.COUNT, 8, "剩余短信：剩余 8 条"),
    ],
)
def test_remaining_only_allowance_does_not_invent_zero_usage(
    category: AllowanceCategory,
    unit: AllowanceUnit,
    remaining: int,
    expected: str,
) -> None:
    allowance = Allowance(
        category=category,
        scope=AllowanceScope.GENERAL,
        name=expected.split("：", 1)[0],
        unit=unit,
        total=None,
        used=None,
        remaining=remaining,
        overage=None,
        unlimited=False,
    )

    assert _allowance_summary(allowance) == expected


def test_render_includes_points_members_and_resources() -> None:
    snapshot = CarrierSnapshot(
        schema_version="1.1",
        provider="china_unicom",
        account=AccountSnapshot("138****8000", None, None, None, loyalty_points=922),
        plan=PlanInfo(Status.AVAILABLE, "测试套餐"),
        allowances=(),
        subscriptions=CapabilityResult(Status.UNSUPPORTED),
        queried_at=datetime(2026, 8, 4, tzinfo=UTC),
        lines=(LineUsage("138****8001", LineRole.SECONDARY, ()),),
        resources=(ResourceUsage("联通云盘", "普通会员", 80 * 1024**2, 60 * 1024**3, "生效中"),),
    )

    payload = snapshot_to_dict(snapshot)
    summary = render_summary(snapshot)

    assert payload["lines"][0]["phone_masked"] == "138****8001"  # type: ignore[index]
    assert payload["resources"][0]["used"] == str(80 * 1024**2)  # type: ignore[index]
    assert payload["account"]["loyalty_points"] == "922"  # type: ignore[index]
    assert "可用积分：922" in summary
    assert "副卡 138****8001" in summary
    assert "联通云盘：普通会员" in summary
    assert "13800138001" not in summary
