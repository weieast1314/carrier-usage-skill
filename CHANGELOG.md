# 版本说明（Changelog）

本文件是发布到 SkillHub 时版本说明的单一可信源。打 `vX.Y.Z` tag 时，
`scripts/publish_skill.sh` 会按以下优先级提取该版本的说明：

1. git tag 的 annotation message（`git tag -a vX.Y.Z -m "..."`）；
2. 本文件中 `## X.Y.Z` 对应段落；
3. 兜底占位文本。

## 0.4.6 - 2026-08-06

- 修复联通限流重试路径的真实 bug：`china_unicom_web.py` 重试耗尽判断误用 `self.max_retries`（不存在），改为 `self._max_retries`，避免限流重试耗尽时 `AttributeError`。
- 清理静态检查：修复 mypy `no-any-return`（退避秒数显式 `int()`）与 ruff 既有 lint（UP037/I001 等），CI 质量检查转绿。

## 0.4.5 - 2026-08-06

- 修复 CI「持续集成」工作流「安装依赖」步骤失败：`pyproject.toml` 迁移到 `carrier-usage-skill/` Skill 包内，与 CI 的 `working-directory` 一致。
- 发布说明自动化：新增 `CHANGELOG.md` 作为单一可信源，`scripts/publish_skill.sh` 缺省按 git tag annotation → `CHANGELOG.md` 段落 → 占位三级回退提取真实版本说明，CI 不再使用写死占位文本。
- `pip_audit` 审计步骤改为在 Skill 包目录运行并 `--skip-editable`，避免审计本地 editable 包报错。

## 0.4.4 - 2026-08-05

- 新增 `.github/workflows/publish.yml`，推送 `v*` tag 时自动发布到 SkillHub（校验 tag 与版本一致）。
- 补充 README 发布流程章节。

## 0.4.3 - 2026-08-05

- 新增 `scripts/publish_skill.sh` 发布脚本，发布前自动排除 `.venv`/缓存等超大目录，避免 skillhub CLI 打包失败。

## 0.4.2 - 2026-08-05

- 联通接口层限流识别与指数退避重试正式发布。

## 0.4.1 - 2026-08-05

- 重组仓库为标准 SkillHub 布局（外层 git 项目 + 嵌套 `carrier-usage-skill/` Skill 包）。
- 加入上游限流识别与指数退避重试。

## 0.4.0 - 2026-08-04

- 补齐中国联通只读查询能力：交费记录、电子发票、返费与赠款、金融合约账单，以及需短信二次认证的详单查询。
- 完善多账户与默认卡管理。
