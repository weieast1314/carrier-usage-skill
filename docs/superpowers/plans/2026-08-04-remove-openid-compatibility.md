# 移除 OpenID 兼容登录实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除中国联通 OpenID 兼容登录的全部可执行能力和文档入口，使官方 APP 扫码会话成为唯一认证方式，并发布 `0.1.1`。

**Architecture:** 保留 `china_unicom.py` 中被网页 Provider 复用的纯解析函数，删除其中的小程序认证 Provider 和专属 HTTP 辅助逻辑。配置层只解析会话路径，注册层只构造 `ChinaUnicomWebProvider`，CLI 错误边界只做通用脱敏。

**Tech Stack:** Python 3.11–3.13、httpx、pytest、respx、Ruff、mypy、Hatchling、Agent Skills `SKILL.md`。

## Global Constraints

- 中国联通唯一认证方式是“中国联通”APP 扫描官方网页二维码。
- 不保留隐藏、未导出或不可达的 OpenID Provider 代码。
- `carrier_usage.redaction` 必须继续过滤 `openid` 和 `openId` 键名。
- 删除两份 2026-08-03 扫码迁移历史文档。
- 用户文档优先使用中文。
- 发布版本固定为 `0.1.1`，SkillHub Slug 保持 `query-carrier-usage`。

---

### Task 1：配置只接受扫码会话

**Files:**
- Modify: `tests/test_config.py`
- Modify: `tests/test_provider_registry.py`
- Modify: `carrier_usage/config.py`
- Modify: `carrier_usage/providers/__init__.py`

**Interfaces:**
- Produces: `AppConfig(provider: str, min_refresh_seconds: int, unicom_session_path: Path | None = None)`。
- Produces: `create_china_unicom_provider(config, client) -> ChinaUnicomWebProvider`。

- [ ] **Step 1: 改写配置与注册失败测试**

将测试改为期望配置模型不含 OpenID，旧环境变量不能代替会话，并且注册器始终返回网页 Provider：

```python
def test_legacy_openid_does_not_replace_login_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    with pytest.raises(ConfigurationError, match="请先运行 login 命令扫码登录"):
        load_config({"CARRIER_USAGE_UNICOM_OPENID": "legacy-id"}, None)


def test_accepts_explicit_unicom_session_path(tmp_path: Path) -> None:
    session_path = tmp_path / "session.json"
    config = load_config({"CARRIER_USAGE_UNICOM_SESSION": str(session_path)}, None)
    assert config == AppConfig("china_unicom", 300, session_path)
    assert not hasattr(config, "unicom_openid")
```

在 `tests/test_provider_registry.py` 使用显式会话路径构造 `AppConfig`，并断言 `create_provider("china_unicom", config, client)` 是 `ChinaUnicomWebProvider`。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv312/bin/python -m pytest tests/test_config.py tests/test_provider_registry.py -q`

Expected: FAIL，原因是 `AppConfig` 仍含 `unicom_openid`，旧环境变量仍能启用兼容配置。

- [ ] **Step 3: 最小化配置和 Provider 注册**

把配置模型改为：

```python
@dataclass(frozen=True, slots=True)
class AppConfig:
    provider: str
    min_refresh_seconds: int
    unicom_session_path: Path | None = None
```

删除 OpenID 环境变量/TOML 读取和相关条件分支。联通配置只有在显式会话路径或默认会话文件存在时成功。

把注册入口改为只导入和注册 `ChinaUnicomWebProvider`：

```python
def create_china_unicom_provider(
    config: AppConfig, client: httpx.AsyncClient
) -> ChinaUnicomWebProvider:
    return ChinaUnicomWebProvider(config, client)


register_provider(ChinaUnicomWebProvider.provider_id, create_china_unicom_provider)
__all__ = ["ChinaUnicomWebProvider"]
```

- [ ] **Step 4: 运行目标测试并确认 GREEN**

Run: `.venv312/bin/python -m pytest tests/test_config.py tests/test_provider_registry.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add carrier_usage/config.py carrier_usage/providers/__init__.py tests/test_config.py tests/test_provider_registry.py
git commit -m "refactor: require Unicom QR sessions"
```

### Task 2：删除小程序 OpenID Provider

**Files:**
- Modify: `carrier_usage/providers/china_unicom.py`
- Delete: `tests/test_unicom_http.py`
- Modify: all tests constructing `AppConfig`

**Interfaces:**
- Preserves: `parse_account`、`parse_allowances`、`parse_plan`、`extract_phone` and other pure parser helpers imported by `china_unicom_web.py` and `china_unicom_web_detail.py`。
- Removes: `ChinaUnicomProvider`、`UnicomAuthSession` and OpenID-specific endpoint constants/helpers。

- [ ] **Step 1: 更新使用新配置接口的测试并记录旧 Provider 基线**

将全库 `AppConfig` 构造改为新签名。运行 `rg -n "ChinaUnicomProvider|UnicomAuthSession|OPENID|openid" carrier_usage/providers`，确认删除前可以发现旧 Provider 实现。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv312/bin/python -m pytest tests/test_provider_registry.py tests/test_unicom_web_provider.py -q`

Expected: 新签名测试在生产代码改造完成前 FAIL；静态基线命令输出旧 Provider 位置。

- [ ] **Step 3: 删除旧 Provider，保留纯解析代码**

从 `carrier_usage/providers/china_unicom.py` 删除：

- `ChinaUnicomProvider`
- `UnicomAuthSession`
- ticket、微信小程序和旧手机营业厅专属 URL 常量
- `_required_cookies` 及仅被旧 Provider 调用的请求辅助代码
- 因上述删除而不再使用的 `asyncio`、`time`、`httpx`、认证错误和网络错误导入

保留网页 Provider 当前导入的所有解析函数，并用 `rg` 确认每个剩余私有辅助函数仍有调用者。

删除 `tests/test_unicom_http.py`；该文件只验证已删除的旧 Provider。修改其他测试的 `AppConfig` 位置参数为关键字参数，避免字段顺序耦合。

- [ ] **Step 4: 运行 Provider 和解析测试并确认 GREEN**

Run: `.venv312/bin/python -m pytest tests/test_provider_registry.py tests/test_unicom_parser.py tests/test_unicom_web_provider.py tests/test_unicom_web_detail.py -q`

Expected: PASS。

Run: `rg -n "ChinaUnicomProvider|UnicomAuthSession|OPENID|openid" carrier_usage/providers`

Expected: 无输出。

- [ ] **Step 5: 提交**

```bash
git add -A carrier_usage/providers tests
git commit -m "refactor: remove Unicom OpenID provider"
```

### Task 3：删除 CLI 和示例配置中的兼容入口

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `carrier_usage/cli.py`
- Modify: `examples/config.example.toml`

**Interfaces:**
- Preserves: `login`、`doctor`、`query`、`capabilities` CLI 命令。
- Removes: 对 `CARRIER_USAGE_UNICOM_OPENID` 的全部读取。

- [ ] **Step 1: 编写 CLI 失败测试**

将扫码测试改名为 `test_login_saves_to_requested_path`，删除环境变量清理。把无会话错误测试改为即使存在旧环境变量也拒绝查询：

```python
monkeypatch.setenv("CARRIER_USAGE_UNICOM_OPENID", "legacy-id")
exit_code = main(["doctor", "--provider", "china_unicom"])
assert exit_code == 2
assert "请先运行 login 命令扫码登录" in capsys.readouterr().err
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv312/bin/python -m pytest tests/test_cli.py -q`

Expected: FAIL，因为旧环境变量仍会绕过“缺少扫码会话”的配置检查。

- [ ] **Step 3: 删除 CLI 兼容读取和示例字段**

异常处理只调用通用脱敏：

```python
except CarrierUsageError as error:
    print(redact_text(str(error)), file=sys.stderr)
    return error.exit_code
except Exception:
    if os.environ.get("CARRIER_USAGE_DEBUG") == "1":
        print(redact_text(traceback.format_exc()), file=sys.stderr)
```

如 `redact_text` 当前要求第二参数，则将其默认值设为空序列并补充单元测试。删除 `examples/config.example.toml` 的 `openid` 行，只保留 `session_path`。

- [ ] **Step 4: 运行 CLI 与脱敏测试并确认 GREEN**

Run: `.venv312/bin/python -m pytest tests/test_cli.py tests/test_redaction.py -q`

Expected: PASS，且 `tests/test_redaction.py` 继续证明 `openid/openId` 会被过滤。

- [ ] **Step 5: 提交**

```bash
git add carrier_usage/cli.py carrier_usage/redaction.py examples/config.example.toml tests/test_cli.py tests/test_redaction.py
git commit -m "refactor: remove legacy OpenID configuration"
```

### Task 4：删除文档表述和旧历史文档

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Delete: `docs/superpowers/specs/2026-08-03-unicom-web-sms-login-design.md`
- Delete: `docs/superpowers/plans/2026-08-03-unicom-web-sms-login.md`

**Interfaces:**
- Produces: 中文优先、只描述 APP 扫码认证的 Skill 与 README。
- Preserves: 通用脱敏模块中的敏感键名。

- [ ] **Step 1: 记录删除前静态基线**

Run: `rg -n -i "openid|CARRIER_USAGE_UNICOM_OPENID" SKILL.md README.md examples carrier_usage docs/superpowers/specs/2026-08-03-unicom-web-sms-login-design.md docs/superpowers/plans/2026-08-03-unicom-web-sms-login.md`

Expected: 输出当前兼容实现、配置和文档位置，证明清理检查能够发现旧内容。

- [ ] **Step 2: 运行测试并确认 RED**

本任务不新增文本契约单元测试；文档删除使用 Step 1 与 Step 4 的静态前后对比验收。

- [ ] **Step 3: 更新 Skill 和 README，删除历史文档**

从 `SKILL.md` 删除兼容配置步骤、能力表兼容说明、OpenID 恢复建议和 OpenID 安全条目。认证步骤只运行：

```bash
python3 scripts/carrier_usage.py login --provider china_unicom
```

从 `README.md` 删除整个“OpenID 兼容配置”章节以及错误恢复、安全边界和提交 Issue 提示中的 OpenID 字样。直接删除两份指定历史文档。

- [ ] **Step 4: 运行文档契约和 Skill 校验并确认 GREEN**

Run: `rg -n -i "openid|CARRIER_USAGE_UNICOM_OPENID" SKILL.md README.md examples carrier_usage/config.py carrier_usage/cli.py carrier_usage/providers/__init__.py carrier_usage/providers/china_unicom.py`

Expected: 无输出。

Run: `.venv312/bin/python /Users/weieast/.codex/skills/.system/skill-creator/scripts/quick_validate.py .`

Expected: PASS 且输出 `Skill is valid!`。

- [ ] **Step 5: 提交**

```bash
git add -A SKILL.md README.md docs
git commit -m "docs: remove OpenID compatibility guidance"
```

### Task 5：升级版本并完整验证

**Files:**
- Modify: `pyproject.toml`
- Generated: `dist/carrier_usage_skill-0.1.1.tar.gz`
- Generated: `dist/carrier_usage_skill-0.1.1-py3-none-any.whl`

**Interfaces:**
- Produces: Python package and Skill version `0.1.1`。

- [ ] **Step 1: 确认当前发布版本基线**

Run: `.venv312/bin/python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])'`

Expected: 输出 `0.1.0`。

- [ ] **Step 2: 将版本升级为 0.1.1**

把 `pyproject.toml` 的 `project.version` 改为 `0.1.1`。

- [ ] **Step 3: 运行全部验证和构建**

```bash
.venv312/bin/python -m pytest -q
.venv312/bin/ruff check carrier_usage scripts tests
.venv312/bin/ruff format --check carrier_usage scripts tests
.venv312/bin/mypy carrier_usage
.venv312/bin/python /Users/weieast/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
.venv312/bin/python -m build
git diff --check
```

Expected: 全部退出码为 0；构建产物文件名包含 `0.1.1`。

- [ ] **Step 4: 验证当前追踪文件边界**

Run: `rg -n -i "openid|CARRIER_USAGE_UNICOM_OPENID" . --glob '!dist/**' --glob '!*.egg-info/**' --glob '!carrier_usage/redaction.py' --glob '!tests/test_redaction.py' --glob '!docs/superpowers/specs/2026-08-04-remove-openid-compatibility-design.md' --glob '!docs/superpowers/plans/2026-08-04-remove-openid-compatibility.md'`

Expected: 无输出。允许当前移除规格/计划以及通用脱敏测试提到该敏感键名。

- [ ] **Step 5: 提交版本**

```bash
git add pyproject.toml
git commit -m "release: prepare v0.1.1"
```

### Task 6：发布 GitHub 与 SkillHub 0.1.1

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: clean `main` branch at version `0.1.1`。
- Produces: pushed GitHub commits, GitHub Release `v0.1.1`, SkillHub version `0.1.1` under Slug `query-carrier-usage`。

- [ ] **Step 1: 推送 main**

Run: `git push origin main`

Expected: `main -> main`，远端包含全部移除提交。

- [ ] **Step 2: 创建 GitHub Release**

```bash
gh release create v0.1.1 \
  dist/carrier_usage_skill-0.1.1.tar.gz \
  dist/carrier_usage_skill-0.1.1-py3-none-any.whl \
  --repo weieast1314/carrier-usage-skill \
  --title "v0.1.1：移除 OpenID 兼容登录" \
  --notes "移除微信小程序 OpenID Provider、配置入口和相关文档。中国联通现仅支持官方 APP 扫码登录与本地会话复用；通用敏感字段脱敏规则保持不变。"
```

Expected: 返回 `https://github.com/weieast1314/carrier-usage-skill/releases/tag/v0.1.1`。

- [ ] **Step 3: 更新 SkillHub**

在 SkillHub 的 `query-carrier-usage` 管理页通过已绑定 GitHub 仓库导入 `main` 根目录，版本填 `0.1.1`，显示名称保持“运营商流量与资费查询”，变更说明填：

```text
移除 OpenID 兼容登录实现与文档。中国联通现在仅支持官方 APP 扫码登录，会话凭据继续只保存在用户本机。
```

最终发布属于公开外部写操作，点击提交前再次向用户确认。

- [ ] **Step 4: 核对发布状态**

Expected: GitHub Release 为公开状态；SkillHub 显示 `0.1.1` 且进入安全审核，不再展示 OpenID 登录说明。
