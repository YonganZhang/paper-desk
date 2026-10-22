#!/usr/bin/env bash
# 读投稿系统页面的纯文本（含同源 iframe），代替整页 snapshot，省 token。只读，不点击。
# 用法：page_text.sh <投稿人ID> [网址] [最多字符数，默认 4000]
#   给网址时先跳转；不给就读当前页。需要点击或填表时再用 snapshot 取 ref。
# 浏览器、profile、代理与密码配置沿用 paper-submit 的 paper_browser.sh（环境变量 PAPER_BROWSER 可改路径）。
# 注意：会话已开着时会直接 goto，会把正在用这个会话的人的页面跳走；先确认没人在用（见 SKILL.md「浏览器与账号」）。
set -euo pipefail
id=${1:?需要投稿人ID，例如 zhang-san}
url=${2:-}
max=${3:-4000}
here=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
BROWSER=${PAPER_BROWSER:-$here/../../paper-submit/scripts/paper_browser.sh}
PWCLI=${PAPER_SUBMIT_PLAYWRIGHT:-playwright-cli}
[ -f "$BROWSER" ] || { echo "找不到 paper_browser.sh：$BROWSER（设 PAPER_BROWSER）" >&2; exit 1; }
export DISPLAY=${PAPER_SUBMIT_DISPLAY:-:97}
# playwright-cli 会把快照和日志写进当前目录，固定写到工作目录，不弄脏项目
work=${PAPER_STATUS_WORK:-$HOME/.cache/paper-status-check}
mkdir -p "$work" && cd "$work"

if ! "$PWCLI" -s="submit-$id" eval "() => 1" >/dev/null 2>&1; then
  bash "$BROWSER" open "$id" "${url:-about:blank}" >/dev/null
elif [ -n "$url" ]; then
  "$PWCLI" -s="submit-$id" goto "$url" >/dev/null
fi

js="() => { const parts = [document.title + ' | ' + location.href, document.body ? document.body.innerText : ''];
  for (const f of document.querySelectorAll('iframe, frame')) {
    try { parts.push('---- frame ' + (f.name || f.id || '') + ' ----\n' + f.contentDocument.body.innerText); } catch (e) { parts.push('---- frame (跨域，读不到) ----'); }
  }
  return parts.join('\n').replace(/\n{3,}/g, '\n\n').slice(0, $max); }"
read_text() {
  "$PWCLI" -s="submit-$id" eval "$js" | sed -n '/^### Result/,/^### Ran/p' | sed '1d;$d' \
    | python3 -I -c 'import json,sys; t=sys.stdin.read().strip(); print(json.loads(t) if t.startswith("\"") else t)'
}
# 列表页常在 iframe 里晚几秒才加载：有 frame 但 frame 里没字就等一下再读，最多三次
for i in 1 2 3; do
  out=$(read_text)
  frames=$(printf '%s\n' "$out" | grep -c -- '^---- frame' || true)
  body=$(printf '%s\n' "$out" | awk '/^---- frame/{f=1;next} f&&NF{c++} END{print c+0}')
  { [ "$frames" -eq 0 ] || [ "$body" -gt 0 ]; } && break
  [ "$i" -lt 3 ] && sleep 4
done
printf '%s\n' "$out"
