"""联通网页业务查询的稳定 JSON 和中文摘要。"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast

from carrier_usage.models import Allowance
from carrier_usage.render import allowance_to_dict, render_allowance_summary
from carrier_usage.web_models import (
    BalanceInfo,
    ContractBill,
    InvoiceRecord,
    MonthlyBill,
    PaymentRecord,
    RebateRecord,
    WebQueryEnvelope,
)


def render_web_json(envelope: WebQueryEnvelope) -> str:
    payload = {
        "schema_version": envelope.schema_version,
        "provider": envelope.provider,
        "account_id": envelope.account_id,
        "account_alias": envelope.account_alias,
        "query_type": envelope.query_type,
        "queried_at": envelope.queried_at.isoformat(),
        "data": _json_value(envelope.data),
        "warnings": list(envelope.warnings),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_web_summary(envelope: WebQueryEnvelope) -> str:
    title = f"账户：{envelope.account_alias}"
    if isinstance(envelope.data, BalanceInfo):
        balance = envelope.data
        return "\n".join(
            [
                title,
                f"剩余话费：{_money(balance.remaining_cny)}",
                f"上月结转：{_money(balance.carried_cny)}",
                f"本月存入：{_money(balance.deposited_cny)}",
                f"本月已消费：{_money(balance.consumed_cny)}",
            ]
        )
    if isinstance(envelope.data, MonthlyBill):
        bill = envelope.data
        lines = [
            title,
            f"账单月份：{bill.month:%Y-%m}",
            f"实际应付：{_money(bill.payable_cny)}",
            f"待交费：{_money(bill.overdue_cny)}",
        ]
        lines.extend(f"费用项：{line.name}，{_money(line.payable_cny)}" for line in bill.lines)
        return "\n".join(lines)
    if (
        envelope.query_type == "allowances"
        and isinstance(envelope.data, tuple)
        and all(isinstance(item, Allowance) for item in envelope.data)
    ):
        return "\n".join([title, *(render_allowance_summary(item) for item in envelope.data)])
    if (
        envelope.query_type == "payments"
        and isinstance(envelope.data, tuple)
        and all(isinstance(item, PaymentRecord) for item in envelope.data)
    ):
        return "\n".join(
            [
                title,
                "交费记录：",
                *(
                    f"{_datetime_summary(item.paid_at)}，{item.phone_masked or '号码未提供'}，"
                    f"{_money(item.amount_cny)}，{item.status or '状态未提供'}"
                    for item in envelope.data
                ),
            ]
        )
    if (
        envelope.query_type == "invoices"
        and isinstance(envelope.data, tuple)
        and all(isinstance(item, InvoiceRecord) for item in envelope.data)
    ):
        return "\n".join(
            [
                title,
                "电子发票：",
                *(
                    f"{item.invoice_no_masked or '编号未提供'}，{_money(item.amount_cny)}，{item.status or '状态未提供'}"
                    for item in envelope.data
                ),
            ]
        )
    if (
        envelope.query_type == "rebates"
        and isinstance(envelope.data, tuple)
        and all(isinstance(item, RebateRecord) for item in envelope.data)
    ):
        return "\n".join(
            [
                title,
                "返费与赠款：",
                *(f"{item.name or item.kind}，{_money(item.amount_cny)}" for item in envelope.data),
            ]
        )
    if isinstance(envelope.data, ContractBill):
        contract_bill = envelope.data
        return "\n".join(
            [
                title,
                f"金融合约账单月份：{contract_bill.month:%Y-%m}",
                f"消费合计：{_money(contract_bill.total_cny)}",
                *(
                    f"{item.name or '未命名合约'}，{_money(item.amount_cny)}"
                    for item in contract_bill.items
                ),
            ]
        )
    return title + "\n查询完成"


def _money(value: Decimal | None) -> str:
    return f"{value:.2f} 元" if value is not None else "未提供"


def _datetime_summary(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value is not None else "时间未提供"


def _json_value(value: Any) -> Any:
    if isinstance(value, BalanceInfo):
        return {
            "remaining_balance_cny": _json_value(value.remaining_cny),
            "carried_balance_cny": _json_value(value.carried_cny),
            "deposited_this_month_cny": _json_value(value.deposited_cny),
            "consumed_this_month_cny": _json_value(value.consumed_cny),
            "source_queried_at": _json_value(value.source_queried_at),
        }
    if isinstance(value, Allowance):
        return allowance_to_dict(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _json_value(asdict(cast(Any, value)))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value
