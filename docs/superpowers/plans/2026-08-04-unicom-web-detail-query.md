# 中国联通网页明细查询与中文触发词实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 复用中国联通扫码网页会话，按中文查询意图返回流量、语音、短信、成员/副卡和云盘明细。

**架构：** 继续以 `ChinaUnicomWebProvider` 为联通网页适配层，调用余量页使用的 `mxx.client.10010.com` 只读接口并转换为运营商无关模型。通用服务层通过 `QueryScope` 选择最小查询范围；CLI 和 SKILL.md 只暴露稳定范围与中文意图，不暴露联通接口细节。

**技术栈：** Python 3.11+、httpx、asyncio、dataclasses、pytest、respx、Ruff、mypy、Agent Skills 规范。

## 全局约束

- 文档、CLI 提示和默认摘要优先使用中文。
- 只查询用户本人或明确授权的账户。
- 不办理充值、缴费、套餐变更、退订或云盘开通。
- 不查询通话详单、短信详单、上网记录或通信对象。
- 完整手机号在进入输出模型前脱敏；不得输出 Cookie、令牌、请求头或原始响应。
- 测试只能使用人工构造的匿名数据，不得保存真实账户响应。
- 会话 Cookie 只能发送至 `10010.com` 及其官方子域。
- 成员/副卡能力默认可用，但普通 `overview` 查询不得展开成员信息。
- 流量统一为 byte，语音统一为 second，短信统一为 count。
- 采用测试驱动开发：每个生产行为先写失败测试并确认失败，再写最小实现。

---

## 文件结构

- 修改 `carrier_usage/models.py`：查询范围、成员和其他资源通用模型。
- 修改 `carrier_usage/providers/base.py`：Provider 新能力协议。
- 创建 `carrier_usage/providers/china_unicom_web_detail.py`：联通余量与云盘响应解析，避免继续膨胀汇总 Provider。
- 修改 `carrier_usage/providers/china_unicom_web.py`：明细接口请求、缓存和能力实现。
- 修改 `carrier_usage/service.py`：按范围编排查询并支持非核心能力部分失败。
- 修改 `carrier_usage/render.py`：成员和其他资源的稳定 JSON/中文摘要。
- 修改 `carrier_usage/cli.py`：`--scope` 参数。
- 修改 `SKILL.md`、`README.md`、`agents/openai.yaml`：中文触发词与用法。
- 创建 `tests/fixtures/unicom/web_detail.json`、`tests/fixtures/unicom/web_disk.json`：人工匿名响应。
- 创建 `tests/test_unicom_web_detail.py`：解析测试。
- 修改 `tests/test_models.py`、`tests/provider_contract.py`、`tests/test_unicom_web_provider.py`、`tests/test_service.py`、`tests/test_render.py`、`tests/test_cli.py`：契约和回归测试。

### Task 1：建立查询范围、成员和其他资源模型

**Files:**
- Modify: `carrier_usage/models.py`
- Modify: `tests/test_models.py`

**Interfaces:**
- Produces: `QueryScope`, `LineRole`, `LineUsage`, `ResourceUsage`。
- Produces: `CarrierSnapshot.lines: tuple[LineUsage, ...]` 与 `CarrierSnapshot.resources: tuple[ResourceUsage, ...]`。
- Produces: `AccountSnapshot.loyalty_points: int | None`，用于首页可用积分。

- [ ] **Step 1: 写失败测试**

在 `tests/test_models.py` 增加：

```python
from carrier_usage.models import Allowance, LineRole, LineUsage, ResourceUsage


def test_line_usage_requires_masked_phone() -> None:
    with pytest.raises(ValueError, match="成员号码必须脱敏"):
        LineUsage("13800138000", LineRole.SECONDARY, ())


def test_resource_usage_rejects_negative_capacity() -> None:
    with pytest.raises(ValueError, match="used must be non-negative"):
        ResourceUsage("联通云盘", "普通会员", -1, 60 * 1024**3, "active")
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv312/bin/python -m pytest tests/test_models.py -q`

Expected: FAIL，提示无法导入 `LineRole`、`LineUsage` 或 `ResourceUsage`。

- [ ] **Step 3: 写最小模型实现**

在 `carrier_usage/models.py` 增加：

```python
class QueryScope(str, Enum):
    OVERVIEW = "overview"
    DATA = "data"
    VOICE = "voice"
    SMS = "sms"
    MEMBERS = "members"
    RESOURCES = "resources"
    ALL = "all"


class LineRole(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    MEMBER = "member"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LineUsage:
    phone_masked: str
    role: LineRole
    allowances: tuple[Allowance, ...]

    def __post_init__(self) -> None:
        if "*" not in self.phone_masked:
            raise ValueError("成员号码必须脱敏")


@dataclass(frozen=True, slots=True)
class ResourceUsage:
    name: str
    tier: str | None
    used: int | None
    total: int | None
    status: str | None

    def __post_init__(self) -> None:
        for field_name in ("used", "total"):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must be non-negative")
```

为 `CarrierSnapshot` 增加默认空元组字段 `lines` 和 `resources`；将默认字段放在无默认字段之后，保持 dataclass 合法。

为 `AccountSnapshot` 最后增加默认字段 `loyalty_points: int | None = None`，保持现有位置参数调用兼容；拒绝负积分。

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: `.venv312/bin/python -m pytest tests/test_models.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add carrier_usage/models.py tests/test_models.py
git commit -m "feat: add scoped carrier detail models"
```

### Task 2：解析联通余量、成员和云盘响应

**Files:**
- Create: `carrier_usage/providers/china_unicom_web_detail.py`
- Create: `tests/fixtures/unicom/web_detail.json`
- Create: `tests/fixtures/unicom/web_disk.json`
- Create: `tests/test_unicom_web_detail.py`

**Interfaces:**
- Consumes: `Allowance`, `LineUsage`, `ResourceUsage`。
- Produces: `parse_web_allowances(payload, category) -> tuple[Allowance, ...]`。
- Produces: `parse_web_lines(payload) -> tuple[LineUsage, ...]`。
- Produces: `parse_web_resources(payload) -> tuple[ResourceUsage, ...]`。

- [ ] **Step 1: 创建匿名 fixture 并写失败测试**

`web_detail.json` 使用虚构号码 `13800138000`、`13800138001`，包含：90 GB 和 10 GB 流量包、200 分钟和 800 分钟语音包、0 条短信、`viceCardLits`。`web_disk.json` 包含普通会员、已用 `78.5M`、总量 `60G`。

在 `tests/test_unicom_web_detail.py` 断言：

```python
def test_parse_web_detail_normalizes_allowances_and_members() -> None:
    payload = load_fixture("web_detail.json")
    data = parse_web_allowances(payload, AllowanceCategory.DATA)
    voice = parse_web_allowances(payload, AllowanceCategory.VOICE)
    lines = parse_web_lines(payload)

    assert [item.total for item in data] == [90 * 1024**3, 10 * 1024**3]
    assert sum(item.used or 0 for item in data) == int(Decimal("6.40") * 1024**3)
    assert [item.total for item in voice] == [200 * 60, 800 * 60]
    assert lines[0].phone_masked == "138****8000"
    assert lines[0].role is LineRole.PRIMARY
    assert lines[1].phone_masked == "138****8001"
    assert lines[1].role is LineRole.SECONDARY


def test_parse_web_disk_normalizes_capacity() -> None:
    resources = parse_web_resources(load_fixture("web_disk.json"))
    assert resources[0].name == "联通云盘"
    assert resources[0].tier == "普通会员"
    assert resources[0].used == int(Decimal("78.5") * 1024**2)
    assert resources[0].total == 60 * 1024**3
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv312/bin/python -m pytest tests/test_unicom_web_detail.py -q`

Expected: FAIL，`china_unicom_web_detail` 不存在。

- [ ] **Step 3: 实现最小解析器**

实现 `parse_web_allowances(payload: Mapping[str, object], category: AllowanceCategory) -> tuple[Allowance, ...]`、`parse_web_lines(payload: Mapping[str, object]) -> tuple[LineUsage, ...]` 和 `parse_web_resources(payload: Mapping[str, object]) -> tuple[ResourceUsage, ...]`，并遵循以下规则：

- 流量从 `resources`、`unshared`、`MlResources`、`TwResources`、`RzbResources`、`XsbResources` 的 `details` 读取。
- 语音从 `voiceSumresource`、`unshared_userVoice` 的 `details` 读取。
- 短信从 `smsSumresource`、`unshared_usersms` 的 `details` 读取。
- `total`、`use`、`remain` 按类别转换单位；负数归零；缺失保持 `None`。
- `share`/共享属性写入 `raw_type`，未知资源类别使用 `AllowanceScope.OTHER`。
- `viceCardlist` 或顶层 `viceCardLits` 中 `currentLoginFlag == "1"` 为主卡，其他为副卡；号码先调用 `mask_phone`。
- 云盘解析兼容 `M`、`MB`、`G`、`GB`，未知单位抛出 `UpstreamChangedError`。

- [ ] **Step 4: 运行解析测试并确认 GREEN**

Run: `.venv312/bin/python -m pytest tests/test_unicom_web_detail.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add carrier_usage/providers/china_unicom_web_detail.py tests/fixtures/unicom/web_detail.json tests/fixtures/unicom/web_disk.json tests/test_unicom_web_detail.py
git commit -m "feat: parse Unicom web usage details"
```

### Task 3：扩展 Provider 协议并接入网页明细接口

**Files:**
- Modify: `carrier_usage/models.py`
- Modify: `carrier_usage/providers/base.py`
- Modify: `carrier_usage/providers/china_unicom_web.py`
- Modify: `tests/provider_contract.py`
- Modify: `tests/test_unicom_web_provider.py`

**Interfaces:**
- Produces capability values `MEMBERS`、`RESOURCES`。
- Produces Provider 方法 `get_lines() -> tuple[LineUsage, ...]`、`get_resources() -> tuple[ResourceUsage, ...]`。
- Uses endpoint `https://mxx.client.10010.com/servicequerybusiness/operationservice/queryOcsPackageFlowLeftContentRevisedInJune`。
- Uses endpoint `https://mxx.client.10010.com/servicequerybusiness/operationservice/remainingQueryWebDiskTab`。

- [ ] **Step 1: 写 Provider 失败测试**

在 `tests/test_unicom_web_provider.py` 使用 respx 模拟两个接口，断言请求为 POST、表单包含 `version=WT`，并断言：

```python
assert Capability.MEMBERS in provider.capabilities()
assert Capability.RESOURCES in provider.capabilities()
assert (await provider.get_account()).loyalty_points == 922
assert (await provider.get_allowances())[0].total == 90 * 1024**3
assert (await provider.get_lines())[0].phone_masked == "138****8000"
assert (await provider.get_resources())[0].name == "联通云盘"
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv312/bin/python -m pytest tests/test_unicom_web_provider.py tests/provider_contract.py -q`

Expected: FAIL，缺少能力、方法或接口请求。

- [ ] **Step 3: 扩展协议和 Provider**

在 `Capability` 增加 `MEMBERS`、`RESOURCES`；在 `CarrierProvider` 增加异步协议方法 `get_lines(self) -> tuple[LineUsage, ...]` 和 `get_resources(self) -> tuple[ResourceUsage, ...]`。

在 `ChinaUnicomWebProvider` 增加明细和云盘 payload 缓存，所有明细 POST 使用：

```python
headers = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://imgxx.client.10010.com/yuliangchaxunsfwt/index.html#/",
}
data = {"version": "WT"}
```

验证响应为字典且 `code == "0000"`；`999999` 或非字典响应视为认证失效。让 `get_allowances()` 优先返回明细解析结果，并保留首页汇总作为只有 `overview` 时的轻量路径。

首页汇总中的“可用积分”转换为 `AccountSnapshot.loyalty_points`；字段缺失时保持 `None`。

为旧 `ChinaUnicomProvider` 实现返回空元组的 `get_lines()` 和 `get_resources()`，避免破坏协议。

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: `.venv312/bin/python -m pytest tests/test_unicom_web_provider.py tests/test_unicom_http.py tests/provider_contract.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add carrier_usage/models.py carrier_usage/providers/base.py carrier_usage/providers/china_unicom.py carrier_usage/providers/china_unicom_web.py tests/provider_contract.py tests/test_unicom_web_provider.py tests/test_unicom_http.py
git commit -m "feat: query Unicom web detail endpoints"
```

### Task 4：按查询范围编排并保留部分结果

**Files:**
- Modify: `carrier_usage/service.py`
- Modify: `tests/test_service.py`

**Interfaces:**
- Consumes: `query_snapshot(provider, now, scope: QueryScope = QueryScope.OVERVIEW)`。
- Produces: 按 scope 填充的 `CarrierSnapshot`，非核心失败写入 `warnings`。

- [ ] **Step 1: 写查询范围失败测试**

在 `tests/test_service.py` 增加带调用计数的 Provider，验证：

```python
snapshot = await query_snapshot(provider, now, QueryScope.MEMBERS)
assert provider.calls == {"account", "lines"}
assert snapshot.allowances == ()
assert snapshot.lines[0].phone_masked == "138****8001"
```

再增加资源接口抛出 `NetworkError` 的测试：`QueryScope.ALL` 仍返回账户和余量，`warnings` 包含“其他资源查询失败”。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv312/bin/python -m pytest tests/test_service.py -q`

Expected: FAIL，`query_snapshot` 不接受 scope 或非核心异常导致整体失败。

- [ ] **Step 3: 实现最小编排**

将 `query_snapshot` 签名改为：

```python
async def query_snapshot(
    provider: CarrierProvider,
    now: datetime,
    scope: QueryScope = QueryScope.OVERVIEW,
) -> CarrierSnapshot:
```

规则：

- 所有范围都认证并查询账户；`overview` 查询首页余量和套餐。
- `data`、`voice`、`sms` 查询明细余量后只保留相应类别。
- `members` 仅额外调用 `get_lines()`。
- `resources` 仅额外调用 `get_resources()`。
- `all` 调用所有已声明能力。
- 账户和认证失败为致命错误；成员、资源及单类明细失败转换为中文 warning。

- [ ] **Step 4: 运行服务测试并确认 GREEN**

Run: `.venv312/bin/python -m pytest tests/test_service.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add carrier_usage/service.py tests/test_service.py
git commit -m "feat: orchestrate scoped carrier queries"
```

### Task 5：输出成员、云盘和分类明细

**Files:**
- Modify: `carrier_usage/render.py`
- Modify: `tests/test_render.py`

**Interfaces:**
- Consumes: `CarrierSnapshot.lines`、`CarrierSnapshot.resources`。
- Produces: 稳定 JSON 字段 `lines`、`resources` 和中文摘要。

- [ ] **Step 1: 写输出失败测试**

构造含主副卡与云盘的 snapshot，断言：

```python
payload = snapshot_to_dict(snapshot)
assert payload["lines"][0]["phone_masked"] == "138****8000"
assert payload["resources"][0]["used"] == str(80 * 1024**2)
assert payload["account"]["loyalty_points"] == "922"
summary = render_summary(snapshot)
assert "可用积分：922" in summary
assert "副卡 138****8001" in summary
assert "联通云盘：普通会员" in summary
assert "13800138001" not in summary
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv312/bin/python -m pytest tests/test_render.py -q`

Expected: FAIL，缺少 `lines` 或 `resources` 输出。

- [ ] **Step 3: 实现 JSON 和中文摘要**

- JSON 的 `lines[].allowances` 复用 `_allowance_dict`。
- JSON 容量继续使用十进制字符串，避免跨语言整数精度问题。
- 中文摘要按“账户 → 套餐 → 余量 → 成员 → 其他资源 → 提示”排序。
- 成员标题使用“主卡/副卡/成员/未知成员 + 脱敏号码”。
- 云盘容量使用 GB/MB 自适应格式，不显示购买或跳转入口。

- [ ] **Step 4: 运行输出测试并确认 GREEN**

Run: `.venv312/bin/python -m pytest tests/test_render.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add carrier_usage/render.py tests/test_render.py
git commit -m "feat: render member and resource usage"
```

### Task 6：为 CLI 增加查询范围

**Files:**
- Modify: `carrier_usage/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `query --scope {overview,data,voice,sms,members,resources,all}`。
- Consumes: `QueryScope(args.scope)` 并传给 `query_snapshot`。

- [ ] **Step 1: 写 CLI 失败测试**

增加参数解析与调用测试：

```python
args = _parser().parse_args([
    "query", "--provider", "china_unicom", "--scope", "members"
])
assert args.scope == "members"
```

再验证无 `--scope` 时为 `overview`，非法值由 argparse 拒绝。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv312/bin/python -m pytest tests/test_cli.py -q`

Expected: FAIL，`--scope` 未定义。

- [ ] **Step 3: 实现参数传递**

在 query 子命令增加：

```python
query.add_argument(
    "--scope",
    choices=tuple(item.value for item in QueryScope),
    default=QueryScope.OVERVIEW.value,
    help="查询范围：概览、流量、语音、短信、成员、其他资源或全部",
)
```

调用 `query_snapshot(provider, now, QueryScope(args.scope))`。`doctor` 和 `login` 行为不变。

- [ ] **Step 4: 运行 CLI 测试并确认 GREEN**

Run: `.venv312/bin/python -m pytest tests/test_cli.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add carrier_usage/cli.py tests/test_cli.py
git commit -m "feat: add scoped usage queries to CLI"
```

### Task 7：更新中文 Skill 触发词和开源文档

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `agents/openai.yaml`

**Interfaces:**
- Produces: Agent 对中文账户、流量、语音、短信、成员、副卡、云盘和套餐意图的发现与 CLI 映射。

- [ ] **Step 1: 建立文档验收检查**

执行以下命令并记录当前缺失项：

```bash
rg -n "成员流量|副卡用量|云盘|--scope" SKILL.md README.md agents/openai.yaml
```

Expected: 至少一个关键词或 `--scope` 缺失，检查不满足设计。

- [ ] **Step 2: 更新 Skill 元数据和正文**

将 description 保持为触发条件并覆盖：余额、话费、积分、套餐、流量明细、语音、短信、成员/主副卡和联通云盘。正文加入意图映射表及命令：

```bash
python3 scripts/carrier_usage.py query --provider china_unicom --scope data --format summary
python3 scripts/carrier_usage.py query --provider china_unicom --scope members --format summary
python3 scripts/carrier_usage.py query --provider china_unicom --scope resources --format summary
```

明确普通概览不展开成员，完整查询使用 `--scope all`。

- [ ] **Step 3: 更新 README 和 UI 元数据**

README 增加中文能力表、范围表、脱敏成员示例和会话失效处理。`agents/openai.yaml` 的 `short_description` 覆盖明细和成员查询，`default_prompt` 使用中文概览请求。

- [ ] **Step 4: 验证 Skill 与文档关键词**

Run: `.venv312/bin/python /Users/weieast/.codex/skills/.system/skill-creator/scripts/quick_validate.py .`

Run: `rg -n "成员流量|副卡用量|联通云盘|--scope" SKILL.md README.md agents/openai.yaml`

Expected: Skill is valid，且每类关键词都有明确触发或说明。

- [ ] **Step 5: 提交**

```bash
git add SKILL.md README.md agents/openai.yaml
git commit -m "docs: add Chinese detail query triggers"
```

### Task 8：完整回归与真实只读验收

**Files:**
- Modify only if verification exposes a defect; follow a new RED/GREEN cycle before each fix.

**Interfaces:**
- Verifies the complete distributable Skill.

- [ ] **Step 1: 运行完整自动化测试**

Run: `.venv312/bin/python -m pytest -q`

Expected: 全部测试 PASS，0 failures。

- [ ] **Step 2: 运行静态与格式检查**

```bash
.venv312/bin/python -m ruff check carrier_usage scripts tests
.venv312/bin/python -m ruff format --check carrier_usage scripts tests
.venv312/bin/python -m mypy carrier_usage
```

Expected: 三项均退出码 0。

- [ ] **Step 3: 运行 Skill 校验和打包**

```bash
.venv312/bin/python /Users/weieast/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
.venv312/bin/python -m build
```

Expected: `Skill is valid!`，并成功生成 sdist 与 wheel。

- [ ] **Step 4: 使用本人扫码会话执行真实只读验收**

按刷新限制顺序执行：

```bash
.venv312/bin/python scripts/carrier_usage.py query --provider china_unicom --scope data --format summary
.venv312/bin/python scripts/carrier_usage.py query --provider china_unicom --scope members --format summary
.venv312/bin/python scripts/carrier_usage.py query --provider china_unicom --scope resources --format summary
```

若刷新保护阻止连续查询，使用一次 `--scope all` 代替三次请求。验收只记录“成功/失败”和脱敏摘要，不保存 JSON 原始响应。

Expected: 返回流量包、脱敏主副卡和云盘数据；输出不含完整手机号或凭据。

- [ ] **Step 5: 检查仓库敏感信息和提交状态**

```bash
git diff --check
git status --short
rg -n "13800138000|SESSION|private" . --glob '!tests/fixtures/**' --glob '!docs/superpowers/**'
```

Expected: diff 无空白错误；工作树只包含预期变更；生产文件无测试手机号和测试 Cookie。

- [ ] **Step 6: 提交验收中产生的必要修复**

只有存在经测试驱动修复的变更时执行：

```bash
git add carrier_usage tests SKILL.md README.md agents/openai.yaml
git commit -m "fix: harden Unicom detail queries"
```
