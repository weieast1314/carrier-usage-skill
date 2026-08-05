"""解析中国联通网页余额和账单响应。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from carrier_usage.errors import UpstreamChangedError
from carrier_usage.redaction import mask_phone
from carrier_usage.web_models import (
    BalanceInfo,
    BillLine,
    ContractBill,
    ContractBillItem,
    InvoiceRecord,
    MonthlyBill,
    PaymentRecord,
    RebateRecord,
)


def parse_balance(payload: Mapping[str, object]) -> BalanceInfo:
    remaining = _decimal(payload.get("curntbalancecust"))
    if remaining is None:
        raise UpstreamChangedError("中国联通余额响应缺少剩余话费")
    return BalanceInfo(
        remaining,
        _decimal(payload.get("newCarryOverArrears")),
        _decimal(payload.get("newDepositForTheMonth")),
        _decimal(payload.get("realfeecustnew")),
        _datetime(payload.get("queryTime")),
    )


def parse_bill_months(payload: Mapping[str, object]) -> tuple[date, ...]:
    data = _mapping(payload.get("data"))
    raw = data.get("months")
    if not isinstance(raw, list):
        return ()
    result: list[date] = []
    for item in raw:
        row = _mapping(item)
        try:
            result.append(
                date(int(str(row.get("historyYear"))), int(str(row.get("historyMonth"))), 1)
            )
        except (TypeError, ValueError):
            continue
    return tuple(result)


def parse_monthly_bill(payload: Mapping[str, object], month: date) -> MonthlyBill:
    data = _mapping(payload.get("data"))
    consumed = _decimal(data.get("totalspayfee"))
    if consumed is None:
        raise UpstreamChangedError("中国联通账单响应缺少实际应付金额")
    payable = _decimal(data.get("allpayfee"))
    adjustment = _mapping(data.get("adjustment"))
    raw_lines = data.get("acctBillList")
    lines = (
        tuple(_bill_line(item) for item in raw_lines if isinstance(item, dict))
        if isinstance(raw_lines, list)
        else ()
    )
    return MonthlyBill(
        month=month,
        consumed_cny=consumed,
        overdue_cny=_decimal(data.get("allnopayfee")),
        original_cny=_decimal(data.get("totalprice")),
        discount_cny=_decimal(data.get("totalDiscount")),
        rebate_cny=_decimal(adjustment.get("rebateDeduction")),
        payable_cny=payable if payable is not None else consumed,
        lines=lines,
    )


def parse_payments(payload: Mapping[str, object]) -> tuple[PaymentRecord, ...]:
    raw = payload.get("orderList")
    if not isinstance(raw, list):
        raw = _mapping(payload.get("data")).get("orderList")
    if not isinstance(raw, list):
        return ()
    return tuple(
        PaymentRecord(
            order_id_masked=_mask_identifier(_text(row.get("originalOrder") or row.get("orderNo"))),
            paid_at=_datetime(row.get("orderTime")),
            channel=_text(row.get("channelName") or row.get("payRemark") or row.get("payMent")),
            phone_masked=_masked_phone(row.get("deliverCarrier")),
            amount_cny=_decimal(row.get("topayTotalMoney")),
            payment_method=_text(row.get("paymentMethod") or row.get("payType")),
            paid_cny=_decimal(row.get("incomeTotalMoney")),
            status=_text(row.get("status") or row.get("realOrderState") or row.get("orderState")),
        )
        for item in raw[:100]
        if (row := _mapping(item))
    )


def parse_invoices(payload: Mapping[str, object]) -> tuple[InvoiceRecord, ...]:
    data = _mapping(payload.get("data"))
    raw = next(
        (
            value
            for value in (
                data.get("invoiceList"),
                data.get("list"),
                payload.get("invoiceList"),
                payload.get("list"),
            )
            if isinstance(value, list)
        ),
        [],
    )
    return tuple(
        InvoiceRecord(
            invoice_no_masked=_mask_identifier(
                _text(row.get("invoiceNo") or row.get("einvoiceNo") or row.get("invoiceCode"))
            ),
            amount_cny=_decimal(row.get("amount") or row.get("invoiceAmount") or row.get("fee")),
            issued_at=_date(row.get("invoiceDate") or row.get("issueDate") or row.get("date")),
            invoice_type=_text(row.get("invoiceType") or row.get("type")),
            status=_text(row.get("status") or row.get("state")),
        )
        for item in raw[:100]
        if (row := _mapping(item))
    )


def parse_rebates(payload: Mapping[str, object], kind: str) -> tuple[RebateRecord, ...]:
    raw: object = payload.get("data")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as error:
            raise UpstreamChangedError("中国联通返费与赠款响应结构已变化") from error
    if not isinstance(raw, list):
        return ()
    result: list[RebateRecord] = []
    for item in raw[:100]:
        row = _mapping(item)
        cents = _decimal(row.get("PAY_FEE"))
        amount = (
            cents / 100
            if cents is not None and kind == "grant"
            else _decimal(
                row.get("sumreturnmoney")
                or row.get("returnfreemoney")
                or row.get("amount")
                or row.get("fee")
            )
        )
        result.append(
            RebateRecord(
                kind=kind,
                amount_cny=amount,
                occurred_at=_compact_datetime(row.get("PAY_DATE") or row.get("returntime")),
                phone_masked=_masked_phone(
                    row.get("SERIAL_NUMBER") or row.get("serialnumber") or row.get("memberphone")
                ),
                name=_text(row.get("actname") or row.get("productname") or row.get("name")),
                starts_at=_date(row.get("startdate")),
                ends_at=_date(row.get("enddate")),
            )
        )
    return tuple(result)


def parse_contract_bill(payload: Mapping[str, object], month: date) -> ContractBill:
    data = _mapping(payload.get("data"))
    raw = data.get("billinfos")
    items = (
        tuple(
            ContractBillItem(
                name=_text(row.get("productname")),
                phone_masked=_masked_phone(row.get("memberphone")),
                order_id_masked=_mask_identifier(_text(row.get("tradeid"))),
                dealt_at=_datetime(row.get("dealtime")),
                amount_cny=_decimal(row.get("fee")),
                remaining_months=_integer(row.get("surplusnum")),
                transaction_type="扣款" if str(row.get("tradetype")) == "0" else "退款",
            )
            for item in raw[:100]
            if (row := _mapping(item))
        )
        if isinstance(raw, list)
        else ()
    )
    return ContractBill(month, _decimal(data.get("allfree")), items)


def _bill_line(value: Mapping[str, object]) -> BillLine:
    bill = _mapping(value.get("bill")) or value
    children_raw = value.get("subItems")
    children = (
        tuple(_bill_line(item) for item in children_raw if isinstance(item, dict))
        if isinstance(children_raw, list)
        else ()
    )
    return BillLine(
        name=str(bill.get("integrateitem") or bill.get("name") or "未命名费用项"),
        original_cny=_decimal(bill.get("originalFee") or bill.get("originalprice")),
        discount_cny=_decimal(bill.get("discountFee") or bill.get("discount")),
        rebate_cny=_decimal(bill.get("rebateFee") or bill.get("rebate")),
        payable_cny=_decimal(bill.get("payableFee") or bill.get("spayfee")),
        children=children,
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        china_standard_time = timezone(timedelta(hours=8))
        normalized = value.replace("T", " ")[:19]
        return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=china_standard_time
        )
    except ValueError:
        return None


def _compact_datetime(value: object) -> datetime | None:
    if isinstance(value, str) and re.fullmatch(r"\d{14}", value):
        china_standard_time = timezone(timedelta(hours=8))
        return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=china_standard_time)
    return _datetime(value)


def _date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    normalized = value.replace("年", "-").replace("月", "-").replace("日", "")[:10]
    if re.fullmatch(r"\d{8}", normalized):
        normalized = f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}"
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _text(value: object) -> str | None:
    text = str(value).strip() if value not in (None, "") else ""
    return text or None


def _masked_phone(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    first = text.split(",", maxsplit=1)[0]
    return mask_phone(first) if first.isdigit() and len(first) >= 7 else _mask_identifier(first)


def _mask_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


def _integer(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
