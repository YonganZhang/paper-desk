#!/usr/bin/env python3
"""查课题组投稿台账的论文进度。只读，不改任何数据。

    export PORTAL_BASE='https://paper.example.org/api/v1'   # 你的台账地址；默认本机 127.0.0.1:8611
    export PORTAL_TOKEN='<只读 token>'      # Linux/macOS
    $env:PORTAL_TOKEN='<只读 token>'        # Windows PowerShell

    python check_papers.py                 # 全部
    python check_papers.py P13             # 某一篇（编号大小写不敏感）
    python check_papers.py --watch         # 只列在投的（一次查询，不驻留）
    python check_papers.py --stats         # 统计
    python check_papers.py --stale 90      # 在投且已超过 N 天的
    python check_papers.py --json          # 原始 JSON，给 AI 直接吃
    python check_papers.py P13 --json      # 单篇原始 JSON

注意：经 CDN / 反向代理（例如 Cloudflare）暴露时，部分 CDN 会拦截默认的
Python-urllib User-Agent（返回 403，到不了认证环节）。本脚本固定发送自定义 UA。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

BASE = os.environ.get("PORTAL_BASE", "http://127.0.0.1:8611/api/v1").rstrip("/")
TOKEN = os.environ.get("PORTAL_TOKEN", "")
UA = "paper-desk-client/1.1"


def get(path: str, **params):
    if not TOKEN:
        sys.exit("没有 token。先设环境变量 PORTAL_TOKEN（网站「管理」页生成）。")
    url = BASE + path
    params = {k: v for k, v in params.items() if v}
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + TOKEN,
                      "User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            sys.exit("HTTP 403：token 权限不足，或被 CDN/反向代理拦截（常见原因是 User-Agent）。"
                     "确认请求带了 User-Agent 头。")
        msg = {401: "token 缺失或不对", 404: "没有这个编号",
               503: "服务端还没生成 token，去管理页生成"}
        sys.exit(f"HTTP {e.code}：{msg.get(e.code, e.reason)}")
    except urllib.error.URLError as e:
        sys.exit(f"连不上 {BASE}：{e.reason}")


def months_between(d: date, today: date) -> int:
    """满几个自然月（3 个自然月 ≠ 90 天）。"""
    m = (today.year - d.year) * 12 + (today.month - d.month)
    if today.day < d.day:
        m -= 1
    return m


def show(p: dict, detail: bool = False) -> None:
    mine = p["my_author_position"] or "位次未标"
    if p["i_am_corresponding"]:
        mine += " + 通讯"
    n = p["submission_count"]
    print(f"\n[{p['code']}] {p['status']}   我：{mine}")
    print(f"  {p['title']}")
    if p["title_cn"]:
        print(f"  {p['title_cn']}")
    line = f"  当前期刊：{p['current_journal'] or '（无投稿记录）'}"
    if n > 1:
        line += f"   第 {n} 次（转投过 {n - 1} 次）"
    print(line)
    d = p.get("days_since_current_submit")
    cur = p.get("current_submission") or {}
    if d is not None:
        sd = cur.get("submit_date")
        mo = months_between(datetime.strptime(sd, "%Y-%m-%d").date(), date.today())
        print(f"  已投出 {d} 天（满 {mo} 个自然月），自 {sd}")
    elif cur:
        print("  投稿日期未填，无法计算已投出多久")
    if detail:
        if p["authors"]:
            print("  作者：" + " / ".join(p["authors"]))
        else:
            print("  作者：未录入")
        for s in p["submissions"]:
            tail = "  ← 当前" if s["is_current"] else "  （历史）"
            print(f"    第{s['seq']}次 {s['journal']}  {s['submit_date'] or '无日期'}"
                  f"  {s['status']}{tail}")
            if s["manuscript_id"]:
                print(f"           稿号 {s['manuscript_id']}")
        for f in p.get("files", []):
            print(f"    附件 {f['name']}  {f['size_mb']} MB")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="查投稿台账（只读）", formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="--watch 是一次性查询，不驻留监控。要定时提醒请用系统计划任务。")
    ap.add_argument("code", nargs="?", help="论文编号，如 P13")
    ap.add_argument("--watch", action="store_true", help="只列在投的（一次查询）")
    ap.add_argument("--stats", action="store_true", help="统计")
    ap.add_argument("--stale", type=int, metavar="N", help="列出在投且已超过 N 天的")
    ap.add_argument("--position", help="按位次过滤，如 第一作者")
    ap.add_argument("--json", action="store_true", help="输出原始 JSON")
    a = ap.parse_args()

    if a.stats:
        d = get("/stats")
        if a.json:
            print(json.dumps(d, ensure_ascii=False, indent=2)); return
        print(f"共 {d['total']} 篇   （{d['generated_at']} {d.get('timezone','')}）")
        print("\n按状态：")
        for k, v in sorted(d["by_status"].items(), key=lambda x: -x[1]):
            print(f"  {k:<8}{v}")
        print("\n按我的作者位次：")
        for k, v in sorted(d["by_author_position"].items(), key=lambda x: -x[1]):
            print(f"  {k:<8}{v}")
        print(f"  {'通讯作者':<8}{d['corresponding_count']}")
        return

    if a.code:
        d = get(f"/papers/{a.code}")
        print(json.dumps(d, ensure_ascii=False, indent=2)) if a.json else show(d, detail=True)
        return

    d = get("/papers", status="投稿中" if (a.watch or a.stale is not None) else "",
            position=a.position or "")
    papers = d["papers"]
    if a.stale is not None:
        papers = [p for p in papers
                  if (p.get("days_since_current_submit") or -1) >= a.stale]
    if a.json:
        print(json.dumps({**d, "papers": papers}, ensure_ascii=False, indent=2)); return
    label = (f"在投且超过 {a.stale} 天" if a.stale is not None
             else "在投" if a.watch else "全部")
    print(f"{label} {len(papers)} 篇：")
    for p in papers:
        show(p)
    if not papers:
        print("  （没有符合条件的）")


if __name__ == "__main__":
    main()
