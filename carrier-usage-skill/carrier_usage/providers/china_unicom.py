"""中国联通响应解析器。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation

from carrier_usage.errors import UpstreamChangedError
from carrier_usage.models import (
    AccountSnapshot,
    Allowance,
    AllowanceCategory,
    AllowanceScope,
    AllowanceUnit,
    PlanInfo,
    Status,
)
from carrier_usage.redaction import mask_phone

_MEBIBYTE = 1024**2


def parse_account(balance: Mapping[str, object], bill: Mapping[str, object]) -> AccountSnapshot:
    """把联通余额和账单响应转换为统一账户快照。"""

    balance_data = _payload_data(balance)
    bill_data = _payload_data(bill)
    current_charges = _decimal(bill_data.get("realPayFee"))
    if current_charges is None:
        current_charges = _decimal(
            balance_data.get("totalrealfee", balance_data.get("realfeecustnew"))
        )
    return AccountSnapshot(
        phone_masked=None,
        balance_cny=_decimal(balance_data.get("curntbalancecust")),
        current_charges_cny=current_charges,
        amount_due_cny=_decimal(balance_data.get("allbowefeecust")),
    )


def parse_allowances(payload: Mapping[str, object]) -> tuple[Allowance, ...]:
    """把联通余量响应转换为流量、语音和短信项目。"""

    groups = _usage_groups(payload)
    if groups is None:
        raise UpstreamChangedError("联通用量响应结构已变化")

    allowances: list[Allowance] = []
    for group in groups:
        details = group.get("details")
        if not isinstance(details, list):
            continue
        for raw_item in details:
            if not isinstance(raw_item, dict):
                continue
            item = _string_mapping(raw_item)
            elem_type = _string(item.get("elemType"))
            if elem_type == "3":
                allowances.append(_parse_data_allowance(item))
            elif elem_type == "1":
                allowances.append(_parse_count_allowance(item, AllowanceCategory.VOICE))
            elif elem_type == "2":
                allowances.append(_parse_count_allowance(item, AllowanceCategory.SMS))

    if not allowances:
        raise UpstreamChangedError("联通用量响应结构已变化")
    return tuple(allowances)


def parse_plan(payload: Mapping[str, object]) -> PlanInfo:
    """尽力从商品列表提取主套餐。"""

    data = _payload_data(payload)
    resources = data.get("res")
    if not isinstance(resources, list) or not resources or not isinstance(resources[0], dict):
        return PlanInfo(status=Status.PARTIAL)
    item = _string_mapping(resources[0])
    name = _string(item.get("productName"))
    fee = _decimal(item.get("monthlyFee"))
    effective_at = _date(item.get("effectiveDate"))
    status = Status.AVAILABLE if name or fee is not None else Status.PARTIAL
    return PlanInfo(
        status=status,
        name=name,
        monthly_fee_cny=fee,
        effective_at=effective_at,
    )


def extract_phone(payload: Mapping[str, object]) -> str | None:
    """提取并立即遮蔽主号码。"""

    data = _payload_data(payload)
    resources = data.get("res")
    if not isinstance(resources, list):
        return None
    for raw_item in resources:
        if not isinstance(raw_item, dict):
            continue
        phone = raw_item.get("mainNumber")
        if isinstance(phone, str) and len(phone) == 11 and phone.isdigit():
            return mask_phone(phone)
    return None


def _parse_data_allowance(item: Mapping[str, object]) -> Allowance:
    total_mb = _integer(item.get("total"))
    unlimited = total_mb == 0
    return Allowance(
        category=AllowanceCategory.DATA,
        scope=_flow_scope(_string(item.get("flowType"))),
        name=_string(item.get("addUpItemName")),
        unit=AllowanceUnit.BYTE,
        total=None if unlimited else _bytes_from_mb(total_mb),
        used=_bytes_from_mb(_integer(item.get("use"))),
        remaining=None if unlimited else _bytes_from_mb(_integer(item.get("remain"))),
        overage=_bytes_from_mb(_integer(item.get("xexceedvalue"))),
        unlimited=unlimited,
        expires_at=_date(item.get("endDate")),
        raw_type=_string(item.get("flowType")),
    )


def _parse_count_allowance(item: Mapping[str, object], category: AllowanceCategory) -> Allowance:
    multiplier = 60 if category is AllowanceCategory.VOICE else 1
    unit = AllowanceUnit.SECOND if category is AllowanceCategory.VOICE else AllowanceUnit.COUNT
    return Allowance(
        category=category,
        scope=AllowanceScope.GENERAL,
        name=_string(item.get("addUpItemName")),
        unit=unit,
        total=_scaled_integer(item.get("total"), multiplier),
        used=_scaled_integer(item.get("use"), multiplier),
        remaining=_scaled_integer(item.get("remain"), multiplier),
        overage=_scaled_integer(item.get("xexceedvalue"), multiplier),
        unlimited=False,
    )


def _usage_groups(payload: Mapping[str, object]) -> list[Mapping[str, object]] | None:
    groups: list[Mapping[str, object]] = []
    recognized = False
    for key in ("unshared", "resources"):
        raw_groups = payload.get(key)
        if isinstance(raw_groups, list):
            recognized = True
            groups.extend(_mapping_items(raw_groups))
    share_data = payload.get("shareData")
    if isinstance(share_data, dict):
        recognized = True
        groups.append(_string_mapping(share_data))
    return groups if recognized else None


def _payload_data(payload: Mapping[str, object]) -> Mapping[str, object]:
    data = payload.get("data")
    return _string_mapping(data) if isinstance(data, dict) else payload


def _mapping_items(items: list[object]) -> list[Mapping[str, object]]:
    return [_string_mapping(item) for item in items if isinstance(item, dict)]


def _string_mapping(value: Mapping[object, object]) -> dict[str, object]:
    return {str(key): item for key, item in value.items()}


def _flow_scope(flow_type: str | None) -> AllowanceScope:
    return {
        "1": AllowanceScope.GENERAL,
        "2": AllowanceScope.EXCLUSIVE,
        "3": AllowanceScope.OTHER,
    }.get(flow_type or "", AllowanceScope.OTHER)


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _integer(value: object) -> int | None:
    number = _decimal(value)
    return int(number) if number is not None else None


def _bytes_from_mb(value: int | None) -> int | None:
    return value * _MEBIBYTE if value is not None else None


def _scaled_integer(value: object, multiplier: int) -> int | None:
    number = _integer(value)
    return number * multiplier if number is not None else None


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _date(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("/", "-")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None
