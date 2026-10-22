#!/usr/bin/env bash
# 把 PaperDesk 的六个技能装进 Claude Code / Codex 的技能目录（默认软链，便于 git pull 后自动更新）。
# 用法：bash install.sh [--claude] [--codex] [--copy]
#   不带 --claude/--codex 时两边都装；--copy 复制而不是软链。台账程序的安装见 ledger/README.md。
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
targets=() mode=link
for a in "$@"; do
  case "$a" in
    --claude) targets+=("$HOME/.claude/skills") ;;
    --codex)  targets+=("$HOME/.agents/skills") ;;
    --copy)   mode=copy ;;
    -h|--help) sed -n 2,4p "$0"; exit 0 ;;
    *) echo "未知参数：$a" >&2; exit 2 ;;
  esac
done
[ ${#targets[@]} -gt 0 ] || targets=("$HOME/.claude/skills" "$HOME/.agents/skills")
for t in "${targets[@]}"; do
  mkdir -p "$t"
  for s in paper-ledger paper-submit paper-status-check paper-mailbox paper-submission-kit paper-revision; do
    dst="$t/$s"
    if [ -e "$dst" ] || [ -L "$dst" ]; then echo "跳过 $dst（已存在，先自行移走）"; continue; fi
    if [ "$mode" = copy ]; then cp -r "$here/skills/$s" "$dst"; else ln -s "$here/skills/$s" "$dst"; fi
    echo "已安装 $dst"
  done
done
echo "下一步：按 docs/setup-linux.md 配置虚拟屏幕、浏览器和邮箱；按 ledger/README.md 启动台账。"
