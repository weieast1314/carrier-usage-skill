import json
from decimal import Decimal
from pathlib import Path

from carrier_usage.models import AllowanceCategory, LineRole
from carrier_usage.providers.china_unicom_web_detail import (
    parse_web_allowances,
    parse_web_lines,
    parse_web_resources,
)

FIXTURES = Path(__file__).parent / "fixtures" / "unicom"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_web_detail_normalizes_allowances_and_members() -> None:
    payload = load_fixture("web_detail.json")
    data = parse_web_allowances(payload, AllowanceCategory.DATA)
    voice = parse_web_allowances(payload, AllowanceCategory.VOICE)
    lines = parse_web_lines(payload)

    assert [item.total for item in data] == [90 * 1024**3, 10 * 1024**3]
    assert sum(item.used or 0 for item in data) == 6 * 1024**3
    assert [item.total for item in voice] == [200 * 60, 800 * 60]
    assert lines[0].phone_masked == "138****8000"
    assert lines[0].role is LineRole.PRIMARY
    assert lines[1].phone_masked == "138****8001"
    assert lines[1].role is LineRole.SECONDARY
    member_voice = next(
        item for item in lines[1].allowances if item.category is AllowanceCategory.VOICE
    )
    assert member_voice.used == 1 * 60


def test_parse_web_disk_normalizes_capacity() -> None:
    resources = parse_web_resources(load_fixture("web_disk.json"))

    assert resources[0].name == "联通云盘"
    assert resources[0].tier == "普通会员"
    assert resources[0].used == int(Decimal("78.5") * 1024**2)
    assert resources[0].total == 60 * 1024**3
    assert resources[0].status is None


def test_web_parsers_deduplicate_shared_groups() -> None:
    payload = load_fixture("web_detail.json")
    unshared = payload["unshared"]
    resources = payload["resources"]
    assert isinstance(unshared, list)
    assert isinstance(resources, list)
    duplicate = dict(unshared[0])
    duplicate["type"] = "SharedData"
    resources.append(duplicate)

    data = parse_web_allowances(payload, AllowanceCategory.DATA)
    lines = parse_web_lines(payload)

    assert len(data) == 2
    primary = next(line for line in lines if line.role is LineRole.PRIMARY)
    assert len(primary.allowances) == 2
