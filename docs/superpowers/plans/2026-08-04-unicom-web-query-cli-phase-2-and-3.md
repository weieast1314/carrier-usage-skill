# 中国联通网页查询 CLI 第二、三期实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 `payments`、`invoices`、`rebates`、`contract-bills` 和 `usage-details` 五个只读 CLI，使 Agent 能查询联通历史财务记录，并在详单需要短信二次认证时安全引导用户。

**Architecture:** 扩展现有 `ChinaUnicomWebClient`、稳定业务模型和统一结果信封。可直接使用扫码 Cookie 的四项业务由官方网页接口返回并转换为脱敏模型；详单查询不触发验证码，在官方页面要求短信验证时返回专用认证错误。

**Tech Stack:** Python 3.11、httpx、dataclasses、Decimal、argparse、pytest、respx、mypy、Ruff。

## Global Constraints

- 所有新增能力只读，不发起缴费、再充值、开票、发票下载、邮件推送或账户变更。
- 只接受中国联通官方 `10010.com` 域名会话 Cookie。
- 不读取 Chrome Cookie、Local Storage、密码或验证码。
- 订单号、手机号、发票号码和详单对端号码输出前必须脱敏。
- 真实页面响应、真实号码、真实金额和认证信息不得进入 Git 或测试 fixture。
- 详单查询不自动发送短信；需要二次认证时返回退出码 3 和官方页面地址。
- 列表查询最多返回 100 条，并在截断时写入 `warnings`。
- 版本从 `0.3.0` 升级为 `0.4.0`。

## 已确认的联通官方契约

| 能力 | 方法与 URL | Referer |
|---|---|---|
| 交费记录 | `GET https://upay.10010.com/npfweb/NpfQueryWeb/feeSearch/queryOrderNew` | `https://upay.10010.com/upayWeb/home/feeSearch` |
| 电子发票列表 | `GET https://mxx.client.10010.com/serviceimportantbusiness/queryNew/einvoicelist.htm` | `https://imgxx.client.10010.com/dianzifapiaowt2024/index.html#/` |
| 赠款记录 | `POST https://mxx.client.10010.com/servicequerybusiness/grantsAndContractRebates/contractRebate` | `https://imgxx.client.10010.com/fanfeiyuzengkuan/index.html#/` |
| 合约返赠 | `POST https://mxx.client.10010.com/servicequerybusiness/rebatesAndGrants/queryDatas` | 同上 |
| 金融合约账单 | `POST https://m.client.10010.com/servicebusiness/query/queryFinancialCBDetail` | `https://img.client.10010.com/jinrongzhangdanwt/index.html#/` |
| 详单查询 | 官方页面要求短信二次认证 | `https://iservice.10010.com/e4/miniservice/query/detailQuery.html` |

---

### Task 1: 历史财务与敏感查询模型

**Files:**
- Modify: `carrier_usage/web_models.py`
- Test: `tests/test_web_models.py`

**Interfaces:**
- Produces: `PaymentRecord`、`InvoiceRecord`、`RebateRecord`、`ContractBillItem`、`ContractBill`、`UsageDetailResult`。
- Produces: `ListQueryResult(items, range_start, range_end, truncated, status)`。
- Produces: `parse_month_range(start, end)`，校验起止月份和最大 12 个月范围。

- [ ] **Step 1: 编写月份范围、不可变金额和脱敏字段失败测试**
- [ ] **Step 2: 运行 `pytest tests/test_web_models.py -v`，确认新增类型导入失败**
- [ ] **Step 3: 实现最小不可变模型和范围校验**
- [ ] **Step 4: 运行模型测试并确认通过**
- [ ] **Step 5: 提交模型变更**

### Task 2: 交费记录、发票、返费和金融账单解析

**Files:**
- Modify: `carrier_usage/providers/china_unicom_web_queries.py`
- Test: `tests/test_unicom_web_queries_phase_2.py`

**Interfaces:**
- Produces: `parse_payments(payload)`，兼容 `orderList` 字段并脱敏订单号、交费号码。
- Produces: `parse_invoices(payload)`，只保留已有发票的脱敏号码、金额、日期、类型和状态。
- Produces: `parse_rebates(payload, kind)`，兼容 JSON 字符串或列表形式的 `data`。
- Produces: `parse_contract_bill(payload, month)`，映射 `allfree` 和 `billinfos`。

- [ ] **Step 1: 使用完全人工数据编写四类解析失败测试**
- [ ] **Step 2: 运行定向测试并确认函数不存在**
- [ ] **Step 3: 实现金额、日期、列表和标识脱敏解析**
- [ ] **Step 4: 覆盖空列表、结构变化和最多 100 条截断**
- [ ] **Step 5: 运行解析测试并提交**

### Task 3: 第二、三期网页客户端

**Files:**
- Modify: `carrier_usage/providers/china_unicom_web_client.py`
- Modify: `carrier_usage/errors.py`
- Test: `tests/test_unicom_web_client_phase_2.py`

**Interfaces:**
- Produces: `query_payments(start, end)`、`query_invoices(month)`、`query_rebates()`、`query_contract_bill(month)`。
- Produces: `query_usage_details(category, month)`，不发送验证码并抛出 `SecondaryAuthenticationRequiredError`。

- [ ] **Step 1: 编写方法、URL、Referer、参数和二次认证失败测试**
- [ ] **Step 2: 运行测试，确认客户端缺少方法**
- [ ] **Step 3: 实现统一 GET/POST、官方状态码和只读方法**
- [ ] **Step 4: 实现详单二次认证专用错误，不发起网络请求**
- [ ] **Step 5: 运行客户端测试并提交**

### Task 4: CLI、统一渲染与 Agent 触发词

**Files:**
- Modify: `carrier_usage/cli.py`
- Modify: `carrier_usage/web_render.py`
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `agents/openai.yaml`
- Modify: `pyproject.toml`
- Test: `tests/test_cli.py`
- Test: `tests/test_web_render.py`
- Test: `tests/test_skill_docs.py`

**Interfaces:**
- Produces: `payments --from YYYY-MM --to YYYY-MM`。
- Produces: `invoices --month YYYY-MM`、`rebates`、`contract-bills --month YYYY-MM`。
- Produces: `usage-details --category data|voice|sms --month YYYY-MM`。

- [ ] **Step 1: 编写五个命令、JSON 信封、中文摘要和文档触发词失败测试**
- [ ] **Step 2: 运行测试并确认失败原因正确**
- [ ] **Step 3: 接入统一账户解析、刷新保护和查询路由**
- [ ] **Step 4: 更新中文 Skill、README、0.4.0 和 UI 元数据**
- [ ] **Step 5: 运行定向测试并提交**

### Task 5: 发布前安全和兼容验证

**Files:**
- Verify: all changed files

- [ ] **Step 1: 运行 `ruff check`、`ruff format --check` 和 `mypy`**
- [ ] **Step 2: 运行完整 `pytest`**
- [ ] **Step 3: 运行 `quick_validate.py` 和 `python -m build`**
- [ ] **Step 4: 搜索 Cookie、Token、真实号码、订单号、金额和原始响应残留**
- [ ] **Step 5: 确认 Git diff 只包含第二、三期范围并提交**
