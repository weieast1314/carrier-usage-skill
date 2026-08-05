from datetime import date
from decimal import Decimal

import pytest
from carrier_usage.errors import ConfigurationError
from carrier_usage.web_models import BalanceInfo, parse_month, parse_month_range


def test_parse_month_accepts_year_month_and_rejects_invalid() -> None:
    assert parse_month("2026-08") == date(2026, 8, 1)
    with pytest.raises(ConfigurationError, match="YYYY-MM"):
        parse_month("2026/08")


def test_balance_rejects_negative_consumption() -> None:
    with pytest.raises(ValueError, match="consumed_cny"):
        BalanceInfo(Decimal(1), Decimal(1), Decimal(0), Decimal(-1), None)


def test_parse_month_range_accepts_twelve_months_and_rejects_reverse() -> None:
    assert parse_month_range("2025-09", "2026-08") == (
        date(2025, 9, 1),
        date(2026, 8, 1),
    )
    with pytest.raises(ConfigurationError, match="起始月份"):
        parse_month_range("2026-08", "2026-07")
