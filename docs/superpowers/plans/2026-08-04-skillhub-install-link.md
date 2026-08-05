# SkillHub 安装链接文档更新实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用正式 SkillHub 详情链接和安装提示替换 README 中的占位说明，并明确 skills.sh 收录状态。

**Architecture:** 仅修改 README 的安装章节，不改变代码、版本号、Skill 内容或发布状态。通过 Markdown 链接检查、Skill 校验和 Git diff 验证文档质量。

**Tech Stack:** Markdown、Agent Skill 校验脚本、Git。

## Global Constraints

- SkillHub URL 固定为 `https://skillhub.cn/skills/user_639ac3ba/query-carrier-usage`。
- SkillHub 详情页已确认展示 `v0.1.1`，可以提供正式安装提示。
- 中文优先；skills.sh 未收录状态必须如实说明。

---

### Task 1：更新 README 安装说明

**Files:**
- Modify: `README.md`

**Interfaces:**
- Produces: 指向公开 SkillHub 详情页的安装说明。

- [ ] **Step 1: 替换占位文案**

将：

```text
Agent Skill 发布后也可以通过技能目录安装；正式 URL 会在 SkillHub 审核和 skills.sh 收录后补充。
```

替换为：

```markdown
SkillHub 已收录本 Skill：[运营商流量与资费查询](https://skillhub.cn/skills/user_639ac3ba/query-carrier-usage)。可将以下提示词发送给支持 Agent Skills 的 AI 助手进行安装：

```text
请根据 https://skillhub.cn/install/skillhub.md，安装 query-carrier-usage。
```

skills.sh 尚未收录，后续补充对应链接。
```

- [ ] **Step 2: 验证文档**

```bash
rg -n "skillhub.cn/skills/user_639ac3ba/query-carrier-usage|v0.1.1|skills.sh" README.md
.venv312/bin/python /Users/weieast/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
git diff --check
```

Expected: 找到正式 URL 和两项状态说明；Skill 输出 `Skill is valid!`；Git diff 无空白错误。

- [ ] **Step 3: 提交并推送**

```bash
git add README.md
git commit -m "docs: add SkillHub install link"
git push origin main
```

Expected: 本地与 `origin/main` 指向相同提交。
