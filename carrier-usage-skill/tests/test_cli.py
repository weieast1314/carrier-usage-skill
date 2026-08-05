import subprocess
import sys
from pathlib import Path

import pytest
from carrier_usage.account_registry import AccountRegistry, default_registry_path
from carrier_usage.cli import _parser, main


def test_cli_maps_configuration_error_to_exit_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    exit_code = main(["doctor", "--provider", "china_unicom"])

    assert exit_code == 2
    assert "请先运行 login 命令扫码登录" in capsys.readouterr().err


def test_help_lists_only_supported_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--help"])

    help_text = capsys.readouterr().out
    assert "query" in help_text
    assert "capabilities" in help_text
    assert "doctor" in help_text
    assert "login" in help_text


def test_login_saves_to_requested_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_path = tmp_path / "unicom-session.json"
    captured: list[Path] = []

    monkeypatch.setattr(
        "carrier_usage.cli.login_unicom_interactively",
        lambda path: captured.append(path),
    )

    exit_code = main(
        [
            "login",
            "--provider",
            "china_unicom",
            "--session",
            str(session_path),
        ]
    )

    assert exit_code == 0
    assert captured == [session_path]
    assert "登录会话已安全保存" in capsys.readouterr().out


def test_repository_script_can_run_without_package_name_shadowing() -> None:
    project_root = Path(__file__).parents[1]

    result = subprocess.run(
        [sys.executable, "scripts/carrier_usage.py", "--help"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "安全查询运营商余额" in result.stdout


def test_query_accepts_members_scope() -> None:
    args = _parser().parse_args(["query", "--provider", "china_unicom", "--scope", "members"])

    assert args.scope == "members"


def test_query_defaults_to_overview_scope() -> None:
    args = _parser().parse_args(["query", "--provider", "china_unicom"])

    assert args.scope == "overview"


def test_query_rejects_unknown_scope() -> None:
    with pytest.raises(SystemExit, match="2"):
        _parser().parse_args(["query", "--scope", "billing-history"])


def test_login_registers_alias_and_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr("carrier_usage.cli.login_unicom_interactively", lambda path: None)

    exit_code = main(["login", "--provider", "china_unicom", "--alias", "工作联通", "--default"])

    registry = AccountRegistry(default_registry_path())
    selected = registry.resolve(account="工作联通")
    assert exit_code == 0
    assert registry.resolve() == selected
    assert registry.resolve(provider="china_unicom") == selected
    assert "工作联通" in capsys.readouterr().out


def test_accounts_commands_manage_alias_and_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr("carrier_usage.cli.login_unicom_interactively", lambda path: None)
    assert main(["login", "--alias", "工作联通"]) == 0

    assert main(["accounts", "rename", "工作联通", "办公联通"]) == 0
    assert main(["accounts", "set-default", "办公联通"]) == 0
    assert main(["accounts", "list"]) == 0

    output = capsys.readouterr().out
    assert "办公联通" in output
    assert "全局默认" in output


def test_query_parser_accepts_account_alias() -> None:
    args = _parser().parse_args(["query", "--account", "工作联通"])
    assert args.account == "工作联通"


def test_balance_command_accepts_account_and_json() -> None:
    args = _parser().parse_args(["balance", "--account", "我的联通", "--format", "json"])
    assert args.command == "balance"
    assert args.account == "我的联通"


def test_bills_accepts_month() -> None:
    args = _parser().parse_args(["bills", "--account", "我的联通", "--month", "2026-08"])
    assert args.month == "2026-08"


def test_phase_two_and_three_commands_accept_stable_parameters() -> None:
    payments = _parser().parse_args(
        ["payments", "--account", "我的联通", "--from", "2026-01", "--to", "2026-08"]
    )
    invoices = _parser().parse_args(["invoices", "--month", "2026-08"])
    details = _parser().parse_args(["usage-details", "--category", "data", "--month", "2026-08"])
    contract = _parser().parse_args(["contract-bills", "--month", "2026-08"])
    rebates = _parser().parse_args(["rebates"])

    assert (payments.from_month, payments.to_month) == ("2026-01", "2026-08")
    assert invoices.month == "2026-08"
    assert details.category == "data"
    assert contract.command == "contract-bills"
    assert rebates.command == "rebates"
