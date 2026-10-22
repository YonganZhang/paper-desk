"""paper-status-check 的配置与台账调用：读 JSON 配置、补默认值，并提供调用台账 CLI 的 paper()。

配置文件：环境变量 PAPER_STATUS_CONFIG，默认 ~/.config/paper-desk/status-check.json。
字段说明见 references/config.md，示例见 assets/status-check.example.json。配置文件不存在时用默认值，并在 stderr 提示。
"""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

SKILL = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(os.environ.get("PAPER_STATUS_CONFIG") or "~/.config/paper-desk/status-check.json").expanduser()

DEFAULTS = {
    "ledger_cli": "paper",                  # 台账 CLI；环境变量 PAPER_CLI 优先
    "self_names": [],                       # 「本人」的姓名写法：台账负责人是其中之一时按本人跟进推
    "always_scan": [],                      # 本人的可读邮箱：每篇论文都扫
    "blocking_confirm_journals": [],        # 确认信写明「合著者全部确认前不进入编辑流程」的刊
    "near_acceptance_stages": ["小修", "已录用"],
    "extra_manuscript_id_patterns": [],     # 漏登扫描额外识别的稿号正则
    "work_dir": "~/.cache/paper-status-check",
    "report": {
        "from": "",                         # 发件邮箱，须在 mailboxes.json 里配置了 smtp
        "to": [],
        "subject": "投稿与期刊情况追踪（{date}）",
        "greeting": "您好：",
        "sender_label": "投稿服务器",
        "schedule_label": "每周一",
        "timezone": "",                     # 空 = 服务器本地时区
        "out_dir": "~/.local/share/paper-desk/weekly-status",
    },
}


def _merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load():
    if not CONFIG_PATH.exists():
        print(f"提示：没有配置文件 {CONFIG_PATH}，按默认值运行（见 references/config.md）", file=sys.stderr)
        return _merge(DEFAULTS, {})
    return _merge(DEFAULTS, json.loads(CONFIG_PATH.read_text(encoding="utf-8")))


CFG = load()
SUBMIT_HOME = Path(os.environ.get("PAPER_SUBMIT_HOME") or "~/.local/share/paper-submit").expanduser()
SUBMIT_ACCOUNTS = SUBMIT_HOME / "accounts.json"
PAPER_BROWSER = Path(os.environ.get("PAPER_BROWSER")
                     or SKILL.parent / "paper-submit" / "scripts" / "paper_browser.sh").expanduser()
WORK = Path(os.environ.get("PAPER_STATUS_WORK") or CFG["work_dir"]).expanduser()
PWCLI = os.environ.get("PAPER_SUBMIT_PLAYWRIGHT") or "playwright-cli"
PAPER_CMD = shlex.split(os.environ.get("PAPER_CLI") or CFG["ledger_cli"])
SELF = set(CFG["self_names"])


def tz():
    name = CFG["report"].get("timezone")
    return ZoneInfo(name) if name else None   # None：datetime.now(None).astimezone() 用本地时区


def paper(*args):
    r = subprocess.run([*PAPER_CMD, "--json", *args], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode:
        sys.exit(f"{' '.join(PAPER_CMD)} {' '.join(args)} 失败：{r.stderr.strip()}")
    return json.loads(r.stdout)


def submit_accounts():
    return json.loads(SUBMIT_ACCOUNTS.read_text(encoding="utf-8")) if SUBMIT_ACCOUNTS.exists() else []
