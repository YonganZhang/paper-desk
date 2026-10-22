#!/usr/bin/env python3
"""找台账漏登的投稿：扫本人可读邮箱（配置 always_scan）里的投稿确认信，列出信里有、台账里没有的稿号（只读）。

整篇漏登、漏登一轮（例如转投后忘了 paper submit）都能靠它兜底。每周报告会调用 scan()，把漏登的稿号放进「需要您处理」。
用法：untracked_scan.py [--days 30] [--json]。看信用 `mailboxes.py read <地址> <uid>`；补录按台账规则（新轮用 paper submit，更早的轮次加 --history）。
"""
import argparse
import imaplib
import json
import re
import sys
from datetime import date, timedelta
from email import message_from_bytes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # -I 运行时脚本目录不在 sys.path
import mailboxes  # noqa: E402
import settings  # noqa: E402

SUBJECTS = ("Submission Confirmation", "Confirming your submission", "Manuscript Received", "Manuscript ID",
            "Submission to", "successfully submitted", "has been submitted", "Acknowledg", "Confirm co-authorship",
            "verify your contribution")
# 通用稿号格式：EM（ABCD-D-YY-NNNNN）、ScholarOne（ABC-YY-NNNN / ABC-YYYY-NNNN）；
# 各刊自有格式写进配置 extra_manuscript_id_patterns
_PATTERNS = [r"[A-Z]{2,8}-D-\d{2}-\d{4,6}", r"[A-Z]{3,8}-\d{2}-\d{4,6}", r"[A-Z]{2,6}-20\d{2}-\d{4,6}"]
MS = re.compile(r"\b(" + "|".join(_PATTERNS + list(settings.CFG["extra_manuscript_id_patterns"])) + r")\b")
TITLE = re.compile(r"(?:entitled|manuscript|paper|title)[:,]?\s*(?:&quot;|\"|“)?([A-Z][^\"”&]{25,180})", re.I)


def base(ms):
    return re.sub(r"\.R\d+$", "", ms.strip().upper())


def known_ids(papers):
    ids = set()
    for p in papers:
        for s in p.get("submissions") or []:
            for part in re.split(r"[\s/;,，]+", s.get("manuscript_id") or ""):
                if part:
                    ids.add(base(part))
        notes = " ".join([p.get("notes") or ""] + [s.get("notes") or "" for s in p.get("submissions") or []])
        ids |= {base(x) for x in MS.findall(notes)}   # 台账不支持插旧轮时，历史轮稿号记在备注里
    return ids


def scan(since, papers=None, boxes=None):
    """返回 (漏登列表, 读取失败 {邮箱: 原因})。漏登每条：稿号、日期、邮箱、UID、主题、信里抓到的题目。"""
    boxes = settings.CFG["always_scan"] if boxes is None else boxes
    known = known_ids(papers if papers is not None else settings.paper("list")["papers"])
    found, errors = {}, {}
    try:
        accounts = mailboxes.load_accounts()
    except mailboxes.MailboxError as e:
        return [], {b: str(e) for b in boxes}
    for addr in boxes:
        try:
            M = mailboxes.imap_conn(mailboxes.acct(addr, accounts), addr)
            M.select("INBOX", readonly=True)
            uids = set()
            for q in SUBJECTS:
                _, d = M.uid("search", None, f'SINCE {since:%d-%b-%Y} SUBJECT "{q}"')
                uids |= set(d[0].split()) if d and d[0] else set()
            for u in sorted(uids, key=int):
                _, d = M.uid("fetch", u, "(BODY.PEEK[])")
                if not d or not isinstance(d[0], tuple):
                    continue
                m = message_from_bytes(d[0][1])
                subj = mailboxes.dh(m.get("Subject"))
                body = " ".join(mailboxes.extract_body(m).split())[:3000]
                t = TITLE.search(body)
                for ms in {base(x) for x in MS.findall(subj + " " + body)} - known:
                    found.setdefault(ms, {"ms": ms, "date": m.get("Date", "")[:25], "box": addr, "uid": u.decode(),
                                          "subject": " ".join(subj.split())[:150],
                                          "title": t.group(1).strip()[:160] if t else ""})
            M.logout()
        except (mailboxes.MailboxError, imaplib.IMAP4.error, OSError) as e:   # 一个邮箱失败不挡其他邮箱
            errors[addr] = f"{type(e).__name__}: {e}"[:200]
    return sorted(found.values(), key=lambda r: r["ms"]), errors


def main():
    ap = argparse.ArgumentParser(description="列出邮箱投稿确认信里有、台账里没有的稿号（只读）")
    ap.add_argument("--days", type=int, default=30, help="扫多少天内的信（默认 30）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    a = ap.parse_args()
    if not settings.CFG["always_scan"]:
        sys.exit("配置里 always_scan 为空：不知道该扫哪个邮箱（见 references/config.md）")
    rows, errors = scan(date.today() - timedelta(days=a.days))
    if a.json:
        print(json.dumps({"untracked": rows, "errors": errors}, ensure_ascii=False, indent=1))
        return
    print(f"# 近 {a.days} 天投稿确认信里、台账没有的稿号：{len(rows)} 个")
    for r in rows:
        print(f"- {r['ms']}｜{r['date']}｜{r['box']} UID {r['uid']}｜{r['subject']}" + (f"｜{r['title']}" if r["title"] else ""))
    for addr, e in errors.items():
        print(f"! 邮箱 {addr} 读取失败：{e}")


if __name__ == "__main__":
    main()
