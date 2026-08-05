import json
from datetime import UTC, datetime
from decimal import Decimal

from carrier_usage.web_models import BalanceInfo, WebQueryEnvelope
from carrier_usage.web_render import render_web_json, render_web_summary


def envelope() -> WebQueryEnvelope:
    return WebQueryEnvelope(
        "1.0",
        "china_unicom",
        "unicom-work",
        "工作联通",
        "balance",
        datetime(2026, 8, 5, tzinfo=UTC),
        BalanceInfo(Decimal("142.35"), Decimal("157.35"), Decimal(20), Decimal(35), None),
    )


def test_balance_json_uses_stable_envelope() -> None:
    payload = json.loads(render_web_json(envelope()))
    assert payload["query_type"] == "balance"
    assert payload["data"]["remaining_balance_cny"] == "142.35"
    assert "session_path" not in json.dumps(payload)


def test_balance_summary_is_chinese() -> None:
    summary = render_web_summary(envelope())
    assert "工作联通" in summary
    assert "剩余话费：142.35 元" in summary


def test_payment_summary_keeps_masked_identifiers() -> None:
    from carrier_usage.web_models import PaymentRecord

    item = PaymentRecord(
        "TEST****5678",
        datetime(2026, 8, 1, tzinfo=UTC),
        "示例渠道",
        "138****8000",
        Decimal("28.50"),
        "在线支付",
        Decimal("28.50"),
        "已交费",
    )
    query = WebQueryEnvelope(
        "1.0",
        "china_unicom",
        "unicom-work",
        "工作联通",
        "payments",
        datetime(2026, 8, 5, tzinfo=UTC),
        (item,),
    )
    summary = render_web_summary(query)
    assert "交费记录" in summary
    assert "28.50 元" in summary
    assert "13800138000" not in summary
