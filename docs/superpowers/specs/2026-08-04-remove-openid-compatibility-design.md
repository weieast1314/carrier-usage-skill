# 移除 OpenID 兼容登录设计

## 背景

项目已经通过中国联通 APP 扫描官方网页二维码完成真实账户验证。旧微信小程序 OpenID Provider 操作困难，并会诱导用户处理敏感认证材料，因此不再作为兼容方案保留。

## 目标

- 中国联通只支持官方 APP 扫码登录和本地网页会话复用。
- 删除全部 OpenID 登录技术实现、配置入口、测试和用户文档表述。
- 删除记录旧兼容决策的历史设计文档和实施计划。
- 保留与认证方式无关的通用敏感字段过滤能力。
- 发布 `0.1.1` 修订版本并同步 GitHub、GitHub Release 和 SkillHub。

## 代码与配置变更

删除微信小程序 OpenID Provider 及其专属 HTTP 请求逻辑。`china_unicom` Provider 注册不再进行认证方式回退，只创建扫码网页 Provider。

从 `AppConfig`、环境变量读取、TOML 读取和 CLI 中移除 `unicom_openid` 与 `CARRIER_USAGE_UNICOM_OPENID`。没有有效扫码会话时，错误信息只引导用户运行 `login`。

删除示例配置中的 `openid` 字段。保留会话文件路径、查询刷新间隔和其他非 OpenID 配置。

## 文档变更

从 `SKILL.md` 和 `README.md` 删除 OpenID 配置方法、兼容模式、恢复建议和安全提示中的相关表述。认证流程只说明中国联通 APP 扫码登录。

直接删除以下旧历史文档：

- `docs/superpowers/specs/2026-08-03-unicom-web-sms-login-design.md`
- `docs/superpowers/plans/2026-08-03-unicom-web-sms-login.md`

其他仍有价值的架构与实现文档保持不变。

## 安全边界

`carrier_usage.redaction` 继续过滤键名 `openid` 和 `openId`。该逻辑属于通用防泄漏措施，不能被配置、CLI 或 Provider 调用，不代表项目支持 OpenID 登录。

项目继续禁止通过聊天、日志、命令行参数、Issue 或测试 fixture 传递 Cookie、token、ticket、完整手机号和原始认证响应。

## 测试策略

先增加或改写失败测试，验证：

- 配置模型不再暴露 `unicom_openid`。
- 环境变量和 TOML 中的旧 OpenID 设置不能启用兼容 Provider。
- Provider 注册始终选择扫码网页 Provider。
- CLI 查询不会读取 OpenID 环境变量。
- 源码、示例和面向用户文档不再包含 OpenID 登录说明。

随后删除旧 Provider 和不再适用的测试，运行完整 pytest、Ruff、格式检查、mypy、Skill 校验和构建。最后进行 Git 历史之外的当前追踪文件敏感信息检查。

## 发布

版本从 `0.1.0` 升级为 `0.1.1`，提交并推送 `main`，创建 GitHub Release。SkillHub 使用原 Slug `query-carrier-usage` 发布 `0.1.1`，变更说明明确为移除 OpenID 兼容登录，扫码登录成为唯一认证方式。
