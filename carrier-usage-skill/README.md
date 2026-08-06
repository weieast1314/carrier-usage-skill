# 运营商用量查询 Skill（包内说明）

本文件是 `carrier-usage-skill/` Skill 包的说明。完整的项目说明、安装、使用与发布流程见仓库根目录的 [`../README.md`](../README.md)。

本目录是 SkillHub 的标准 Skill 包布局：

```
carrier-usage-skill/
├── SKILL.md          # 必需：YAML 元数据 + Markdown 指令
├── pyproject.toml    # 包配置（在 Skill 包内）
├── README.md         # 本文件
├── carrier_usage/    # 源码包
├── scripts/          # 可执行脚本
├── references/       # 按需加载的参考文档
└── tests/            # 测试
```

开发、测试与发布命令均在本目录内执行，例如：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -v
```
