# 中国联通网页查询 CLI 第一批实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `balance`、`allowances`、`bills` 三个只读 CLI 命令，让 Agent 通过中文账户别名获取联通网页余额、余量和月账单的稳定 JSON。

**Architecture:** 新建聚焦只读业务查询的 `ChinaUnicomWebClient`，复用现有扫码 Cookie 加载规则，通过独立解析器转换为不可变业务模型，再由统一结果信封和渲染器输出。现有 `ChinaUnicomWebProvider` 保持综合查询职责，并复用新客户端的认证和余额能力，修复 `overview` 余额缺失。

**Tech Stack:** Python 3.11、httpx、dataclasses、Decimal、argparse、pytest、respx、mypy、Ruff。

## Global Constraints

- 所有新增能力只读，不发起缴费、开票、下载或账户变更。
- 只接受中国联通官方 `10010.com` 域名会话 Cookie。
- 不保存真实响应、Cookie、Token、完整请求头、完整手机号或发票号码。
- 金额使用 `Decimal`，JSON 中输出十进制字符串。
- 文档和用户交互优先中文。
- 真实接口响应不得进入测试 fixture；测试数据必须人工构造并完全脱敏。
- 查询继续按账户 ID 隔离刷新保护。
- 版本从 `0.2.1` 升级为 `0.3.0`。

## 已确认的联通官方契约

| 能力 | 方法与 URL | Referer |
|---|---|---|
| 剩余话费 | `POST https://mxx.client.10010.com/servicequerybusiness/balancenew/accountBalancenew.htm` | `https://imgxx.client.10010.com/shengyuhuafeiwt2024/index.html#/` |
| 可查询账单月份 | `POST https://m.client.10010.com/serviceimportantbusiness/phoneBill/queryMonths` | `https://img.client.10010.com/WThuafeiyuzhangdan/index.html#/` |
| 月账单明细 | `POST https://m.client.10010.com/serviceimportantbusiness/phoneBill/queryDetail` | `https://img.client.10010.com/WThuafeiyuzhangdan/index.html#/` |
| 套餐余量 | `POST https://mxx.client.10010.com/servicequerybusiness/operationservice/queryOcsPackageFlowLeftContentRevisedInJune` | `https://imgxx.client.10010.com/yuliangchaxunsfwt/index.html#/` |

所有请求使用 `application/x-www-form-urlencoded`、`version=WT`、15 秒超时和当前账户扫码会话。余额成功状态为 `code == "0000"`。余额字段映射为：

- `curntbalancecust` → 剩余话费；
- `newCarryOverArrears` → 上月结转话费；
- `newDepositForTheMonth` → 本月存入；
- `realfeecustnew` → 本月已消费；
- `queryTime` → 联通查询时间。

---

### Task 1: 第一批业务模型与统一结果信封

**Files:**
- Create: `carrier_usage/web_models.py`
- Test: `tests/test_web_models.py`

**Interfaces:**
- Produces: `BalanceInfo(remaining_cny, carried_cny, deposited_cny, consumed_cny, source_queried_at)`。
- Produces: `BillLine(name, original_cny, discount_cny, rebate_cny, payable_cny, children)`。
- Produces: `MonthlyBill(month, consumed_cny, overdue_cny, original_cny, discount_cny, rebate_cny, payable_cny, lines, status)`。
- Produces: `WebQueryEnvelope(schema_version, provider, account_id, account_alias, query_type, queried_at, data, warnings)`。
- Produces: `parse_month(value: str) -> date`，仅接受 `YYYY-MM`。

- [ ] **Step 1: 编写金额约束、月份解析和不可变模型的失败测试**

```python
def test_parse_month_accepts_year_month_and_rejects_invalid() -> None:
    assert parse_month("2026-08") == date(2026, 8, 1)
    with pytest.raises(ConfigurationError, match="YYYY-MM"):
        parse_month("2026/08")


def test_balance_rejects_negative_consumption() -> None:
    with pytest.raises(ValueError, match="consumed_cny"):
        BalanceInfo(Decimal("1"), Decimal("1"), Decimal("0"), Decimal("-1"), None)
```

- [ ] **Step 2: 运行测试并确认模块尚不存在**

Run: `.venv312/bin/pytest tests/test_web_models.py -v`
Expected: FAIL，提示 `carrier_usage.web_models` 不存在。

- [ ] **Step 3: 实现不可变业务模型和严格月份解析**

```python
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


def parse_month(value: str) -> date:
    try:
        parsed = datetime.strptime(value, "%Y-%m").date()
    except ValueError as error:
        raise ConfigurationError("月份必须使用 YYYY-MM 格式") from error
    return parsed.replace(day=1)
```

- [ ] **Step 4: 运行模型测试**

Run: `.venv312/bin/pytest tests/test_web_models.py -v`
Expected: PASS。

- [ ] **Step 5: 提交业务模型**

```bash
git add carrier_usage/web_models.py tests/test_web_models.py
git commit -m "feat: add Unicom web query models"
```

---

### Task 2: 联通网页业务客户端与余额解析

**Files:**
- Create: `carrier_usage/providers/china_unicom_web_client.py`
- Create: `carrier_usage/providers/china_unicom_web_queries.py`
- Modify: `carrier_usage/providers/china_unicom_web.py`
- Test: `tests/test_unicom_web_queries.py`
- Test: `tests/test_unicom_web_provider.py`

**Interfaces:**
- Consumes: Task 1 的 `BalanceInfo`。
- Produces: `parse_balance(payload: Mapping[str, object]) -> BalanceInfo`。
- Produces: `ChinaUnicomWebClient.load_session(path)` 和 `query_balance()`。
- Produces: Provider `get_account()` 优先使用独立余额接口，失败时保留当前汇总结果并添加警告的编排接口。

- [ ] **Step 1: 编写余额字段解析和 HTTP 契约失败测试**

```python
BALANCE_PAYLOAD = {
    "code": "0000",
    "queryTime": "2026-08-05 10:20:30",
    "curntbalancecust": "142.35",
    "newCarryOverArrears": "157.35",
    "newDepositForTheMonth": "20.00",
    "realfeecustnew": "35.00",
}


def test_parse_balance_maps_official_fields() -> None:
    result = parse_balance(BALANCE_PAYLOAD)
    assert result.remaining_cny == Decimal("142.35")
    assert result.carried_cny == Decimal("157.35")
    assert result.deposited_cny == Decimal("20.00")
    assert result.consumed_cny == Decimal("35.00")


@pytest.mark.asyncio
@respx.mock
async def test_query_balance_uses_read_only_official_endpoint(tmp_path: Path) -> None:
    session = secure_unicom_session(tmp_path)
    route = respx.post(BALANCE_URL).mock(return_value=httpx.Response(200, json=BALANCE_PAYLOAD))
    async with httpx.AsyncClient() as http:
        client = ChinaUnicomWebClient(http, session)
        result = await client.query_balance()
    request = route.calls.last.request
    assert request.headers["referer"] == BALANCE_REFERER
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert request.content == b"version=WT"
    assert result.remaining_cny == Decimal("142.35")
```

- [ ] **Step 2: 运行测试并确认客户端和解析器不存在**

Run: `.venv312/bin/pytest tests/test_unicom_web_queries.py -v`
Expected: FAIL，提示客户端或解析函数不存在。

- [ ] **Step 3: 实现共享认证、只读 POST 和余额解析**

```python
BALANCE_URL = (
    "https://mxx.client.10010.com/servicequerybusiness/"
    "balancenew/accountBalancenew.htm"
)
BALANCE_REFERER = "https://imgxx.client.10010.com/shengyuhuafeiwt2024/index.html#/"


async def query_balance(self) -> BalanceInfo:
    payload = await self._post(BALANCE_URL, BALANCE_REFERER, {"version": "WT"})
    if str(payload.get("code")) != "0000":
        raise AuthenticationError("中国联通剩余话费查询失败或会话已失效")
    return parse_balance(payload)
```

客户端只加载域名为 `10010.com` 或其子域的 Cookie。`_post()` 统一处理网络错误、JSON 校验、状态码和 15 秒超时，不记录原始响应。

- [ ] **Step 4: 让综合 Provider 复用业务客户端余额**

Provider 认证后使用同一 `httpx.AsyncClient` 和同一会话。`get_account()` 将 `BalanceInfo.remaining_cny` 写入 `AccountSnapshot.balance_cny`，将 `consumed_cny` 写入 `current_charges_cny`；余额接口失败时仅在综合查询中降级，独立 `balance` 命令仍返回明确错误。

- [ ] **Step 5: 运行余额客户端和 Provider 回归测试**

Run: `.venv312/bin/pytest tests/test_unicom_web_queries.py tests/test_unicom_web_provider.py -v`
Expected: PASS。

- [ ] **Step 6: 提交余额客户端**

```bash
git add carrier_usage/providers/china_unicom_web_client.py carrier_usage/providers/china_unicom_web_queries.py carrier_usage/providers/china_unicom_web.py tests/test_unicom_web_queries.py tests/test_unicom_web_provider.py
git commit -m "feat: query Unicom remaining balance"
```

---

### Task 3: 月账单和可查询月份

**Files:**
- Modify: `carrier_usage/providers/china_unicom_web_client.py`
- Modify: `carrier_usage/providers/china_unicom_web_queries.py`
- Test: `tests/test_unicom_web_queries.py`

**Interfaces:**
- Consumes: Task 1 的 `MonthlyBill` 和 `BillLine`。
- Produces: `query_bill_months() -> tuple[date, ...]`。
- Produces: `query_bill(month: date) -> MonthlyBill`。
- Produces: `parse_bill_months(payload) -> tuple[date, ...]` 和 `parse_monthly_bill(payload, month) -> MonthlyBill`。

- [ ] **Step 1: 编写月份列表、账单层级和空账单失败测试**

```python
def test_parse_bill_months_normalizes_official_year_month_items() -> None:
    payload = {"code": "0000", "data": [{"historyYear": "2026", "historyMonth": "8"}]}
    assert parse_bill_months(payload) == (date(2026, 8, 1),)


def test_parse_monthly_bill_keeps_fee_semantics() -> None:
    payload = {
        "code": "0000",
        "data": {
            "totalprice": "47.25",
            "totalDiscount": "2.00",
            "totalspayfee": "45.25",
            "allpayfee": "45.25",
            "allnopayfee": "0.00",
            "adjustment": {"rebateDeduction": "0.00"},
            "acctBillList": [
                {
                    "bill": {
                        "integrateitem": "套餐费",
                        "originalFee": "39.00",
                        "payableFee": "37.00"
                    }
                }
            ],
            "userBillList": []
        },
    }
    bill = parse_monthly_bill(payload, date(2026, 8, 1))
    assert bill.consumed_cny == Decimal("45.25")
    assert bill.lines[0].name == "套餐费"
```

- [ ] **Step 2: 运行账单解析测试并确认函数不存在**

Run: `.venv312/bin/pytest tests/test_unicom_web_queries.py -k 'bill' -v`
Expected: FAIL，提示账单函数不存在。

- [ ] **Step 3: 实现账单接口和兼容字段解析**

```python
BILL_MONTHS_URL = (
    "https://m.client.10010.com/serviceimportantbusiness/phoneBill/queryMonths"
)
BILL_DETAIL_URL = (
    "https://m.client.10010.com/serviceimportantbusiness/phoneBill/queryDetail"
)
BILL_REFERER = "https://img.client.10010.com/WThuafeiyuzhangdan/index.html#/"


async def query_bill(self, month: date) -> MonthlyBill:
    payload = await self._post(
        BILL_DETAIL_URL,
        BILL_REFERER,
        {"version": "WT", "month": month.strftime("%Y%m")},
    )
    return parse_monthly_bill(payload, month)
```

解析器通过有序候选字段兼容账户级、用户级和省份差异；无法识别核心金额时抛出 `UpstreamChangedError`，可选字段缺失时返回 `None` 和 `partial` 状态。空月份列表返回空元组。

- [ ] **Step 4: 运行账单定向测试**

Run: `.venv312/bin/pytest tests/test_unicom_web_queries.py -k 'bill' -v`
Expected: PASS。

- [ ] **Step 5: 提交月账单能力**

```bash
git add carrier_usage/providers/china_unicom_web_client.py carrier_usage/providers/china_unicom_web_queries.py tests/test_unicom_web_queries.py
git commit -m "feat: query Unicom monthly bills"
```

---

### Task 4: 统一 CLI 命令和渲染

**Files:**
- Create: `carrier_usage/web_render.py`
- Modify: `carrier_usage/cli.py`
- Test: `tests/test_web_render.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 1–3 的模型、业务客户端和账户解析。
- Produces: `balance`、`allowances`、`bills` 命令。
- Produces: `render_web_json(envelope)` 和 `render_web_summary(envelope)`。

- [ ] **Step 1: 编写 CLI 参数、JSON 信封和中文摘要失败测试**

```python
def test_balance_command_accepts_account_and_json() -> None:
    args = _parser().parse_args(["balance", "--account", "我的联通", "--format", "json"])
    assert args.command == "balance"
    assert args.account == "我的联通"


def test_bills_requires_valid_month() -> None:
    assert main(["bills", "--account", "我的联通", "--month", "2026/08"]) == 2


def test_balance_json_uses_stable_envelope() -> None:
    payload = json.loads(render_web_json(balance_envelope()))
    assert payload["query_type"] == "balance"
    assert payload["data"]["remaining_balance_cny"] == "142.35"
    assert "session_path" not in json.dumps(payload)
```

- [ ] **Step 2: 运行 CLI 和渲染测试并确认命令不存在**

Run: `.venv312/bin/pytest tests/test_cli.py tests/test_web_render.py -v`
Expected: FAIL，`argparse` 拒绝新命令或渲染模块不存在。

- [ ] **Step 3: 实现三个显式业务命令**

```python
balance = subparsers.add_parser("balance", help="查询剩余话费")
_account_query_options(balance)

allowances = subparsers.add_parser("allowances", help="查询套餐余量")
_account_query_options(allowances)
allowances.add_argument("--detail", action="store_true")

bills = subparsers.add_parser("bills", help="查询月账单")
_account_query_options(bills)
bills.add_argument("--month", required=True, help="账单月份，格式 YYYY-MM")
```

三个命令复用账户解析、会话配置和账户级刷新键。`allowances --detail` 使用现有 `QueryScope.ALL` 的通信余量解析，但不额外查询云盘和订阅。

- [ ] **Step 4: 实现稳定 JSON 和中文摘要**

余额摘要包含剩余话费、上月结转、本月存入、本月消费和查询时间。账单摘要包含月份、消费、待交费、原价、优惠、返赠、实际应付及费用项。缺失值显示“未提供”，不推断。

- [ ] **Step 5: 运行 CLI 和渲染测试**

Run: `.venv312/bin/pytest tests/test_cli.py tests/test_web_render.py -v`
Expected: PASS。

- [ ] **Step 6: 提交 CLI 第一批能力**

```bash
git add carrier_usage/cli.py carrier_usage/web_render.py tests/test_cli.py tests/test_web_render.py
git commit -m "feat: add Unicom balance allowance and bill commands"
```

---

### Task 5: Skill 触发词、中文文档和 0.3.0 验证

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `pyproject.toml`
- Modify: `tests/test_skill_docs.py`

**Interfaces:**
- Consumes: Task 4 的三个 CLI 命令。
- Produces: Agent 对“剩余话费、余额、账单、余量”的准确触发规则。
- Produces: 发布版本 `0.3.0`。

- [ ] **Step 1: 扩展文档契约测试并确认失败**

```python
def test_skill_documents_first_batch_web_queries() -> None:
    text = Path("SKILL.md").read_text(encoding="utf-8")
    for phrase in ("balance", "bills", "allowances", "剩余话费", "我的账单"):
        assert phrase in text
```

Run: `.venv312/bin/pytest tests/test_skill_docs.py -v`
Expected: FAIL，至少缺少新命令说明。

- [ ] **Step 2: 更新 Skill 触发规则**

明确映射：余额、剩余话费、本月消费 → `balance`；套餐余量、流量余量、语音余量 → `allowances`；我的账单、月账单、费用构成 → `bills --month`。更正旧提示为“当前 Skill 尚未接入独立余额接口”的历史语义，并在功能完成后删除该限制说明。

- [ ] **Step 3: 更新 README 和版本**

README 添加三个命令示例、JSON 字段、只读边界和地区差异说明。将 `pyproject.toml` 与 README 版本更新为 `0.3.0`。

- [ ] **Step 4: 执行完整验证**

Run: `.venv312/bin/pytest -q`
Expected: 全部 PASS。

Run: `.venv312/bin/ruff check .`
Expected: `All checks passed!`

Run: `.venv312/bin/mypy carrier_usage`
Expected: `Success: no issues found`。

Run: `.venv312/bin/python -m build`
Expected: 成功生成 `0.3.0` wheel 和 sdist。

Run: `.venv312/bin/python /Users/weieast/.codex/skills/.system/skill-creator/scripts/quick_validate.py .`
Expected: `Skill is valid!`

- [ ] **Step 5: 提交文档和版本**

```bash
git add SKILL.md README.md pyproject.toml tests/test_skill_docs.py
git commit -m "release: prepare Unicom web queries 0.3.0"
```

---

### Task 6: 最终安全与发布检查

**Files:**
- Modify only if verification reveals a defect.

**Interfaces:**
- Consumes: Tasks 1–5 的完整第一批实现。
- Produces: 可发布且无真实用户数据的 `0.3.0` 工作树。

- [ ] **Step 1: 搜索真实号码和敏感凭据**

Run: `rg -n "186[0-9*]{8}|354\.48|383\.48|Cookie:|Authorization:" carrier_usage tests SKILL.md README.md`
Expected: 不包含本次 Chrome 调试的真实金额和真实号码；测试仅使用人工构造的虚构金额和脱敏号码。

- [ ] **Step 2: 检查只读边界**

Run: `rg -n "sendEmail|printPDF|saveBill|paySeki|缴费|开票|下载发票" carrier_usage`
Expected: 不存在联通写操作实现；中文词仅可出现在明确禁止说明中。

- [ ] **Step 3: 检查 Git 状态和变更范围**

Run: `git diff --check && git status --short`
Expected: 无空白错误；任务均提交后工作树干净。

- [ ] **Step 4: 重新运行最终验证套件**

Run: `.venv312/bin/pytest -q && .venv312/bin/ruff check . && .venv312/bin/mypy carrier_usage && .venv312/bin/python -m build`
Expected: 测试、静态检查、类型检查和构建全部成功。
