#!/usr/bin/env bash
#
# 发布 carrier-usage-skill 到 SkillHub，发布前自动排除大型/无关目录。
#
# 背景：skillhub CLI 不会读取 .gitignore，会把 .venv（数百 MB）和各类
# 缓存目录一并打包，导致上传 Broken pipe 或文件类型校验失败。本脚本先把
# Skill 包复制到一个干净的临时目录（排除 .venv / 缓存 / 字节码），再发布，
# 发布后自动清理临时目录，不污染工作区。
#
# 用法：
#   scripts/publish_skill.sh [--changelog "说明文字"] [--version-check]
#
# 前置条件：已安装 skillhub CLI 且已登录（skillhub auth whoami）。
set -euo pipefail

# 仓库根目录（脚本位于 <root>/scripts/）
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_DIR="$ROOT_DIR/carrier-usage-skill"

# 需排除、不应进入发布包的路径（相对 SKILL_DIR）
EXCLUDES=(
  ".venv"
  "venv"
  ".env"
  ".mypy_cache"
  ".pytest_cache"
  ".ruff_cache"
  "__pycache__"
  "*.egg-info"
  ".coverage"
  "htmlcov"
  ".DS_Store"
  ".skillhubignore"
)

CHANGELOG=""
VERSION_CHECK=0
DRY_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --changelog)
      CHANGELOG="${2:-}"; shift 2 ;;
    --version-check)
      VERSION_CHECK=1; shift ;;
    --dry-run)
      DRY_RUN=1; shift ;;
    *)
      echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

# 确保 skillhub 可用（本地可能装在 ~/.local/bin，CI 可能装在 pip --user 的 bin）
if ! command -v skillhub >/dev/null 2>&1; then
  USER_BIN="$(python3 -m site --user-base 2>/dev/null)/bin"
  export PATH="$HOME/.local/bin:$USER_BIN:$PATH"
fi
if ! command -v skillhub >/dev/null 2>&1; then
  echo "未找到 skillhub CLI，请先安装：pip install skillhub-cli" >&2
  exit 1
fi

# 版本号检查：确保 SKILL.md 中的 version 与 git 最新 tag/提交信息一致提示
if [ "$VERSION_CHECK" -eq 1 ]; then
  if ! grep -q "^version: " "$SKILL_DIR/SKILL.md"; then
    echo "SKILL.md 缺少 version 字段" >&2; exit 1
  fi
  echo "当前 SKILL.md 版本：$(grep '^version:' "$SKILL_DIR/SKILL.md")"
fi

# 构造临时发布目录
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/skillhub_publish.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

# 用 rsync 复制并排除无关目录（无 rsync 时回退到 cp + 删除）
if command -v rsync >/dev/null 2>&1; then
  RSYNC_EXCLUDES=()
  for e in "${EXCLUDES[@]}"; do RSYNC_EXCLUDES+=(--exclude="$e"); done
  rsync -a --delete "${RSYNC_EXCLUDES[@]}" "$SKILL_DIR/" "$TMP_DIR/"
else
  cp -R "$SKILL_DIR/." "$TMP_DIR/"
  for e in "${EXCLUDES[@]}"; do
    # 支持通配（如 *.egg-info）仅在 find 可用时处理简单情况
    rm -rf "$TMP_DIR/$e" 2>/dev/null || true
  done
  find "$TMP_DIR" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  find "$TMP_DIR" -type d -name '.mypy_cache' -prune -exec rm -rf {} + 2>/dev/null || true
  find "$TMP_DIR" -type d -name '.pytest_cache' -prune -exec rm -rf {} + 2>/dev/null || true
  find "$TMP_DIR" -type d -name '.ruff_cache' -prune -exec rm -rf {} + 2>/dev/null || true
fi

echo "已准备干净发布目录：$TMP_DIR"
if command -v du >/dev/null 2>&1; then
  echo "发布目录大小：$(du -sh "$TMP_DIR" | cut -f1)"
fi

# 组装发布命令
PUBLISH_CMD=(skillhub publish "$TMP_DIR")
if [ -n "$CHANGELOG" ]; then
  PUBLISH_CMD+=(--changelog "$CHANGELOG")
fi

if [ "$DRY_RUN" -eq 1 ]; then
  # 仅预览将要发布的目录内容，不真正发布，也不清理临时目录
  trap - EXIT
  echo "[dry-run] 将发布的目录：$TMP_DIR"
  echo "[dry-run] 顶层内容："
  ls -a "$TMP_DIR"
  echo "[dry-run] 若含不应发布的目录（.venv/缓存等）请检查 EXCLUDES。"
  exit 0
fi

echo "执行：${PUBLISH_CMD[*]}"
"${PUBLISH_CMD[@]}"

echo "发布完成，临时目录已清理。"
