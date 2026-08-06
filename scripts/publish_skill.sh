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
# 版本说明（--changelog）缺省时，按以下优先级自动提取真实说明：
#   1. git tag 的 annotation message（建议打 annotated tag：git tag -a vX.Y.Z -m "..."）
#   2. 仓库根 CHANGELOG.md 中 "## X.Y.Z" 对应段落
#   3. 兜底占位文本
#
# 前置条件：已安装 skillhub CLI 且已登录（skillhub auth whoami）。
set -euo pipefail

# 仓库根目录（脚本位于 <root>/scripts/）
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_DIR="$ROOT_DIR/carrier-usage-skill"
CHANGELOG_FILE="$ROOT_DIR/CHANGELOG.md"

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

# 从 SKILL.md 读取版本号（去掉 v 前缀即为 CHANGELOG 段落标题）
SKILL_VERSION="$(grep -m1 '^version:' "$SKILL_DIR/SKILL.md" | sed 's/version:[[:space:]]*//')"

# 提取某版本的发布说明：优先 git tag annotation，其次 CHANGELOG.md 段落，最后占位
extract_changelog() {
  local ver="$1"
  local tag="v$ver"
  local note=""

  # 1) git tag annotation（仅当是 annotated tag 对象时；轻量 tag 的 %(contents) 会误返回 commit message，需跳过）
  if command -v git >/dev/null 2>&1 && git rev-parse "$tag" >/dev/null 2>&1; then
    if [ "$(git cat-file -t "refs/tags/$tag" 2>/dev/null)" = "tag" ]; then
      local anno
      anno="$(git for-each-ref --format='%(contents)' "refs/tags/$tag" 2>/dev/null | sed '/^$/d')"
      if [ -n "$anno" ]; then
        note="$anno"
      fi
    fi
  fi

  # 2) CHANGELOG.md 中 "## X.Y.Z" 段落（到下一个 "## " 或文件尾）
  if [ -z "$note" ] && [ -f "$CHANGELOG_FILE" ]; then
    note="$(awk -v v="$ver" '
      /^## / {
        if (found) exit
        sub(/^##[[:space:]]*/, "")
        # 标题形如 "0.4.5 - 2026-08-06" 或 "0.4.5"
        split($0, parts, /[[:space:]]*-[[:space:]]*/)
        if (parts[1] == v) { found=1; next }
        next
      }
      found { print }
    ' "$CHANGELOG_FILE" | sed '/^$/d')"
  fi

  # 3) 兜底占位
  if [ -z "$note" ]; then
    note="发布版本 $tag"
  fi

  printf '%s' "$note"
}

# --changelog 未显式提供时，自动提取真实版本说明
if [ -z "$CHANGELOG" ]; then
  CHANGELOG="$(extract_changelog "$SKILL_VERSION")"
fi
echo "版本说明：$CHANGELOG"

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
  exit 0
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
