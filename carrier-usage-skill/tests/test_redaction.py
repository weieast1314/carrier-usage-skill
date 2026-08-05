from carrier_usage.redaction import mask_phone, redact_mapping, redact_text


def test_masks_phone_and_explicit_secret() -> None:
    assert mask_phone("13800138000") == "138****8000"

    text = redact_text("phone=13800138000 openid=abc-secret", ["abc-secret"])

    assert text == "phone=138****8000 openid=[REDACTED]"


def test_redacts_sensitive_mapping_keys_recursively() -> None:
    value = {
        "headers": {"Authorization": "Bearer x", "Cookie": "ticket=y"},
        "body": {"openId": "abc", "safe": "visible"},
    }

    redacted = redact_mapping(value)

    assert redacted == {
        "headers": {"Authorization": "[REDACTED]", "Cookie": "[REDACTED]"},
        "body": {"openId": "[REDACTED]", "safe": "visible"},
    }


def test_redacts_sensitive_values_inside_lists() -> None:
    redacted = redact_mapping({"events": [{"token": "secret"}, "13800138000"]})

    assert redacted == {"events": [{"token": "[REDACTED]"}, "138****8000"]}
