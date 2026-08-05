from pathlib import Path

_SKILL_MD = Path(__file__).parents[1] / "SKILL.md"
_README_MD = Path(__file__).parents[2] / "README.md"


def test_skill_documents_multi_account_selection() -> None:
    text = _SKILL_MD.read_text(encoding="utf-8")
    for phrase in ("--account", "全局默认", "运营商默认", "脱敏选项", "当前对话"):
        assert phrase in text


def test_readme_documents_account_management() -> None:
    text = _README_MD.read_text(encoding="utf-8")
    for phrase in ("accounts list", "accounts rename", "set-default", "旧版"):
        assert phrase in text


def test_skill_documents_first_web_query_commands() -> None:
    text = _SKILL_MD.read_text(encoding="utf-8")
    for phrase in ("balance", "allowances", "bills", "剩余话费", "我的账单", "余量查询"):
        assert phrase in text


def test_readme_documents_basic_read_only_queries() -> None:
    text = _README_MD.read_text(encoding="utf-8")
    for phrase in ("剩余话费", "我的账单", "余量查询", "只读"):
        assert phrase in text


def test_skill_documents_phase_two_and_three_queries() -> None:
    text = _SKILL_MD.read_text(encoding="utf-8")
    for phrase in (
        "payments",
        "invoices",
        "rebates",
        "contract-bills",
        "usage-details",
        "短信二次认证",
    ):
        assert phrase in text


def test_readme_documents_version_040_and_all_read_only_queries() -> None:
    text = _README_MD.read_text(encoding="utf-8")
    for phrase in ("0.4.0", "交费记录", "电子发票", "返费与赠款", "金融合约账单", "详单查询"):
        assert phrase in text
