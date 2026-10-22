#!/usr/bin/env python3
"""查论文前的可查性体检：按跟进方式分流，检查 AI 代查论文的登录路径和期刊来信邮箱。

只读：读台账（paper CLI，凭证只看「是否已保存」）、paper-submit 的账号登记 accounts.json、
邮箱登记 mailboxes.json（readable、author_links）；不登录任何网站，不连邮箱。
用法：access_audit.py [--days 30] [--include-extra] [--json]
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))   # -I 运行时脚本目录不在 sys.path
import settings  # noqa: E402
from settings import mailboxes  # noqa: E402  paper-mailbox/scripts/mailboxes.py

paper = settings.paper
PAPER = settings.PAPER_CMD
VERIFIED_MARK = "[可查性已验证]"
VERIFY_STALE_DAYS = 60
EXTRA = "其他论文（不计入主序列）"           # 台账 category 中 extra 的对外名（API 只返回中文名）


def follow_mode(p):
    """跟进方式只认台账的 follow_mode（ai=AI 代查、self=本人自查、student、watch=学生改·AI 盯截止、partner）。
    台账没登记时按负责人推：负责人是本人（配置 self_names）→ ai，
    其中跟进计划的 action_owner 写了「本人自查」→ self；其余 → student。"""
    m = p.get("follow_mode") or ""
    if m:
        return m
    lead = p.get("lead_author") or ""
    if lead in settings.SELF:
        return "self" if "本人自查" in (paper("followup", "show", p["code"]).get("action_owner") or "") else "ai"
    return "student"


def site_key(url):
    u = urlparse(url or "")
    seg = u.path.strip("/").split("/")[0].lower() if u.path.strip("/") else ""
    return (u.netloc.lower(), seg)


def login_paths(code, cur, submit_accounts):
    """台账本轮凭证 + 投稿账号登记；按论文编号匹配的算已登记，只按系统网址匹配的要实测。"""
    paths = []
    cred = paper("credentials", "show", code)
    if cred.get("sys_account") and cred.get("sys_password"):
        paths.append(("台账本轮凭证", "已保存账号和密码"))
    elif cred.get("sys_account"):
        paths.append(("台账本轮凭证", "只有账号，没有密码"))
    for a in submit_accounts:
        by_code = code in str(a.get("paper") or "").split()
        by_site = site_key(a.get("login_url")) == site_key(cur.get("site_url")) and site_key(cur.get("site_url"))[0]
        if by_code or by_site:
            how = "按编号登记" if by_code else "同系统账号，需实测能否看到本稿"
            paths.append((f"投稿账号 {a.get('browser_profile')}（{a.get('person')}）", how))
    return paths


def paper_mailboxes(code, accounts):
    out = []
    for addr, entry in accounts.items():
        for link in entry.get("author_links") or []:
            if any(str(p).split()[0] == code for p in link.get("papers") or []):
                out.append({"address": addr, "person": link.get("person"), "role": link.get("role") or "",
                            "readable": bool(entry.get("readable")), "checked": str(entry.get("checked_at") or "")[:10]})
    return out


def last_verified(code):
    ev = paper("followup", "events", code).get("events", [])
    hits = [e["occurred_at"][:10] for e in ev if VERIFIED_MARK in (e.get("text") or "") and not e.get("deleted")]
    return max(hits) if hits else None


def judge(paths, mails, verified):
    gaps = []
    if not paths:
        gaps.append("没有任何可登录路径")
    elif all("需实测" in h or "没有密码" in h for _, h in paths):
        gaps.append("登录路径只靠同系统账号推测，未确认能看到本稿")
    key = [m for m in mails if ("投稿人" in m["role"] or "通讯" in m["role"])]
    if not mails:
        gaps.append("邮箱登记里没有本篇作者邮箱")
    elif not any(m["readable"] for m in key):
        gaps.append("投稿人／系统通讯的邮箱都读不到" if key else "没有登记投稿人或通讯的邮箱")
    if not verified:
        gaps.append("从未实测登录并看到投稿记录")
    elif (date.today() - date.fromisoformat(verified)).days > VERIFY_STALE_DAYS:
        gaps.append(f"上次实测 {verified}，超过 {VERIFY_STALE_DAYS} 天")
    hard = {"没有任何可登录路径", "投稿人／系统通讯的邮箱都读不到", "邮箱登记里没有本篇作者邮箱", "没有登记投稿人或通讯的邮箱"}
    level = "红" if hard & set(gaps) else ("黄" if gaps else "绿")
    return level, gaps


def main():
    ap = argparse.ArgumentParser(description="查论文前的可查性体检（只读）")
    ap.add_argument("--days", type=int, default=30, help="学生论文无进展多少天后标记（默认 30）")
    ap.add_argument("--include-extra", action="store_true", help="其他论文（extra）也按 AI 代查体检")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    papers = paper("list")["papers"]
    submit_accounts = settings.submit_accounts()
    try:
        accounts = mailboxes.load_accounts()
    except mailboxes.MailboxError as e:
        print(f"提示：{e}；邮箱一项全部按未登记处理", file=sys.stderr)
        accounts = {}
    report = {"date": date.today().isoformat(), "self": [], "student": [], "skipped": []}

    for p in papers:
        code, cur = p["code"], p.get("current_submission") or {}
        if p["status"] in ("已录用", "撰写中", "被拒", "撤稿"):
            report["skipped"].append({"code": code, "reason": p["status"]})
            continue
        if p.get("category") == EXTRA and not a.include_extra:
            report["skipped"].append({"code": code, "reason": "其他论文"})
            continue
        mode = follow_mode(p)
        if mode == "self":
            report["skipped"].append({"code": code, "reason": "本人自查"})
            continue
        if mode == "ai":
            paths, mails, verified = login_paths(code, cur, submit_accounts), paper_mailboxes(code, accounts), last_verified(code)
            level, gaps = judge(paths, mails, verified)
            report["self"].append({"code": code, "journal": cur.get("journal"), "ms_id": cur.get("manuscript_id"),
                                   "site_url": cur.get("site_url"), "login_paths": paths, "mailboxes": mails,
                                   "last_verified": verified, "level": level, "gaps": gaps,
                                   "days_without_progress": p.get("days_without_progress")})
        else:
            owner = p.get("lead_author") or ""
            if not owner:
                plan_owner = paper("followup", "show", code).get("action_owner") or ""
                owner = f"{plan_owner}（台账未登记，取自跟进计划）" if plan_owner else "未登记"
            idle, due = p.get("days_without_progress"), p.get("revision_days_remaining")
            remind = (idle is not None and idle >= a.days) or (due is not None and due <= 14)
            report["student"].append({"code": code, "owner": owner, "mode": mode, "journal": cur.get("journal"),
                                      "days_without_progress": idle, "revision_due": p.get("revision_due_date"),
                                      "remind": remind})

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return
    print(f"# 可查性体检（{report['date']}）\n\n## AI 代查")
    for r in report["self"]:
        print(f"\n### {r['code']} [{r['level']}] {r['journal']} {r['ms_id'] or ''}")
        print("- 登录：" + ("；".join(f"{n}（{h}）" for n, h in r["login_paths"]) or "无"))
        print("- 邮箱：" + ("；".join(f"{m['person']}·{m['role']} {m['address']} {'能读' if m['readable'] else '读不到'}"
                                    for m in r["mailboxes"]) or "无"))
        print(f"- 上次实测能看到记录：{r['last_verified'] or '从未'}")
        for g in r["gaps"]:
            print(f"- ⚠️ {g}")
    print("\n## 学生或合作方跟进（不查不提醒）：" + "、".join(f"{r['code']}({r['owner']})" for r in report["student"]))
    print("\n## 不查：" + "、".join(f"{s['code']}({s['reason']})" for s in report["skipped"]))


if __name__ == "__main__":
    main()
