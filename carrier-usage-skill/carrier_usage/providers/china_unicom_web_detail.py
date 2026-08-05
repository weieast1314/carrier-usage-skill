"""解析中国联通网上营业厅余量和其他资源响应。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation

from carrier_usage.errors import UpstreamChangedError
from carrier_usage.models import (
    Allowance,
    AllowanceCategory,
    AllowanceScope,
    AllowanceUnit,
    LineRole,
    LineUsage,
    ResourceUsage,
)
from carrier_usage.providers.china_unicom import parse_allowances
from carrier_usage.redaction import mask_phone


def parse_web_allowances(
    payload: Mapping[str, object], category: AllowanceCategory
) -> tuple[Allowance, ...]:
    """把网页余量资源转换为统一用量项目。"""

    return _dedupe_allowances(
        item for item in parse_allowances(payload) if item.category is category
    )


def parse_web_lines(payload: Mapping[str, object]) -> tuple[LineUsage, ...]:
    """提取主副卡角色和接口提供的成员用量。"""

    roles: dict[str, LineRole] = {}
    items: dict[str, list[Allowance]] = {}
    for raw in _mapping_list(payload.get("viceCardLits")):
        phone = _phone(raw)
        if phone:
            roles[phone] = _line_role(raw)
            items.setdefault(phone, [])

    for detail, raw_type in _all_details(payload):
        category = _category(detail.get("elemType"))
        if category is None:
            continue
        for raw in _mapping_list(detail.get("viceCardlist")):
            phone = _phone(raw)
            if not phone:
                continue
            roles[phone] = _line_role(raw)
            items.setdefault(phone, []).append(
                Allowance(
                    category=category,
                    scope=AllowanceScope.GENERAL,
                    name=str(
                        detail.get("addUpItemName") or detail.get("feePolicyName") or "成员用量"
                    ),
                    unit=_unit(category),
                    total=None,
                    used=_amount(raw.get("use"), category),
                    remaining=None,
                    overage=None,
                    unlimited=False,
                    raw_type=raw_type,
                )
            )

    return tuple(
        LineUsage(
            mask_phone(phone),
            roles.get(phone, LineRole.UNKNOWN),
            _dedupe_allowances(allowances),
        )
        for phone, allowances in items.items()
    )


def parse_web_resources(payload: Mapping[str, object]) -> tuple[ResourceUsage, ...]:
    """解析云盘等非通信资源。"""

    source = _first_resource(payload)
    if not source:
        return ()
    return (
        ResourceUsage(
            name=str(source.get("name") or source.get("resourceName") or "联通云盘"),
            tier=_optional_text(
                source.get("vipLevel") or source.get("memberLevel") or source.get("levelName")
            ),
            used=_capacity(source.get("usedSize") or source.get("used") or source.get("usedSpace")),
            total=_capacity(
                source.get("totalSize") or source.get("total") or source.get("totalSpace")
            ),
            status=_optional_text(source.get("status") or source.get("statusName")),
        ),
    )


def _all_details(
    payload: Mapping[str, object],
) -> Iterable[tuple[Mapping[str, object], str]]:
    for key in ("unshared", "resources"):
        for group in _mapping_list(payload.get(key)):
            raw_type = str(group.get("type") or key)
            for detail in _mapping_list(group.get("details")):
                yield detail, raw_type
    share_data = payload.get("shareData")
    if isinstance(share_data, dict):
        raw_type = str(share_data.get("type") or "shareData")
        for detail in _mapping_list(share_data.get("details")):
            yield detail, raw_type


def _amount(value: object, category: AllowanceCategory) -> int | None:
    number = _decimal(value)
    if number is None:
        return None
    number = max(number, Decimal(0))
    if category is AllowanceCategory.DATA:
        number *= 1024**2
    elif category is AllowanceCategory.VOICE:
        number *= 60
    return int(number)


def _category(value: object) -> AllowanceCategory | None:
    return {
        "1": AllowanceCategory.VOICE,
        "2": AllowanceCategory.SMS,
        "3": AllowanceCategory.DATA,
    }.get(str(value or ""))


def _capacity(value: object) -> int | None:
    if value is None or value == "":
        return None
    text = str(value).strip().upper()
    units = {
        "B": 1,
        "K": 1024,
        "KB": 1024,
        "M": 1024**2,
        "MB": 1024**2,
        "G": 1024**3,
        "GB": 1024**3,
    }
    for unit in sorted(units, key=len, reverse=True):
        if text.endswith(unit):
            number = _decimal(text[: -len(unit)])
            if number is None:
                break
            return int(max(number, Decimal(0)) * units[unit])
    raise UpstreamChangedError(f"中国联通返回了未知容量：{text}")


def _first_resource(payload: Mapping[str, object]) -> Mapping[str, object]:
    for key in ("data", "resource", "resources", "result"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
        items = _mapping_list(value)
        if items:
            return items[0]
    return payload


def _phone(item: Mapping[str, object]) -> str | None:
    for field_name in (
        "serialNumber",
        "userMobile",
        "usernumber",
        "number",
        "mobile",
        "phone",
        "secretNumber",
    ):
        text = str(item.get(field_name) or "")
        if (text.isdigit() and len(text) >= 7) or "*" in text:
            return text
    return None


def _line_role(item: Mapping[str, object]) -> LineRole:
    if str(item.get("currentLoginFlag") or "") == "1":
        return LineRole.PRIMARY
    role = str(
        item.get("role")
        or item.get("cardType")
        or item.get("numberFlag")
        or item.get("viceCardflag")
        or ""
    ).lower()
    if role in {"primary", "main", "主卡"}:
        return LineRole.PRIMARY
    if role in {"secondary", "vice", "副卡"}:
        return LineRole.SECONDARY
    return LineRole.SECONDARY


def _mapping_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dedupe_allowances(items: Iterable[Allowance]) -> tuple[Allowance, ...]:
    result: list[Allowance] = []
    seen: set[tuple[object, ...]] = set()
    for item in items:
        identity = (
            item.category,
            item.scope,
            item.name,
            item.unit,
            item.total,
            item.used,
            item.remaining,
            item.overage,
            item.unlimited,
            item.effective_at,
            item.expires_at,
        )
        if identity in seen:
            continue
        seen.add(identity)
        result.append(item)
    return tuple(result)


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _unit(category: AllowanceCategory) -> AllowanceUnit:
    return {
        AllowanceCategory.DATA: AllowanceUnit.BYTE,
        AllowanceCategory.VOICE: AllowanceUnit.SECOND,
        AllowanceCategory.SMS: AllowanceUnit.COUNT,
    }[category]


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
