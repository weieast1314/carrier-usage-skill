# 多运营商多账户选择实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为运营商用量 Skill 增加中文账户别名、全局默认与运营商默认、多账户无歧义选择、成员定位和旧版单账户会话迁移。

**Architecture:** 新增独立的 `account_registry` 模块，以权限为 `0600` 的 JSON 注册表管理非敏感账户元数据，并让每个账户指向独立会话文件。CLI 在创建 Provider 前统一解析 `--account`、运营商默认或全局默认；Skill 负责从自然语言和当前对话提取别名并把明确账户传给 CLI。

**Tech Stack:** Python 3.11、标准库 `dataclasses/json/pathlib/tempfile/argparse`、pytest、mypy、Ruff。

## Global Constraints

- 文档和用户交互优先使用中文。
- Cookie、Token、完整手机号和原始请求头不得进入注册表、日志或交互输出。
- 注册表与会话文件必须使用 `0600` 权限，目录使用 `0700` 权限。
- 单账户旧用户升级后无需重新登录，迁移必须幂等且不得提前删除旧会话。
- 账户选择不得模糊猜测；只有结果唯一或命中明确默认时才能自动选择。
- 当前不实现中国移动、中国电信和中国广电的业务接口。

---

### Task 1: 账户注册表与选择核心

**Files:**
- Create: `carrier_usage/account_registry.py`
- Modify: `carrier_usage/errors.py`
- Test: `tests/test_account_registry.py`

**Interfaces:**
- Produces: `AccountRecord(id: str, alias: str, provider: str, masked_phone: str | None, session_path: Path)`。
- Produces: `AccountRegistry(path: Path)` 的 `load()`、`add()`、`rename()`、`remove()`、`set_global_default()`、`set_provider_default()`、`resolve()` 和 `list_accounts()`。
- Produces: `default_registry_path() -> Path`、`account_session_path(account_id: str) -> Path`。
- Produces: `AccountNotFoundError`、`AccountAmbiguousError`、`AccountConflictError`，均继承 `ConfigurationError`。

- [ ] **Step 1: 编写注册表持久化、唯一性和选择顺序的失败测试**

```python
def test_registry_resolves_explicit_then_provider_default_then_global(tmp_path: Path) -> None:
    registry = AccountRegistry(tmp_path / "accounts.json")
    work = AccountRecord("unicom-work", "工作联通", "china_unicom", "138****1234", tmp_path / "work.json")
    home = AccountRecord("unicom-home", "家庭联通", "china_unicom", "186****5678", tmp_path / "home.json")
    registry.add(work)
    registry.add(home)
    registry.set_provider_default("unicom-home")
    registry.set_global_default("unicom-work")

    assert registry.resolve(account="工作联通").id == "unicom-work"
    assert registry.resolve(provider="china_unicom").id == "unicom-home"
    assert registry.resolve().id == "unicom-work"


def test_registry_reports_masked_candidates_when_ambiguous(tmp_path: Path) -> None:
    registry = populated_registry_without_defaults(tmp_path)
    with pytest.raises(AccountAmbiguousError) as captured:
        registry.resolve(provider="china_unicom")
    assert "工作联通（138****1234）" in str(captured.value)
    assert "家庭联通（186****5678）" in str(captured.value)
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `.venv312/bin/pytest tests/test_account_registry.py -v`
Expected: FAIL，提示 `carrier_usage.account_registry` 不存在。

- [ ] **Step 3: 实现不可变账户模型、安全原子写入和选择器**

```python
@dataclass(frozen=True, slots=True)
class AccountRecord:
    id: str
    alias: str
    provider: str
    masked_phone: str | None
    session_path: Path


class AccountRegistry:
    def resolve(self, *, account: str | None = None, provider: str | None = None) -> AccountRecord:
        candidates = [item for item in self.list_accounts() if provider is None or item.provider == provider]
        if account is not None:
            matches = [item for item in candidates if account in {item.id, item.alias, item.masked_phone}]
            return self._require_single(matches, account)
        state = self.load()
        default_id = state.provider_defaults.get(provider) if provider else state.global_default
        if default_id is not None:
            return self._require_single([item for item in candidates if item.id == default_id], default_id)
        return self._require_single(candidates, provider or "全部运营商")
```

实现要求：拒绝空别名、重复别名、重复 ID、非脱敏号码和不存在的默认账户；读取无效 JSON 时抛错且不覆盖原文件；写入使用同目录临时文件、`fsync`、原子替换和 `0600` 权限。

- [ ] **Step 4: 运行注册表测试**

Run: `.venv312/bin/pytest tests/test_account_registry.py -v`
Expected: PASS。

- [ ] **Step 5: 提交账户注册表核心**

```bash
git add carrier_usage/account_registry.py carrier_usage/errors.py tests/test_account_registry.py
git commit -m "feat: add secure account registry"
```

---

### Task 2: 旧会话迁移和账户级配置

**Files:**
- Modify: `carrier_usage/account_registry.py`
- Modify: `carrier_usage/config.py`
- Modify: `carrier_usage/web_session.py`
- Test: `tests/test_account_registry.py`
- Test: `tests/test_config.py`
- Test: `tests/test_web_session.py`

**Interfaces:**
- Consumes: Task 1 的 `AccountRecord`、`AccountRegistry`、`account_session_path()`。
- Produces: `migrate_legacy_session(registry, provider="china_unicom") -> AccountRecord | None`。
- Produces: `load_config(env: Mapping[str, str] | None = None, path: Path | None = None, account: AccountRecord | None = None) -> AppConfig`，显式账户会话覆盖旧默认会话。

- [ ] **Step 1: 编写幂等迁移和账户会话配置的失败测试**

```python
def test_migrate_legacy_session_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    legacy = default_session_path("china_unicom")
    save_browser_state(legacy, {"cookies": []})
    registry = AccountRegistry(tmp_path / "config" / "accounts.json")

    first = migrate_legacy_session(registry)
    second = migrate_legacy_session(registry)

    assert first == second
    assert first is not None and first.alias == "我的联通"
    assert legacy.is_file()
    assert registry.resolve().id == first.id


def test_account_session_overrides_legacy_config(tmp_path: Path) -> None:
    account = AccountRecord("unicom-work", "工作联通", "china_unicom", None, tmp_path / "work.json")
    config = load_config({"CARRIER_USAGE_MIN_REFRESH_SECONDS": "300"}, account=account)
    assert config.provider == "china_unicom"
    assert config.unicom_session_path == account.session_path
```

- [ ] **Step 2: 运行定向测试并确认失败**

Run: `.venv312/bin/pytest tests/test_account_registry.py tests/test_config.py tests/test_web_session.py -v`
Expected: FAIL，提示迁移函数或 `account` 参数不存在。

- [ ] **Step 3: 实现迁移和账户级配置覆盖**

```python
def migrate_legacy_session(
    registry: AccountRegistry,
    provider: str = "china_unicom",
) -> AccountRecord | None:
    existing = registry.list_accounts()
    if existing:
        return next((item for item in existing if item.provider == provider), None)
    legacy = default_session_path(provider)
    if not legacy.is_file():
        return None
    account = AccountRecord("china-unicom-default", "我的联通", provider, None, legacy)
    registry.add(account)
    registry.set_provider_default(account.id)
    registry.set_global_default(account.id)
    return account
```

`default_session_path()` 保持原路径以识别旧文件；新增账户会话统一使用 `sessions/<account-id>.json`。迁移只建立安全引用，不删除或复制含凭证的旧文件。

- [ ] **Step 4: 运行定向测试**

Run: `.venv312/bin/pytest tests/test_account_registry.py tests/test_config.py tests/test_web_session.py -v`
Expected: PASS。

- [ ] **Step 5: 提交迁移和配置改造**

```bash
git add carrier_usage/account_registry.py carrier_usage/config.py carrier_usage/web_session.py tests/test_account_registry.py tests/test_config.py tests/test_web_session.py
git commit -m "feat: migrate legacy carrier sessions"
```

---

### Task 3: 登录绑定和账户管理 CLI

**Files:**
- Modify: `carrier_usage/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 1 的注册表增删改查和 Task 2 的会话路径。
- Produces: `login --alias <中文别名> [--default] [--provider-default]`。
- Produces: `accounts list|rename|set-default|set-provider-default|remove`。
- Produces: `query|doctor --account <账户 ID、准确别名或准确脱敏号码>`。

- [ ] **Step 1: 编写登录绑定与账户管理命令的失败测试**

```python
def test_login_registers_alias_and_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_registry_roots(monkeypatch, tmp_path)
    monkeypatch.setattr("carrier_usage.cli.login_unicom_interactively", lambda path: None)
    exit_code = main(["login", "--provider", "china_unicom", "--alias", "工作联通", "--default"])
    registry = AccountRegistry(default_registry_path())
    account = registry.resolve(account="工作联通")
    assert exit_code == 0
    assert registry.resolve().id == account.id
    assert registry.resolve(provider="china_unicom").id == account.id


def test_accounts_list_only_prints_masked_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    configure_registry_roots(monkeypatch, tmp_path)
    seed_account(alias="工作联通", masked_phone="138****1234")
    assert main(["accounts", "list"]) == 0
    output = capsys.readouterr().out
    assert "工作联通" in output and "138****1234" in output
```

- [ ] **Step 2: 运行 CLI 测试并确认新参数和命令尚不存在**

Run: `.venv312/bin/pytest tests/test_cli.py -v`
Expected: FAIL，`argparse` 拒绝 `accounts`、`--alias` 或 `--account`。

- [ ] **Step 3: 实现 CLI 绑定、管理和账户解析**

```python
login.add_argument("--alias", help="账户中文别名；省略时交互询问")
login.add_argument("--default", action=argparse.BooleanOptionalAction, default=None)
login.add_argument("--provider-default", action=argparse.BooleanOptionalAction, default=None)
query.add_argument("--account", help="账户 ID、准确别名或准确脱敏号码")
doctor.add_argument("--account", help="账户 ID、准确别名或准确脱敏号码")
```

第一张卡自动设为运营商默认；交互模式询问中文别名和是否替换默认；非交互模式完全由参数控制。`accounts remove` 默认仅删除注册信息，只有 `--delete-session` 才删除经过解析验证、位于 carrier-usage 数据目录内的单个会话文件。

- [ ] **Step 4: 运行 CLI 与原有配置测试**

Run: `.venv312/bin/pytest tests/test_cli.py tests/test_config.py -v`
Expected: PASS。

- [ ] **Step 5: 提交 CLI 多账户支持**

```bash
git add carrier_usage/cli.py tests/test_cli.py
git commit -m "feat: add carrier account management commands"
```

---

### Task 4: 查询结果身份和账户级刷新隔离

**Files:**
- Modify: `carrier_usage/models.py`
- Modify: `carrier_usage/service.py`
- Modify: `carrier_usage/cli.py`
- Modify: `carrier_usage/render.py`
- Test: `tests/test_models.py`
- Test: `tests/test_service.py`
- Test: `tests/test_render.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 3 解析得到的 `AccountRecord`。
- Produces: `CarrierSnapshot.account_id: str | None` 和 `account_alias: str | None`。
- Produces: `query_snapshot(provider: CarrierProvider, now: datetime, scope: QueryScope = QueryScope.OVERVIEW, *, account_id: str | None = None, account_alias: str | None = None) -> CarrierSnapshot`。
- Produces: `RefreshGuard.check(key: str, now)` 与 `record(key: str, now)`，CLI 传入 `f"{provider}:{account_id}"`。

- [ ] **Step 1: 编写结果身份和限流隔离的失败测试**

```python
@pytest.mark.asyncio
async def test_snapshot_carries_local_account_identity() -> None:
    snapshot = await query_snapshot(
        FakeProvider(), datetime(2026, 8, 4, tzinfo=UTC),
        account_id="unicom-work", account_alias="工作联通",
    )
    assert snapshot.account_id == "unicom-work"
    assert snapshot.account_alias == "工作联通"


def test_refresh_guard_isolates_accounts(tmp_path: Path) -> None:
    guard = RefreshGuard(tmp_path / "state.json", 300)
    now = datetime(2026, 8, 4, tzinfo=UTC)
    guard.record("china_unicom:unicom-work", now)
    guard.check("china_unicom:unicom-home", now)
```

- [ ] **Step 2: 运行定向测试并确认签名或字段缺失**

Run: `.venv312/bin/pytest tests/test_models.py tests/test_service.py tests/test_render.py tests/test_cli.py -v`
Expected: FAIL，提示账户身份字段或参数不存在。

- [ ] **Step 3: 实现账户身份透传、脱敏渲染和限流键**

```python
@dataclass(frozen=True, slots=True)
class CarrierSnapshot:
    schema_version: str
    provider: str
    account: AccountSnapshot
    plan: PlanInfo
    allowances: tuple[Allowance, ...]
    subscriptions: CapabilityResult
    queried_at: datetime
    account_id: str | None = None
    account_alias: str | None = None
    lines: tuple[LineUsage, ...] = ()
    resources: tuple[ResourceUsage, ...] = ()
    warnings: tuple[str, ...] = ()
```

JSON 和摘要输出增加本地别名及账户 ID，不输出会话路径。认证错误在 CLI 边界补充“账户别名（脱敏号码）”上下文，但继续经过 `redact_text()`。成员数据继续由 `members`/`all` 范围返回，不改变 Provider 协议。

- [ ] **Step 4: 运行定向测试**

Run: `.venv312/bin/pytest tests/test_models.py tests/test_service.py tests/test_render.py tests/test_cli.py -v`
Expected: PASS。

- [ ] **Step 5: 提交查询身份和限流隔离**

```bash
git add carrier_usage/models.py carrier_usage/service.py carrier_usage/cli.py carrier_usage/render.py tests/test_models.py tests/test_service.py tests/test_render.py tests/test_cli.py
git commit -m "feat: isolate carrier queries by account"
```

---

### Task 5: Skill 触发词、中文文档与完整验证

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `examples/config.example.toml`
- Modify: `pyproject.toml`
- Test: `tests/test_skill_docs.py`

**Interfaces:**
- Consumes: Tasks 1–4 的 CLI 命令和选择规则。
- Produces: Agent 可执行的自然语言账户选择、对话延续和成员歧义处理说明。
- Produces: 发布版本 `0.2.0`。

- [ ] **Step 1: 编写文档契约失败测试**

```python
def test_skill_documents_multi_account_selection() -> None:
    text = Path("SKILL.md").read_text(encoding="utf-8")
    for phrase in ("--account", "全局默认", "运营商默认", "脱敏选项", "当前对话"):
        assert phrase in text
```

- [ ] **Step 2: 运行文档测试并确认缺少多账户说明**

Run: `.venv312/bin/pytest tests/test_skill_docs.py -v`
Expected: FAIL，至少缺少 `--account`。

- [ ] **Step 3: 更新 Skill、README、示例和版本**

Skill 必须明确：识别准确别名后传 `--account`；“查流量”走全局默认；“查联通流量”走联通默认；“再看看套餐”延续当前对话账户；只有真正歧义时列出别名、运营商和脱敏号码；成员/副卡先定位主账户再定位成员；不得要求完整手机号或会话内容。

README 增加绑定第二张卡、查看账户、设置双层默认、删除绑定和旧版自动迁移示例。`pyproject.toml` 版本更新为 `0.2.0`。

- [ ] **Step 4: 运行全部测试和静态检查**

Run: `.venv312/bin/pytest -q`
Expected: 全部 PASS。

Run: `.venv312/bin/ruff check .`
Expected: `All checks passed!`

Run: `.venv312/bin/mypy carrier_usage`
Expected: `Success: no issues found`。

Run: `.venv312/bin/python -m build`
Expected: 成功生成 `0.2.0` wheel 和 sdist。

Run: `.venv312/bin/python /Users/weieast/.codex/skills/.system/skill-creator/scripts/quick_validate.py .`
Expected: `Skill is valid!`

- [ ] **Step 5: 提交文档和版本**

```bash
git add SKILL.md README.md examples/config.example.toml pyproject.toml tests/test_skill_docs.py
git commit -m "release: prepare multi-account support"
```

---

### Task 6: 最终安全回归与交付检查

**Files:**
- Modify only if verification reveals a defect.

**Interfaces:**
- Consumes: Tasks 1–5 的完整实现。
- Produces: 可发布、无敏感数据泄漏的 `0.2.0` 工作树。

- [ ] **Step 1: 检查敏感实现和遗留术语**

Run: `rg -n -i "openid|完整手机号|cookie|token|ticket" carrier_usage tests SKILL.md README.md`
Expected: 仅出现安全禁止说明、通用脱敏键和必要的浏览器会话解析；不存在 OpenID 兼容实现或要求用户提供凭证的文案。

- [ ] **Step 2: 检查 Git 变更范围和空白错误**

Run: `git status --short && git diff --check`
Expected: 无未计划文件、无空白错误；若每任务均已提交则工作树干净。

- [ ] **Step 3: 运行最终验证套件**

Run: `.venv312/bin/pytest -q && .venv312/bin/ruff check . && .venv312/bin/mypy carrier_usage && .venv312/bin/python -m build`
Expected: 测试、静态检查、类型检查和构建全部成功。

- [ ] **Step 4: 核对提交历史**

Run: `git log --oneline -8`
Expected: 设计、计划、注册表、迁移、CLI、查询隔离和发布准备均有清晰提交。
