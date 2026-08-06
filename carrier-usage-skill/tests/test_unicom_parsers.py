import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from carrier_usage.errors import UpstreamChangedError
from carrier_usage.models import AllowanceCategory, AllowanceScope, AllowanceUnit, Status
from carrier_usage.providers.china_unicom import (
    extract_phone,
    parse_account,
    parse_allowances,
    parse_plan,
)

FIXTURES = Path(__file__).parent / "fixtures" / "unicom"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_account_normalizes_decimal_currency() -> None:
    account = parse_account(load_fixture("balance.json"), load_fixture("bill.json"))

    assert account.phone_masked is None
    assert account.balance_cny == Decimal("42.15")
    assert account.current_charges_cny == Decimal("19.00")
    assert account.amount_due_cny == Decimal("0.00")


def test_parse_allowances_normalizes_units_and_scopes() -> None:
    allowances = parse_allowances(load_fixture("usage.json"))

    general = next(item for item in allowances if item.name == "通用流量")
    assert general.category is AllowanceCategory.DATA
    assert general.scope is AllowanceScope.GENERAL
    assert general.total == 10 * 1024**3
    assert general.used == 3 * 1024**3
    assert general.remaining == 7 * 1024**3
    assert general.unit is AllowanceUnit.BYTE

    exclusive = next(item for item in allowances if item.name == "应用定向流量")
    assert exclusive.scope is AllowanceScope.EXCLUSIVE

    unlimited = next(item for item in allowances if item.name == "无限流量权益")
    assert unlimited.unlimited is True
    assert unlimited.total is None
    assert unlimited.remaining is None

    voice = next(item for item in allowances if item.category is AllowanceCategory.VOICE)
    assert voice.total == 500 * 60
    assert voice.used == 120 * 60
    assert voice.remaining == 380 * 60
    assert voice.unit is AllowanceUnit.SECOND

    sms = next(item for item in allowances if item.category is AllowanceCategory.SMS)
    assert sms.total == 100
    assert sms.remaining == 88
    assert sms.unit is AllowanceUnit.COUNT


def test_parse_plan_and_phone_from_goods() -> None:
    goods = load_fixture("goods.json")
    goods["data"]["res"][0]["mainNumber"] = "199" + "0000" + "1234"

    plan = parse_plan(goods)

    assert plan.status is Status.AVAILABLE
    assert plan.name == "畅享套餐"
    assert plan.monthly_fee_cny == Decimal("29.00")
    assert plan.effective_at is not None
    assert plan.effective_at.date().isoformat() == "2026-01-01"
    assert extract_phone(goods) == "199****1234"


def test_missing_required_usage_shape_is_upstream_change() -> None:
    with pytest.raises(UpstreamChangedError, match="联通用量响应结构已变化"):
        parse_allowances({"unexpected": []})
