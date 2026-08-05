"""联通网页只读查询的稳定业务模型。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from carrier_usage.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class BalanceInfo:
    remaining_cny: Decimal | None
    carried_cny: Decimal | None
    deposited_cny: Decimal | None
    consumed_cny: Decimal | None
    source_queried_at: datetime | None

    def __post_init__(self) -> None:
        if self.consumed_cny is not None and self.consumed_cny < 0:
            raise ValueError("consumed_cny must be non-negative")


@dataclass(frozen=True, slots=True)
class BillLine:
    name: str
    original_cny: Decimal | None = None
    discount_cny: Decimal | None = None
    rebate_cny: Decimal | None = None
    payable_cny: Decimal | None = None
    children: tuple[BillLine, ...] = ()


@dataclass(frozen=True, slots=True)
class MonthlyBill:
    month: date
    consumed_cny: Decimal | None
    overdue_cny: Decimal | None
    original_cny: Decimal | None
    discount_cny: Decimal | None
    rebate_cny: Decimal | None
    payable_cny: Decimal | None
    lines: tuple[BillLine, ...] = ()
    status: str = "available"


@dataclass(frozen=True, slots=True)
class PaymentRecord:
    order_id_masked: str | None
    paid_at: datetime | None
    channel: str | None
    phone_masked: str | None
    amount_cny: Decimal | None
    payment_method: str | None
    paid_cny: Decimal | None
    status: str | None


@dataclass(frozen=True, slots=True)
class InvoiceRecord:
    invoice_no_masked: str | None
    amount_cny: Decimal | None
    issued_at: date | None
    invoice_type: str | None
    status: str | None


@dataclass(frozen=True, slots=True)
class RebateRecord:
    kind: str
    amount_cny: Decimal | None
    occurred_at: datetime | None
    phone_masked: str | None
    name: str | None = None
    starts_at: date | None = None
    ends_at: date | None = None


@dataclass(frozen=True, slots=True)
class ContractBillItem:
    name: str | None
    phone_masked: str | None
    order_id_masked: str | None
    dealt_at: datetime | None
    amount_cny: Decimal | None
    remaining_months: int | None
    transaction_type: str | None


@dataclass(frozen=True, slots=True)
class ContractBill:
    month: date
    total_cny: Decimal | None
    items: tuple[ContractBillItem, ...]
    status: str = "available"


@dataclass(frozen=True, slots=True)
class UsageDetailResult:
    category: str
    month: date
    status: str
    official_url: str


@dataclass(frozen=True, slots=True)
class WebQueryEnvelope:
    schema_version: str
    provider: str
    account_id: str
    account_alias: str
    query_type: str
    queried_at: datetime
    data: object
    warnings: tuple[str, ...] = ()


def parse_month(value: str) -> date:
    if re.fullmatch(r"\d{4}-\d{2}", value) is None:
        raise ConfigurationError("月份必须使用 YYYY-MM 格式")
    try:
        year, month = (int(part) for part in value.split("-"))
        return date(year, month, 1)
    except ValueError as error:
        raise ConfigurationError("月份必须使用 YYYY-MM 格式") from error


def parse_month_range(start: str, end: str) -> tuple[date, date]:
    start_month, end_month = parse_month(start), parse_month(end)
    if start_month > end_month:
        raise ConfigurationError("起始月份不得晚于结束月份")
    month_count = (end_month.year - start_month.year) * 12 + end_month.month - start_month.month + 1
    if month_count > 12:
        raise ConfigurationError("一次最多查询 12 个月")
    return start_month, end_month
