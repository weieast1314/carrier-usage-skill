---
name: query-carrier-usage
slug: query-carrier-usage
displayName: 运营商流量与资费查询
version: 0.4.4
summary: 安全查询本人或已获授权的中国运营商话费、账单、交费发票、套餐余量与成员用量
license: Apache-2.0
homepage: https://github.com/weieast1314/carrier-usage-skill
description: Use when 用户需要查询本人或已获授权的中国运营商剩余话费、月账单、交费记录、电子发票、返费赠款、金融合约账单、详单、套餐余量、积分、套餐资费、流量、语音、短信、成员/主副卡用量、联通云盘空间，或排查运营商认证与查询错误。
---

# 运营商用量查询

## 核心原则

只查询用户本人或明确授权的账户。默认输出中文和脱敏标识，不在聊天、日志或命令行参数中接收短信验证码、ticket、Cookie、token 或完整手机号。

## 查询流程

1. 确认用户有权查询该账户。
2. 先确定账户。用户说出中文别名时传入 `--account "别名"`；“查流量”等未指定运营商的请求使用全局默认，“查联通流量”等指定运营商的请求使用运营商默认。“再看看套餐”等追问沿用当前对话已选账户。只有真正歧义时才展示别名、运营商和号码组成的脱敏选项，不猜测。
3. 成员/副卡先定位所属主账户，再定位成员；默认支持查询成员/副卡用量。
4. 在 Skill 根目录运行能力检查：

   ```bash
   python3 scripts/carrier_usage.py capabilities --provider china_unicom
   ```

5. 如果本机尚未登录，优先引导用户通过中国联通 APP 扫描官方二维码登录：

   ```bash
   python3 scripts/carrier_usage.py login --provider china_unicom --alias "我的联通"
   ```

   让用户在弹出的中国联通官方页面点击“请登录”，选择扫码方式，并使用已登录的“中国联通”APP 扫码确认。不要截图、解析或转发二维码。网页登录会话默认保存在权限为 `0600` 的本机文件中。

6. 首次查询或凭据可能失效时先运行：

   ```bash
   python3 scripts/carrier_usage.py doctor --provider china_unicom
   ```

7. 根据用户意图调用最小的独立业务命令。优先使用 `--format json` 获取稳定结构，再生成中文回答：

   | 用户意图或触发词 | 命令 |
   |---|---|
   | 剩余话费、话费余额、还有多少钱、本月消费 | `balance --account "别名" --format json` |
   | 余量查询、套餐余量、流量语音短信还剩多少 | `allowances --account "别名" --format json` |
   | 我的账单、月账单、某月话费账单 | `bills --account "别名" --month YYYY-MM --format json` |
   | 交费记录、充值记录、缴费历史 | `payments --account "别名" --from YYYY-MM --to YYYY-MM --format json` |
   | 电子发票、已有发票、发票记录 | `invoices --account "别名" --month YYYY-MM --format json` |
   | 返费与赠款、赠款记录、合约返赠 | `rebates --account "别名" --format json` |
   | 金融合约账单、金融代收 | `contract-bills --account "别名" --month YYYY-MM --format json` |
   | 详单查询、通话详单、短信详单、上网详单 | `usage-details --account "别名" --category data\|voice\|sms --month YYYY-MM --format json` |

   示例：

   ```bash
   python3 scripts/carrier_usage.py balance --account "我的联通" --format json
   python3 scripts/carrier_usage.py allowances --account "我的联通" --detail --format json
   python3 scripts/carrier_usage.py bills --account "我的联通" --month 2026-08 --format json
   python3 scripts/carrier_usage.py payments --account "我的联通" --from 2026-01 --to 2026-08 --format json
   python3 scripts/carrier_usage.py invoices --account "我的联通" --month 2026-08 --format json
   python3 scripts/carrier_usage.py rebates --account "我的联通" --format json
   python3 scripts/carrier_usage.py contract-bills --account "我的联通" --month 2026-08 --format json
   ```

   所有命令均为只读。`invoices` 只列出已有发票，不申请、下载或发送发票；`payments` 不提供“再充一次”。详单查询必须由用户在联通官方页面完成短信二次认证，Skill 不发送验证码、不接收验证码，也不绕过验证。

8. 用户需要综合账户、套餐、成员或云盘信息时，再使用原有 `query` 命令并选择最小范围：

   | 用户意图或触发词 | `--scope` |
   |---|---|
   | 查积分、账户概览、当前套餐、套餐资费 | `overview` |
   | 查流量、流量明细、流量包、通用流量、其他流量 | `data` |
   | 查语音余量、通话分钟、还剩多少分钟 | `voice` |
   | 查短信余量、用了多少短信 | `sms` |
   | 查成员流量、查副卡用量、查主副卡、哪张卡用了流量 | `members` |
   | 查联通云盘、云盘空间、云盘还剩多少空间 | `resources` |
   | 查全部用量、查看完整余量 | `all` |

   普通概览不展开成员信息。成员能力默认可用，但只有用户明确询问成员、主卡或副卡时才使用 `members`；用户明确要求完整信息时才使用 `all`。

9. 综合查询也使用 JSON 获取稳定结构，再向用户生成中文摘要：

   ```bash
   python3 scripts/carrier_usage.py query --account "工作联通" --scope data --format json
   ```

10. 保留手机号遮蔽形式；不要展示原始接口响应、请求头或认证信息。

账户管理命令：

```bash
python3 scripts/carrier_usage.py accounts list
python3 scripts/carrier_usage.py accounts rename "工作联通" "办公联通"
python3 scripts/carrier_usage.py accounts set-default "办公联通"
python3 scripts/carrier_usage.py accounts set-provider-default "办公联通"
```

## Provider 状态

| Provider | 当前能力 |
|---|---|
| `china_unicom` | 官方 APP 扫码 Provider 支持剩余话费、月账单、交费记录、已有电子发票、返费与赠款、金融合约账单、余量、积分、套餐、成员/副卡和联通云盘；详单查询需官方短信二次认证 |
| 中国移动、中国电信、中国广电 | 尚未实现，不要伪造结果 |

## 错误处理

| 退出码 | 含义 | 处理方式 |
|---:|---|---|
| 2 | 配置错误 | 检查环境变量或权限为 `0600` 的 TOML 配置 |
| 3 | 认证失效或用户取消 | 重新运行 `login` 并使用中国联通 APP 扫码 |
| 4 | 刷新过快或上游限流 | 按错误给出的等待时间重试 |
| 5 | 联通接口结构变化 | 停止猜测字段，提交已脱敏的 issue |
| 6 | 网络、DNS、TLS 或超时 | 检查网络后重试 |
| 7 | Provider 或能力不支持 | 明确告知尚未支持 |

## 安全边界

- 不办理充值、缴费、套餐变更或退订。
- 不绕过验证码、设备验证、风控或实名认证。
- 不批量查询号码，不查询无授权账户。
- 不把真实运营商响应保存为测试样例。
- 不要求用户把手机号、短信验证码、会话文件或浏览器 Cookie 粘贴到对话中。

## 常见问题

- `doctor` 成功但查询失败：接口可能变化，先运行一次 JSON 查询并只保留脱敏错误。
- 查询过于频繁：等待本地刷新保护给出的剩余时间。
- 套餐字段为空：这是可选能力；如实说明“不完整”，不要根据月费推测套餐。
