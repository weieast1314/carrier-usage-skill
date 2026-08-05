"""运营商查询命令行入口。"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
import traceback
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import httpx

from carrier_usage.account_registry import (
    AccountRecord,
    AccountRegistry,
    account_session_path,
    migrate_legacy_session,
)
from carrier_usage.auth.china_unicom_web import (
    login_interactively as login_unicom_interactively,
)
from carrier_usage.config import load_config
from carrier_usage.errors import CarrierUsageError, ConfigurationError, UnsupportedCapabilityError
from carrier_usage.models import QueryScope
from carrier_usage.providers import ChinaUnicomWebProvider
from carrier_usage.providers.base import create_provider
from carrier_usage.providers.china_unicom_web_client import ChinaUnicomWebClient
from carrier_usage.redaction import redact_text
from carrier_usage.render import render_json, render_summary
from carrier_usage.service import RefreshGuard, query_snapshot
from carrier_usage.web_models import WebQueryEnvelope, parse_month, parse_month_range
from carrier_usage.web_render import render_web_json, render_web_summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "capabilities":
            return _print_capabilities(args.provider)
        if args.command == "login":
            return _run_login(args)
        if args.command == "accounts":
            return _run_accounts(args)

        env = dict(os.environ)
        registry = AccountRegistry()
        migrate_legacy_session(registry)
        records = registry.list_accounts()
        account = (
            registry.resolve(account=args.account, provider=args.provider) if records else None
        )
        provider_id = account.provider if account else (args.provider or "china_unicom")
        env["CARRIER_USAGE_PROVIDER"] = provider_id
        config_path = Path(args.config) if args.config else None
        config = load_config(env, config_path, account=account)
        return asyncio.run(_run_authenticated(args, config, account))
    except CarrierUsageError as error:
        print(redact_text(str(error)), file=sys.stderr)
        return error.exit_code
    except Exception:  # noqa: BLE001 - CLI 边界必须隐藏未预期异常中的敏感数据
        if os.environ.get("CARRIER_USAGE_DEBUG") == "1":
            print(redact_text(traceback.format_exc()), file=sys.stderr)
        else:
            print("未预期的内部错误", file=sys.stderr)
        return 1


def _run_login(args: argparse.Namespace) -> int:
    provider_id = args.provider
    if provider_id != ChinaUnicomWebProvider.provider_id:
        raise UnsupportedCapabilityError(f"未知 Provider：{provider_id}")
    if args.session and not args.alias:
        session_path = Path(args.session).expanduser()
        login_unicom_interactively(session_path)
        print(f"中国联通登录会话已安全保存：{session_path}")
        return 0
    alias = (
        args.alias or input("请为该账户设置中文别名 [我的联通]：").strip() or "我的联通"
    ).strip()
    registry = AccountRegistry()
    account_id = f"china-unicom-{secrets.token_hex(4)}"
    session_path = (
        Path(args.session).expanduser() if args.session else account_session_path(account_id)
    )
    login_unicom_interactively(session_path)
    account = AccountRecord(account_id, alias, provider_id, None, session_path)
    registry.add(account)
    provider_accounts = [item for item in registry.list_accounts() if item.provider == provider_id]
    if len(provider_accounts) == 1 or args.provider_default:
        registry.set_provider_default(account.id)
    if args.default or (len(registry.list_accounts()) == 1 and args.default is not False):
        registry.set_global_default(account.id)
    print(f"账户“{alias}”已绑定，中国联通登录会话已安全保存：{session_path}")
    return 0


def _run_accounts(args: argparse.Namespace) -> int:
    registry = AccountRegistry()
    action = args.accounts_command
    if action == "list":
        state = registry.load()
        for item in state.accounts:
            flags: list[str] = []
            if state.global_default == item.id:
                flags.append("全局默认")
            if (state.provider_defaults or {}).get(item.provider) == item.id:
                flags.append("运营商默认")
            suffix = f" [{'，'.join(flags)}]" if flags else ""
            print(
                f"{item.alias}（{item.masked_phone or '号码待首次查询补充'}）[{item.provider}] {item.id}{suffix}"
            )
        return 0
    if action == "rename":
        item = registry.rename(args.account, args.alias)
    elif action == "set-default":
        item = registry.set_global_default(args.account)
    elif action == "set-provider-default":
        item = registry.set_provider_default(args.account)
    else:
        item = registry.remove(args.account)
        if args.delete_session:
            expected_parent = account_session_path(item.id).parent.resolve()
            resolved = item.session_path.expanduser().resolve()
            if resolved.parent != expected_parent:
                raise ConfigurationError("拒绝删除账户数据目录以外的会话文件")
            resolved.unlink(missing_ok=True)
    print(f"账户“{item.alias}”已更新")
    return 0


async def _run_authenticated(
    args: argparse.Namespace, config: object, account: AccountRecord | None = None
) -> int:
    async with httpx.AsyncClient() as client:
        state_path = _state_path()
        guard = RefreshGuard(state_path, config.min_refresh_seconds)  # type: ignore[attr-defined]
        now = datetime.now().astimezone()
        provider_id = config.provider  # type: ignore[attr-defined]
        guard_key = f"{provider_id}:{account.id}" if account else provider_id

        if args.command in {
            "balance",
            "bills",
            "payments",
            "invoices",
            "rebates",
            "contract-bills",
            "usage-details",
        }:
            guard.check(guard_key, now)
            session_path = config.unicom_session_path  # type: ignore[attr-defined]
            if session_path is None:
                raise ConfigurationError("缺少中国联通登录会话")
            web_client = ChinaUnicomWebClient(client, session_path)
            if args.command == "balance":
                data: object = await web_client.query_balance()
            elif args.command == "bills":
                data = await web_client.query_bill(parse_month(args.month))
            elif args.command == "payments":
                start, end = parse_month_range(args.from_month, args.to_month)
                data = await web_client.query_payments(start, end)
            elif args.command == "invoices":
                data = await web_client.query_invoices(parse_month(args.month))
            elif args.command == "rebates":
                data = await web_client.query_rebates()
            elif args.command == "contract-bills":
                data = await web_client.query_contract_bill(parse_month(args.month))
            else:
                data = await web_client.query_usage_details(args.category, parse_month(args.month))
            envelope = WebQueryEnvelope(
                "1.0",
                "china_unicom",
                account.id if account else "legacy-unicom",
                account.alias if account else "我的联通",
                args.command,
                now,
                data,
            )
            print(
                render_web_json(envelope) if args.format == "json" else render_web_summary(envelope)
            )
            guard.record(guard_key, now)
            return 0
        provider = create_provider(config.provider, config, client)  # type: ignore[attr-defined,arg-type]
        if args.command == "doctor":
            await provider.authenticate()
            print("运营商认证成功，未输出任何凭据。")
            return 0

        if args.command == "allowances":
            guard.check(guard_key, now)
            await provider.authenticate()
            allowance_data = await provider.get_allowances(QueryScope.ALL)
            envelope = WebQueryEnvelope(
                "1.0",
                provider.provider_id,
                account.id if account else "legacy-unicom",
                account.alias if account else "我的联通",
                "allowances",
                now,
                allowance_data,
            )
            print(
                render_web_json(envelope) if args.format == "json" else render_web_summary(envelope)
            )
            guard.record(guard_key, now)
            return 0

        guard.check(guard_key, now)
        scope = QueryScope(args.scope)
        snapshot = await query_snapshot(
            provider,
            now,
            scope,
            account_id=account.id if account else None,
            account_alias=account.alias if account else None,
        )
        if (
            account
            and snapshot.account.phone_masked
            and snapshot.account.phone_masked != account.masked_phone
        ):
            AccountRegistry().update_masked_phone(account.id, snapshot.account.phone_masked)
        guard.record(guard_key, now)
        print(render_json(snapshot) if args.format == "json" else render_summary(snapshot))
        return 0


def _print_capabilities(provider_id: str) -> int:
    if provider_id != ChinaUnicomWebProvider.provider_id:
        raise UnsupportedCapabilityError(f"未知 Provider：{provider_id}")
    for capability in sorted(item.value for item in ChinaUnicomWebProvider.capabilities()):
        print(capability)
    return 0


def _state_path() -> Path:
    configured = os.environ.get("CARRIER_USAGE_STATE_DIR")
    root = Path(configured) if configured else Path("~/.local/state").expanduser()
    return root / "carrier-usage" / "query-state.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="安全查询运营商余额、套餐和剩余用量")
    subparsers = parser.add_subparsers(dest="command", required=True)
    query = subparsers.add_parser("query", help="查询账户和余量")
    _provider_options(query, default_provider=None)
    query.add_argument("--account", help="账户 ID、准确中文别名或准确脱敏号码")
    query.add_argument("--format", choices=("summary", "json"), default="summary")
    query.add_argument(
        "--scope",
        choices=tuple(item.value for item in QueryScope),
        default=QueryScope.OVERVIEW.value,
        help="查询范围：概览、流量、语音、短信、成员、其他资源或全部",
    )
    for command, help_text in (
        ("balance", "查询剩余话费"),
        ("allowances", "查询套餐余量"),
        ("bills", "查询月账单"),
    ):
        business = subparsers.add_parser(command, help=help_text)
        _provider_options(business, default_provider=None)
        business.add_argument("--account", help="账户 ID、准确中文别名或准确脱敏号码")
        business.add_argument("--format", choices=("summary", "json"), default="summary")
        if command == "allowances":
            business.add_argument("--detail", action="store_true")
        if command == "bills":
            business.add_argument("--month", required=True, help="账单月份，格式 YYYY-MM")
    for command, help_text in (
        ("payments", "查询交费记录"),
        ("invoices", "查询已有电子发票"),
        ("rebates", "查询返费与赠款"),
        ("contract-bills", "查询金融合约账单"),
        ("usage-details", "查询详单（需要官方短信二次认证）"),
    ):
        business = subparsers.add_parser(command, help=help_text)
        _provider_options(business, default_provider=None)
        business.add_argument("--account", help="账户 ID、准确中文别名或准确脱敏号码")
        business.add_argument("--format", choices=("summary", "json"), default="summary")
        if command == "payments":
            business.add_argument("--from", dest="from_month", required=True, help="起始月份")
            business.add_argument("--to", dest="to_month", required=True, help="结束月份")
        if command in {"invoices", "contract-bills", "usage-details"}:
            business.add_argument("--month", required=True, help="月份，格式 YYYY-MM")
        if command == "usage-details":
            business.add_argument("--category", choices=("data", "voice", "sms"), required=True)
    capabilities = subparsers.add_parser("capabilities", help="列出 Provider 能力")
    _provider_options(capabilities, include_config=False)
    doctor = subparsers.add_parser("doctor", help="验证配置和认证")
    _provider_options(doctor, default_provider=None)
    doctor.add_argument("--account", help="账户 ID、准确中文别名或准确脱敏号码")
    login = subparsers.add_parser("login", help="通过运营商官方页面登录")
    _provider_options(login, include_config=False)
    login.add_argument("--session", help="本机会话文件路径")
    login.add_argument("--alias", help="账户中文别名")
    login.add_argument("--default", action=argparse.BooleanOptionalAction, default=None)
    login.add_argument("--provider-default", action=argparse.BooleanOptionalAction, default=None)
    accounts = subparsers.add_parser("accounts", help="管理已绑定账户")
    account_commands = accounts.add_subparsers(dest="accounts_command", required=True)
    account_commands.add_parser("list", help="列出账户")
    rename = account_commands.add_parser("rename", help="修改中文别名")
    rename.add_argument("account")
    rename.add_argument("alias")
    for command in ("set-default", "set-provider-default"):
        target = account_commands.add_parser(command)
        target.add_argument("account")
    remove = account_commands.add_parser("remove", help="解除账户绑定")
    remove.add_argument("account")
    remove.add_argument("--delete-session", action="store_true")
    return parser


def _provider_options(
    parser: argparse.ArgumentParser,
    *,
    include_config: bool = True,
    default_provider: str | None = "china_unicom",
) -> None:
    parser.add_argument("--provider", default=default_provider)
    if include_config:
        parser.add_argument("--config", default=os.environ.get("CARRIER_USAGE_CONFIG"))
