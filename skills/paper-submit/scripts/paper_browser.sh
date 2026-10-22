#!/usr/bin/env bash
# 投稿浏览器：Linux 服务器上常驻的 Chromium（Xvfb 虚拟屏幕 + 可选代理 + 按投稿人保留登录），由 playwright-cli 操作。
#
# 用法:
#   paper_browser.sh open <投稿人ID> [url]   打开或复用 session "submit-<投稿人ID>"，登录状态存在该投稿人的 profile 里
#   paper_browser.sh env                     打印要 export 的 DISPLAY 与配置路径
#   paper_browser.sh check                   检查依赖和密码来源是否就绪（不打印真值）
#   paper_browser.sh stop <投稿人ID>         关掉该投稿人的 session（profile 保留）
#
# 之后照常用: playwright-cli -s=submit-<投稿人ID> snapshot / fill / click …
# 输入密码只写 secret 名: playwright-cli -s=… fill <ref> PAPER_SUBMIT_DEFAULT_PASSWORD
#   （只许字母数字的系统用 PAPER_SUBMIT_ALNUM_PASSWORD：同一密码去掉标点）
# 环境变量与默认值见 references/setup.md。
set -euo pipefail

STATE=${PAPER_SUBMIT_HOME:-$HOME/.local/share/paper-submit}
CONF_DIR=${PAPER_SUBMIT_CONFIG_DIR:-$HOME/.config/paper-submit}
CONF=$CONF_DIR/cli.config.json
DISP=${PAPER_SUBMIT_DISPLAY:-:97}
SCREEN=${PAPER_SUBMIT_SCREEN:-1440x960x24}
PWCLI=${PAPER_SUBMIT_PLAYWRIGHT:-playwright-cli}
USE_SYSTEMD=${PAPER_SUBMIT_SYSTEMD:-auto}

die() { echo "paper_browser: $*" >&2; exit 1; }

# 取一个 secret 的真值，只放进变量，不回显、不进命令行。
#   默认密码：环境变量 PAPER_SUBMIT_DEFAULT_PASSWORD，或执行 PAPER_SUBMIT_PASSWORD_CMD 取 stdout
#   其他 KEY：同名环境变量，或执行 "PAPER_SUBMIT_SECRET_CMD <KEY>" 取 stdout
default_password() {
  if [ -n "${PAPER_SUBMIT_DEFAULT_PASSWORD:-}" ]; then
    printf '%s' "$PAPER_SUBMIT_DEFAULT_PASSWORD"
  elif [ -n "${PAPER_SUBMIT_PASSWORD_CMD:-}" ]; then
    sh -c "$PAPER_SUBMIT_PASSWORD_CMD" </dev/null || die "PAPER_SUBMIT_PASSWORD_CMD 执行失败"
  else
    die "没有密码来源：设置 PAPER_SUBMIT_DEFAULT_PASSWORD 或 PAPER_SUBMIT_PASSWORD_CMD"
  fi
}
named_secret() {
  local key=$1
  [[ $key =~ ^[A-Z][A-Z0-9_]*$ ]] || die "secret 名只许大写字母、数字和下划线：$key"
  if [ -n "${!key:-}" ]; then
    printf '%s' "${!key}"
  elif [ -n "${PAPER_SUBMIT_SECRET_CMD:-}" ]; then
    sh -c "$PAPER_SUBMIT_SECRET_CMD \"\$1\"" sh "$key" </dev/null || die "PAPER_SUBMIT_SECRET_CMD 取 $key 失败"
  else
    die "取不到 $key：设置同名环境变量，或设置 PAPER_SUBMIT_SECRET_CMD"
  fi
}

use_systemd() {
  case "$USE_SYSTEMD" in
    yes|1|true) return 0 ;;
    no|0|false) return 1 ;;
    *) command -v systemd-run >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1 ;;
  esac
}

# 浏览器比这条命令活得久：有 systemd 用户实例时放进独立 scope 并限内存，否则直接起
detached() {  # detached <unit 名> <MemoryMax> <命令…>
  local unit=$1 mem=$2; shift 2
  if use_systemd; then
    systemd-run --user --scope --quiet --collect --unit="$unit-$$" -p MemoryMax="$mem" "$@"
  else
    "$@"
  fi
}

make_config() {
  # 每次打开都按当前环境重写：代理、密码可能变了。文件含真值，权限 0600，只给 playwright-cli 读
  umask 077
  mkdir -p "$CONF_DIR"
  local pw extra="" k v
  pw=$(default_password)
  [ -n "$pw" ] || die "默认密码为空"
  # 别人的账号（例如只读查状态用的通讯作者账号）：PAPER_SUBMIT_EXTRA_SECRETS="KEY1,KEY2"，登记成同名 secret
  local list=${PAPER_SUBMIT_EXTRA_SECRETS:-}
  for k in ${list//,/ }; do
    v=$(named_secret "$k")
    [ -n "$v" ] || die "$k 的值为空"
    extra+="$k"$'\t'"$v"$'\n'
  done
  PW="$pw" EXTRA="$extra" PROXY="${PAPER_SUBMIT_PROXY:-${HTTPS_PROXY:-${https_proxy:-}}}" python3 -I - "$CONF" <<'PY'
import json, os, re, sys
from urllib.parse import urlsplit, unquote
proxy = os.environ.get("PROXY", "")
launch = {"headless": False}
if proxy:
    u = urlsplit(proxy)
    launch["proxy"] = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
    if u.username:
        launch["proxy"].update(username=unquote(u.username), password=unquote(u.password or ""))
cfg = {"browser": {"browserName": "chromium", "launchOptions": launch,
                   "contextOptions": {"viewport": {"width": 1400, "height": 900}, "acceptDownloads": True}},
       # 有的系统密码只许字母和数字：用同一密码去掉标点后的变体，不另立新密码
       "secrets": {"PAPER_SUBMIT_DEFAULT_PASSWORD": os.environ["PW"],
                   "PAPER_SUBMIT_ALNUM_PASSWORD": re.sub(r"[^A-Za-z0-9]", "", os.environ["PW"])}}
for line in os.environ.get("EXTRA", "").splitlines():
    if line:
        k, v = line.split("\t", 1)
        cfg["secrets"][k] = v
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(cfg, fh)
PY
  [ -n "${PAPER_SUBMIT_PROXY:-${HTTPS_PROXY:-${https_proxy:-}}}" ] || echo "提示：没有配置代理（PAPER_SUBMIT_PROXY / HTTPS_PROXY），浏览器直连" >&2
}

ensure_display() {
  local pidfile=$STATE/xvfb${DISP#:}.pid
  mkdir -p "$STATE"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then return; fi
  command -v Xvfb >/dev/null 2>&1 || die "找不到 Xvfb（Debian/Ubuntu: apt install xvfb）"
  # 直接把命令放后台（不经函数），$! 才是 Xvfb 本身（scope 模式下 systemd-run 会 exec 成 Xvfb）
  if use_systemd; then
    systemd-run --user --scope --quiet --collect --unit="paper-xvfb-${DISP#:}-$$" -p MemoryMax=1G \
      Xvfb "$DISP" -screen 0 "$SCREEN" -nolisten tcp >/dev/null 2>&1 &
  else
    Xvfb "$DISP" -screen 0 "$SCREEN" -nolisten tcp >/dev/null 2>&1 &
  fi
  echo $! > "$pidfile"
  sleep 1
  kill -0 "$(cat "$pidfile")" 2>/dev/null || die "Xvfb $DISP 起不来（可能被别人占用，换 PAPER_SUBMIT_DISPLAY）"
}

cmd=${1:-}
case "$cmd" in
  open)
    id=${2:?需要投稿人ID，如 zhang-san}
    url=${3:-about:blank}
    command -v "$PWCLI" >/dev/null 2>&1 || die "找不到 $PWCLI（见 references/setup.md）"
    make_config
    ensure_display
    mkdir -p "$STATE/profiles"
    DISPLAY=$DISP detached "playwright-submit" 2G \
      "$PWCLI" -s="submit-$id" open "$url" --config="$CONF" --profile="$STATE/profiles/$id"
    ;;
  env)
    echo "export DISPLAY=$DISP"
    echo "# 配置：$CONF；profile：$STATE/profiles/<投稿人ID>；账号登记：$STATE/accounts.json"
    ;;
  check)
    ok=0
    for b in "$PWCLI" Xvfb python3; do
      if command -v "$b" >/dev/null 2>&1; then echo "ok   $b"; else echo "缺少 $b"; ok=1; fi
    done
    if (default_password >/dev/null); then echo "ok   默认密码来源"; else ok=1; fi
    for k in $(echo "${PAPER_SUBMIT_EXTRA_SECRETS:-}" | tr ',' ' '); do
      if (named_secret "$k" >/dev/null); then echo "ok   $k"; else ok=1; fi
    done
    if use_systemd; then echo "ok   systemd 用户实例（浏览器放进限内存的 scope）"; else echo "--   不用 systemd，直接启动"; fi
    exit $ok
    ;;
  stop)
    id=${2:?需要投稿人ID}
    "$PWCLI" -s="submit-$id" close
    ;;
  *)
    sed -n '2,13p' "$0"; exit 2 ;;
esac
