"""稳定 JSON 和中文摘要输出。"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from carrier_usage.models import (
    Allowance,
    AllowanceCategory,
    CarrierSnapshot,
    LineRole,
    ResourceUsage,
)


def snapshot_to_dict(snapshot: CarrierSnapshot) -> dict[str, object]:
    return {
        "schema_version": snapshot.schema_version,
        "provider": snapshot.provider,
        "account_id": snapshot.account_id,
        "account_alias": snapshot.account_alias,
        "account": {
            "phone_masked": snapshot.account.phone_masked,
            "balance_cny": _decimal_text(snapshot.account.balance_cny),
            "current_charges_cny": _decimal_text(snapshot.account.current_charges_cny),
            "amount_due_cny": _decimal_text(snapshot.account.amount_due_cny),
            "loyalty_points": _integer_text(snapshot.account.loyalty_points),
        },
        "plan": {
            "status": snapshot.plan.status.value,
            "name": snapshot.plan.name,
            "monthly_fee_cny": _decimal_text(snapshot.plan.monthly_fee_cny),
            "effective_at": _datetime_text(snapshot.plan.effective_at),
            "expires_at": _datetime_text(snapshot.plan.expires_at),
        },
        "allowances": [allowance_to_dict(item) for item in snapshot.allowances],
        "subscriptions": {
            "status": snapshot.subscriptions.status.value,
            "items": [
                {
                    "name": item.name,
                    "fee_cny": _decimal_text(item.fee_cny),
                    "effective_at": _datetime_text(item.effective_at),
                    "expires_at": _datetime_text(item.expires_at),
                }
                for item in snapshot.subscriptions.items
            ],
        },
        "lines": [
            {
                "phone_masked": line.phone_masked,
                "role": line.role.value,
                "allowances": [allowance_to_dict(item) for item in line.allowances],
            }
            for line in snapshot.lines
        ],
        "resources": [
            {
                "name": item.name,
                "tier": item.tier,
                "used": _integer_text(item.used),
                "total": _integer_text(item.total),
                "status": item.status,
            }
            for item in snapshot.resources
        ],
        "queried_at": snapshot.queried_at.isoformat(),
        "warnings": list(snapshot.warnings),
    }


def render_json(snapshot: CarrierSnapshot) -> str:
    return json.dumps(snapshot_to_dict(snapshot), ensure_ascii=False, indent=2)


def render_summary(snapshot: CarrierSnapshot) -> str:
    account = snapshot.account
    phone = account.phone_masked or "未提供"
    identity = f"{snapshot.account_alias}（{phone}）" if snapshot.account_alias else phone
    lines = [f"运营商账户：{identity}"]
    if account.balance_cny is not None:
        lines.append(f"账户余额：{account.balance_cny:.2f} 元")
    if account.current_charges_cny is not None:
        lines.append(f"本月实时话费：{account.current_charges_cny:.2f} 元")
    if account.amount_due_cny is not None:
        lines.append(f"当前欠费：{account.amount_due_cny:.2f} 元")
    if account.loyalty_points is not None:
        lines.append(f"可用积分：{account.loyalty_points}")
    if snapshot.plan.name:
        fee = (
            f"（{snapshot.plan.monthly_fee_cny:.2f} 元/月）"
            if snapshot.plan.monthly_fee_cny is not None
            else ""
        )
        lines.append(f"当前套餐：{snapshot.plan.name}{fee}")
    for allowance in snapshot.allowances:
        lines.append(render_allowance_summary(allowance))
    for line in snapshot.lines:
        title = f"{_line_role_text(line.role)} {line.phone_masked}"
        if not line.allowances:
            lines.append(title)
            continue
        lines.append(f"{title}：")
        lines.extend(f"  {render_allowance_summary(item)}" for item in line.allowances)
    lines.extend(_resource_summary(item) for item in snapshot.resources)
    lines.extend(f"提示：{warning}" for warning in snapshot.warnings)
    return "\n".join(lines)


def allowance_to_dict(item: Allowance) -> dict[str, Any]:
    return {
        "category": item.category.value,
        "scope": item.scope.value,
        "name": item.name,
        "unit": item.unit.value,
        "total": _integer_text(item.total),
        "used": _integer_text(item.used),
        "remaining": _integer_text(item.remaining),
        "overage": _integer_text(item.overage),
        "unlimited": item.unlimited,
        "effective_at": _datetime_text(item.effective_at),
        "expires_at": _datetime_text(item.expires_at),
        "raw_type": item.raw_type,
    }


def render_allowance_summary(item: Allowance) -> str:
    name = item.name or "未命名余量"
    if item.unlimited:
        return f"{name}：无限量权益"
    if item.category is AllowanceCategory.DATA:
        if item.remaining is None and item.used is not None:
            return f"{name}：已用 {_gib(item.used):.2f} GB"
        remaining = _gib(item.remaining)
        if item.used is None:
            return f"{name}：剩余 {remaining:.2f} GB"
        used = _gib(item.used)
        return f"{name}：已用 {used:.2f} GB，剩余 {remaining:.2f} GB"
    if item.category is AllowanceCategory.VOICE:
        if item.remaining is None and item.used is not None:
            return f"{name}：已用 {item.used / 60:.0f} 分钟"
        remaining_minutes = (item.remaining or 0) / 60
        if item.used is None:
            return f"{name}：剩余 {remaining_minutes:.0f} 分钟"
        used_minutes = item.used / 60
        return f"{name}：已用 {used_minutes:.0f} 分钟，剩余 {remaining_minutes:.0f} 分钟"
    if item.remaining is None and item.used is not None:
        return f"{name}：已用 {item.used} 条"
    if item.used is None:
        return f"{name}：剩余 {item.remaining or 0} 条"
    return f"{name}：已用 {item.used or 0} 条，剩余 {item.remaining or 0} 条"


# 保留旧的内部名称，避免既有扩展和测试因公开复用渲染能力而中断。
_allowance_dict = allowance_to_dict
_allowance_summary = render_allowance_summary


def _gib(value: int | None) -> float:
    return (value or 0) / 1024**3


def _line_role_text(role: LineRole) -> str:
    return {
        LineRole.PRIMARY: "主卡",
        LineRole.SECONDARY: "副卡",
        LineRole.MEMBER: "成员",
        LineRole.UNKNOWN: "未知成员",
    }[role]


def _resource_summary(item: ResourceUsage) -> str:
    tier = f"：{item.tier}" if item.tier else ""
    amounts: list[str] = []
    if item.used is not None:
        amounts.append(f"已用 {_capacity_text(item.used)}")
    if item.total is not None:
        amounts.append(f"总空间 {_capacity_text(item.total)}")
    suffix = f"，{'，'.join(amounts)}" if amounts else ""
    return f"{item.name}{tier}{suffix}"


def _capacity_text(value: int) -> str:
    if value >= 1024**3:
        return f"{value / 1024**3:.2f} GB"
    return f"{value / 1024**2:.2f} MB"


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _integer_text(value: int | None) -> str | None:
    return str(value) if value is not None else None


def _datetime_text(value: object) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None
