<p align="center">
  <img src="assets/logo.png" alt="运营商用量查询 Skill Logo" width="180">
</p>

<h1 align="center">运营商用量查询 Skill</h1>

一个以中文为主、可扩展的 Agent Skill，用于安全查询本人或已获授权的中国运营商剩余话费、月账单、套餐余量、积分、套餐资费、流量/语音/短信明细、成员/副卡用量和联通云盘空间。

首个版本实现中国联通。核心层通过 Provider 协议隔离运营商差异，后续可以增加中国移动、中国电信和中国广电，而不改变 CLI 和统一 JSON Schema。

> [!WARNING]
> 本项目是非官方开源项目，与中国联通及其他运营商不存在隶属、授权或背书关系。联通 Provider 使用普通用户可访问的营业厅能力，接口可能随时变化。请遵守运营商服务条款，只查询本人或明确授权的账户。

## 仓库结构

本仓库外层是 git 项目，真正的 Skill 包位于二级文件夹 `carrier-usage-skill/`，遵循 SkillHub 标准布局：

```
carrier-usage-skill/            # 仓库根（git 项目）
├── README.md                   # 本文件
├── LICENSE
├── .github/workflows/          # ci.yml / publish.yml
├── assets/                     # 资源文件（logo 等）
├── docs/                       # 项目级设计/规划文档
├── scripts/                    # 仓库级脚本（发布等）
└── carrier-usage-skill/        # 二级文件夹 = Skill 包（含 pyproject.toml）
    ├── SKILL.md                # 必需：YAML 元数据 + Markdown 指令
    ├── pyproject.toml          # 包配置（在 Skill 包内）
    ├── README.md               # 包内说明（链接回本文件）
    ├── carrier_usage/          # 源码包
    ├── scripts/                # 可执行脚本
    ├── references/             # 按需加载的参考文档
    └── tests/                  # 测试
```

发布、安装与开发命令都需在 `carrier-usage-skill/` 二级文件夹内执行（详见下文）。

## 当前状态

版本：`0.4.1`（实验性）

### 版本说明

- **0.4.0**：补齐中国联通只读查询能力——新增交费记录（`payments`）、电子发票（`invoices`）、返费与赠款（`rebates`）、金融合约账单（`contract-bills`）以及需短信二次认证的详单查询（`usage-details`）；完善多账户与默认卡管理。
- **0.4.1**：重组仓库为标准 SkillHub 布局（外层 git 项目 + 嵌套 `carrier-usage-skill/` Skill 包），并加入上游限流识别与指数退避重试。
- **0.4.2**：联通接口层限流识别与指数退避重试正式发布。
- **0.4.3**：新增 `scripts/publish_skill.sh` 发布脚本，发布前自动排除 `.venv`/缓存等超大目录，避免 skillhub CLI 打包失败。
- **0.4.4**：新增 `.github/workflows/publish.yml`，推送 `v*` tag 时自动发布到 SkillHub（校验 tag 与版本一致），并补充 README 发布流程章节。

| 运营商 | 话费/账单 | 用量明细 | 成员/副卡 | 其他资源 | 状态 |
|---|---:|---:|---:|---:|---|
| 中国联通 | 剩余话费、月账单、交费记录、电子发票、返费赠款、金融合约账单 | 余量、流量、语音、短信；详单需二次认证 | 支持，号码脱敏 | 联通云盘 | 官方 APP 扫码登录；已通过本人账户验证 |
| 中国移动 | 不支持 | 不支持 | 不支持 | 不支持 | 已规划 |
| 中国电信 | 不支持 | 不支持 | 不支持 | 不支持 | 已规划 |
| 中国广电 | 不支持 | 不支持 | 不支持 | 不支持 | 已规划 |

## 多账户与默认卡

首次扫码绑定时设置中文别名：

```bash
carrier-usage login --provider china_unicom --alias "工作联通" --default
```

技能同时维护全局默认和各运营商默认。“查流量”使用全局默认，“查联通流量”使用联通默认；明确说“查工作联通流量”时使用别名选择。只有无法唯一确定账户时才展示脱敏选项。

```bash
carrier-usage accounts list
carrier-usage accounts rename "工作联通" "办公联通"
carrier-usage accounts set-default "办公联通"
carrier-usage accounts set-provider-default "办公联通"
carrier-usage query --account "办公联通" --scope data --format json
```

成员卡和副卡从属于登录主账户，默认支持查询其用量，不需要重复绑定。旧版单账户会话首次使用时会自动导入为“我的联通”，并保留原会话文件。

## 安全边界

- 只查询用户本人或明确授权的账户。
- 不实现充值、缴费、套餐变更、退订或批量号码查询。
- 不绕过验证码、设备验证、风控或实名认证。
- 不通过聊天、普通命令行参数或 issue 接收短信验证码、ticket、Cookie、token、完整手机号或原始接口响应。
- 默认遮蔽手机号；日志和错误会过滤常见认证字段。
- 真实凭据不得提交到 Git，真实响应不得用作测试 fixture。

## 环境要求

- Python 3.11、3.12 或 3.13
- 可访问中国联通相关 HTTPS 接口的网络
- 已安装并登录“中国联通”APP（推荐用于扫码）

## 安装

仓库根目录是 git 项目，真正的 Skill 包在 `carrier-usage-skill/` 二级文件夹。进入该文件夹安装开发版本：

```bash
cd carrier-usage-skill
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

如需使用推荐的官方 APP 扫码登录，同时安装浏览器组件：

```bash
.venv/bin/python -m pip install -e '.[web-login]'
.venv/bin/playwright install chromium
```

安装开发和测试依赖：

```bash
.venv/bin/python -m pip install -e '.[dev]'
```

SkillHub 已收录本 Skill：[运营商流量与资费查询](https://skillhub.cn/skills/user_639ac3ba/query-carrier-usage)。可将以下提示词发送给支持 Agent Skills 的 AI 助手进行安装：

```text
请根据 https://skillhub.cn/install/skillhub.md，安装 query-carrier-usage。
```

skills.sh 尚未收录，后续补充对应链接。

## 登录中国联通

推荐使用中国联通 APP 扫描官方网页二维码登录：

```bash
cd carrier-usage-skill
python3 scripts/carrier_usage.py login --provider china_unicom --alias "我的联通"
```

程序会打开一个独立浏览器窗口。在页面点击“请登录”，选择扫码方式，然后使用已登录的“中国联通”APP 扫码确认。二维码、授权和风控均由中国联通处理，本项目不获取手机号或验证码。登录成功后回到终端按回车，会话保存在：

```text
~/.local/share/carrier-usage/sessions/<account-id>.json
```

会话文件权限为 `0600`，包含敏感认证信息，不要查看、复制、上传或提交到 Git。需要退出时直接删除该文件；需要续期时重新运行 `login`。

## 使用

查看 Provider 能力：

```bash
cd carrier-usage-skill
python3 scripts/carrier_usage.py capabilities --provider china_unicom
```

检查配置和认证：

```bash
cd carrier-usage-skill
python3 scripts/carrier_usage.py doctor --provider china_unicom
```

### 基础只读查询

查询剩余话费（包括上月结转、本月存入和本月已消费）：

```bash
cd carrier-usage-skill
python3 scripts/carrier_usage.py balance --account "我的联通" --format json
```

进行余量查询，获取流量、语音和短信套餐余量：

```bash
python3 scripts/carrier_usage.py allowances --account "我的联通" --detail --format json
```

查询指定月份的我的账单：

```bash
python3 scripts/carrier_usage.py bills --account "我的联通" --month 2026-08 --format json
```

查询交费记录、已有电子发票、返费与赠款和金融合约账单：

```bash
python3 scripts/carrier_usage.py payments --account "我的联通" --from 2026-01 --to 2026-08 --format json
python3 scripts/carrier_usage.py invoices --account "我的联通" --month 2026-08 --format json
python3 scripts/carrier_usage.py rebates --account "我的联通" --format json
python3 scripts/carrier_usage.py contract-bills --account "我的联通" --month 2026-08 --format json
```

详单查询涉及对端号码和通信行为，联通官方页面要求短信二次认证：

```bash
python3 scripts/carrier_usage.py usage-details --account "我的联通" --category data --month 2026-08 --format json
```

该命令不会自动发送或接收验证码，而是返回官方认证页面。用户完成认证前，Skill 不查询详单。

这些命令只读取联通官方网页数据，不会发起缴费、办理业务、申请或下载发票。金额在 JSON 中使用十进制字符串，所有结果都有账户别名和查询时间，可供 Agent 稳定调用。

### 综合查询

生成中文摘要：

```bash
cd carrier-usage-skill
python3 scripts/carrier_usage.py query --provider china_unicom --format summary
```

生成统一 JSON：

```bash
cd carrier-usage-skill
python3 scripts/carrier_usage.py query --provider china_unicom --format json
```

按查询意图选择范围：

| 范围 | 适用说法 | 命令示例 |
|---|---|---|
| `overview` | 查余额、积分、套餐或账户概览 | `query --scope overview` |
| `data` | 查流量、流量包或流量明细 | `query --scope data` |
| `voice` | 查语音余量或通话分钟 | `query --scope voice` |
| `sms` | 查短信余量 | `query --scope sms` |
| `members` | 查成员流量、查副卡用量或查主副卡 | `query --scope members` |
| `resources` | 查联通云盘空间 | `query --scope resources` |
| `all` | 查全部用量或完整余量 | `query --scope all` |

普通概览不会展开成员信息。成员查询会显示“主卡/副卡 + 脱敏号码”，不会显示完整手机号。

示例摘要：

```text
运营商账户：138****8000
账户余额：42.15 元
本月实时话费：19.00 元
当前套餐：示例套餐（29.00 元/月）
通用流量：已用 3.00 GB，剩余 7.00 GB
副卡 138****8001：
  测试语音包：已用 1 分钟
联通云盘：普通会员，已用 80.00 MB，总空间 60.00 GB
```

金额使用十进制字符串；流量在 JSON 中统一为 byte，语音统一为 second，短信统一为 count。手机号始终以遮蔽形式输出。

## 错误与恢复

| 退出码 | 含义 | 建议 |
|---:|---|---|
| 2 | 配置错误 | 检查环境变量、TOML 格式和 `0600` 权限 |
| 3 | 认证失败或用户取消 | 重新运行 `login` 并使用中国联通 APP 扫码 |
| 4 | 查询过快或上游限流 | 按提示等待后重试 |
| 5 | 上游响应结构变化 | 停止猜测字段，提交完全脱敏的 issue |
| 6 | 网络、DNS、TLS 或超时 | 检查网络环境后重试 |
| 7 | Provider 或能力不支持 | 查看 `capabilities` 输出 |

## 架构与扩展

新增运营商应实现 `carrier_usage.providers.base.CarrierProvider`，通过 `capabilities()` 声明真实能力，并把运营商原始字段映射为 `CarrierSnapshot`。不得为缺失能力伪造数据。

每个新 Provider 必须通过公共契约测试、脱敏测试、模拟 HTTP 测试和本地授权账户验证。若未来存在正式开放 API，应优先实现官方认证后端。

## 开发与验证

先进入 Skill 包目录：

```bash
cd carrier-usage-skill
.venv/bin/python -m ruff check carrier_usage scripts tests
.venv/bin/python -m ruff format --check carrier_usage scripts tests
.venv/bin/python -m mypy carrier_usage
.venv/bin/python -m pytest -v
.venv/bin/python -m build
.venv/bin/python -m pip_audit
```

提交 issue 前必须删除手机号、ticket、Cookie、token、认证请求头和原始运营商响应。安全问题请不要公开披露敏感样本；先使用 GitHub Security Advisory 私下报告。

## 发布流程

发布目标是 SkillHub。核心约束：skillhub CLI **不会读取 `.gitignore`**，会把 `.venv`（数百 MB）和各类缓存目录一并打包，导致上传失败。因此统一通过发布脚本发布，脚本会先把 Skill 包复制到一个临时目录并排除 `.venv`、`.env`、`.mypy_cache`、`.pytest_cache`、`.ruff_cache`、`__pycache__`、`*.egg-info` 等后发布，发布后自动清理。

### 本地发布

```bash
# 1. 更新 carrier-usage-skill/SKILL.md 的 version 字段到新版本（如 0.4.4）
# 2. 在 CHANGELOG.md 增补该版本的说明段落（## X.Y.Z - 日期）
# 3. 提交并推送
git commit -am "Release 0.4.4: ..." && git push
# 4. 用发布脚本发布（版本说明自动提取，无需手写）
bash scripts/publish_skill.sh
```

发布脚本的版本说明（`--changelog`）缺省时按以下优先级自动提取真实说明：

1. git tag 的 annotation message（建议打 annotated tag：`git tag -a v0.4.4 -m "0.4.4: ..."`）；
2. 仓库根 `CHANGELOG.md` 中 `## 0.4.4` 对应段落；
3. 兜底占位文本。

发布脚本还支持 `--changelog "自定义说明"`（覆盖自动提取）、`--version-check`（仅检查 SKILL.md 版本）和 `--dry-run`（仅预览将要打包的目录，不真正发布）。

### 自动发布（推荐）

项目配置了 `.github/workflows/publish.yml`：推送形如 `v0.4.4` 的 tag 时，GitHub Actions 会自动安装 skillhub CLI、用 `SKILLHUB_TOKEN` 登录、校验 tag 与 `SKILL.md` 的 `version` 一致后发布，**版本说明由脚本自动提取**（优先 tag annotation，其次 `CHANGELOG.md`）。**前提**是在仓库 `Settings → Secrets and variables → Actions` 中添加名为 `SKILLHUB_TOKEN` 的密钥（值为 `skillhub login --key` 所用的登录密钥）。

标准发布步骤：

```bash
# 1. 本地更新 SKILL.md 的 version、在 CHANGELOG.md 增补说明并提交推送
# 2. 打 annotated tag（tag 名去掉 v 前缀后等于 SKILL.md 的 version）
git tag -a v0.4.4 -m "0.4.4: 本次真实版本说明"
git push origin v0.4.4
# 3. 等待 Actions 工作流完成自动发布
```

若 tag 与 `SKILL.md` 版本不一致，工作流会在校验步骤直接失败，不会发布错误版本。

## 许可证与来源说明

原创代码采用 [Apache License 2.0](LICENSE)。项目参考公开实现的接口行为进行独立实现，没有复制 GPL 项目的源码或文档。

## English summary

`carrier-usage-skill` is an experimental, provider-neutral Agent Skill for securely querying an authorized user's carrier account. Version 0.4.1 reorganizes the repository into a standard SkillHub layout (outer git project with a nested `carrier-usage-skill/` skill package containing SKILL.md, scripts/, and references/; shared resources such as the logo live in the root `assets/` directory), while usage details require official SMS secondary authentication. Credentials stay local, identifiers are redacted, and write operations are intentionally out of scope.
