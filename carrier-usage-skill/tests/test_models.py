from decimal import Decimal

import pytest
from carrier_usage.models import (
    AccountSnapshot,
    Allowance,
    AllowanceCategory,
    AllowanceScope,
    AllowanceUnit,
    LineRole,
    LineUsage,
    ResourceUsage,
)


def test_allowance_rejects_negative_remaining() -> None:
    with pytest.raises(ValueError, match="remaining must be non-negative"):
        Allowance(
            category=AllowanceCategory.DATA,
            scope=AllowanceScope.GENERAL,
            name="通用流量",
            unit=AllowanceUnit.BYTE,
            total=100,
            used=101,
            remaining=-1,
            overage=1,
            unlimited=False,
        )


def test_account_uses_decimal_currency() -> None:
    account = AccountSnapshot(
        phone_masked="138****8000",
        balance_cny=Decimal("42.15"),
        current_charges_cny=Decimal("19.00"),
        amount_due_cny=Decimal("0.00"),
    )

    assert account.balance_cny == Decimal("42.15")


def test_account_rejects_negative_loyalty_points() -> None:
    with pytest.raises(ValueError, match="loyalty_points must be non-negative"):
        AccountSnapshot(None, None, None, None, loyalty_points=-1)


def test_line_usage_requires_masked_phone() -> None:
    with pytest.raises(ValueError, match="成员号码必须脱敏"):
        LineUsage("13800138000", LineRole.SECONDARY, ())


def test_resource_usage_rejects_negative_capacity() -> None:
    with pytest.raises(ValueError, match="used must be non-negative"):
        ResourceUsage("联通云盘", "普通会员", -1, 60 * 1024**3, "active")
