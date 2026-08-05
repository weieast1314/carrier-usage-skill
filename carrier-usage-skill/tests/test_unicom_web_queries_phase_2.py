from datetime import date
from decimal import Decimal

from carrier_usage.providers.china_unicom_web_queries import (
    parse_contract_bill,
    parse_invoices,
    parse_payments,
    parse_rebates,
)


def test_parse_payments_masks_identifiers_and_maps_amounts() -> None:
    result = parse_payments(
        {
            "orderList": [
                {
                    "orderNo": "TESTORDER12345678",
                    "orderTime": "2026-08-01T10:20:30",
                    "channelName": "示例渠道",
                    "deliverCarrier": "13800138000",
                    "topayTotalMoney": "28.50",
                    "payType": "1",
                    "realOrderState": "已交费",
                }
            ]
        }
    )
    assert result[0].order_id_masked == "TEST****5678"
    assert result[0].phone_masked == "138****8000"
    assert result[0].amount_cny == Decimal("28.50")


def test_parse_invoices_keeps_only_read_only_metadata() -> None:
    result = parse_invoices(
        {
            "data": {
                "invoiceList": [
                    {
                        "invoiceNo": "INV202608123456",
                        "amount": "39.00",
                        "invoiceDate": "2026-08-02",
                        "invoiceType": "电子普通发票",
                        "status": "已开具",
                    }
                ]
            }
        }
    )
    assert result[0].invoice_no_masked == "INV2****3456"
    assert result[0].amount_cny == Decimal("39.00")


def test_parse_rebates_accepts_json_string_data() -> None:
    result = parse_rebates(
        {"data": '[{"SERIAL_NUMBER":"13800138000","PAY_DATE":"20260801102030","PAY_FEE":"1250"}]'},
        "grant",
    )
    assert result[0].phone_masked == "138****8000"
    assert result[0].amount_cny == Decimal("12.50")


def test_parse_contract_bill_maps_official_fields() -> None:
    result = parse_contract_bill(
        {
            "status": "0000",
            "data": {
                "allfree": "19.90",
                "billinfos": [
                    {
                        "productname": "示例合约",
                        "memberphone": "13800138000",
                        "tradeid": "ORDER202608001",
                        "dealtime": "2026-08-03 09:00:00",
                        "fee": "19.90",
                        "surplusnum": "5",
                        "tradetype": "0",
                    }
                ],
            },
        },
        date(2026, 8, 1),
    )
    assert result.total_cny == Decimal("19.90")
    assert result.items[0].phone_masked == "138****8000"
    assert result.items[0].order_id_masked == "ORDE****8001"
