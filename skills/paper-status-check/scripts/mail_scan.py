#!/usr/bin/env python3
"""一次扫完多个邮箱：按稿号、题目、中文刊名找本人跟进论文的期刊来信（只读，只取信头）。

每个邮箱只连一次，服务器端按日期过滤，信头分批取回，所有论文的关键词一起匹配。连接和凭证走同目录的 mailboxes.py。
要扫的邮箱：配置 always_scan 里的本人邮箱，加上邮箱登记里 readable=true 且 author_links 关联到本篇的邮箱。
用法：mail_scan.py P04 P10 … [--since YYYY-MM-DD] [--extra-box 地址] [--json]
不给 --since 时，从该篇当前轮投稿日前 3 天起。读正文用 `mailboxes.py read <地址> <uid>`。
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

JUNK = ("Junk", "Junk Email", "Spam", "[Gmail]/Spam", "垃圾邮件")
CJK = re.compile(r"[一-鿿]")
MAIL_ERRORS = (mailboxes.MailboxError, imaplib.IMAP4.error, OSError)


def paper_boxes(code, accounts):
    """邮箱登记里服务器能读、并关联到这篇论文的地址。"""
    out = set()
    for addr, entry in accounts.items():
        if not entry.get("readable"):
            continue
        for link in entry.get("author_links") or []:
            if any(str(x).split()[0] == code for x in link.get("papers") or []):
                out.add(addr)
    return out


def targets(codes):
    """每篇：关键词（各轮稿号、题目开头、近期中文刊名）、扫描起点、要扫的邮箱。"""
    accounts = mailboxes.load_accounts()
    out = {}
    for code in codes:
        p = settings.paper("show", code)
        subs = p.get("submissions") or []
        cur = subs[0] if subs else {}
        # 稿号精确匹配；题目取前 6 个词（作者确认信的主题只带题目，不带稿号）。英文期刊名太宽不用
        keys = {s["manuscript_id"] for s in subs if s.get("manuscript_id") and len(s["manuscript_id"]) < 30}
        title = " ".join((p.get("title") or "").split()[:6])
        if len(title) > 20:
            keys.add(title)
        elif CJK.search(title):
            keys.add(title[:12])
        since = (date.fromisoformat(cur["submit_date"]) - timedelta(days=3)) if cur.get("submit_date") \
            else date.today() - timedelta(days=90)
        # 中文刊来信主题常只有「投稿成功通知」，稿号、题目都不在主题里，要靠发件人里的刊名
        keys |= {s["journal"] for s in subs if CJK.search(s.get("journal") or "")
                 and s.get("submit_date") and date.fromisoformat(s["submit_date"]) >= since - timedelta(days=60)}
        boxes = set(settings.CFG["always_scan"]) | paper_boxes(code, accounts)
        out[code] = {"keys": sorted(keys), "since": since, "boxes": boxes}
    return accounts, out


def scan_box(accounts, addr, since, folders):
    M = mailboxes.imap_conn(mailboxes.acct(addr, accounts), addr)
    typ, lst = M.list()
    names = [l.decode(errors="ignore").rsplit(' "', 1)[-1].strip('"') for l in (lst or []) if l]
    rows = []
    for folder in ["INBOX"] + [n for n in names if n in folders]:
        try:
            M.select(f'"{folder}"', readonly=True)
        except mailboxes.MailboxError:
            if folder == "INBOX":
                raise
            continue                        # 垃圾箱名字因服务器而异，打不开就跳过
        typ, data = M.uid("search", None, "SINCE", since.strftime("%d-%b-%Y"))
        uids = (data[0] or b"").split()
        for i in range(0, len(uids), 200):
            chunk = b",".join(uids[i:i + 200])
            typ, d = M.uid("fetch", chunk, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO DATE)])")
            d = d or []
            for j, part in enumerate(d):
                if not isinstance(part, tuple):
                    continue
                # 多数服务器把 UID 放在信头前；Outlook 放在信头之后的下一段
                tail = d[j + 1] if j + 1 < len(d) and isinstance(d[j + 1], bytes) else b""
                hit = re.search(rb"UID (\d+)", part[0]) or re.search(rb"UID (\d+)", tail)
                uid = hit.group(1).decode() if hit else "?"
                m = message_from_bytes(part[1])
                rows.append({"box": addr, "folder": folder, "uid": uid, "date": m.get("Date", "")[:31],
                             "from": mailboxes.dh(m.get("From"))[:60],
                             "subject": " ".join(mailboxes.dh(m.get("Subject")).split())[:160]})
    M.logout()
    return rows


def scan_all(codes, since=None, extra_boxes=()):
    """扫多篇论文的来信，返回 (每篇的关键词/起点/邮箱, 每篇命中的信, 读取失败的邮箱)。weekly_report.py 也调用它。"""
    accounts, tg = targets(codes)
    boxes = {}
    for code, t in tg.items():
        t["boxes"] |= set(extra_boxes)
        if since:
            t["since"] = since
        for b in t["boxes"]:
            boxes[b] = min(boxes.get(b, t["since"]), t["since"])
    found = {c: [] for c in tg}
    errors = {}
    for addr, start in sorted(boxes.items()):
        try:
            rows = scan_box(accounts, addr, start, JUNK)
        except MAIL_ERRORS as e:            # 一个邮箱失败不挡其他邮箱，结果里写明
            errors[addr] = f"{type(e).__name__}: {e}"[:160]
            continue
        for code, t in tg.items():
            if addr not in t["boxes"]:
                continue
            for r in rows:
                text = r["subject"] + " " + r["from"]
                if any(k.lower() in text.lower() for k in t["keys"]):
                    found[code].append(r)
    return tg, found, errors


def main():
    ap = argparse.ArgumentParser(description="按稿号批量扫期刊来信（只读）")
    ap.add_argument("codes", nargs="+")
    ap.add_argument("--since")
    ap.add_argument("--extra-box", action="append", default=[])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    tg, found, errors = scan_all(a.codes, date.fromisoformat(a.since) if a.since else None, a.extra_box)
    if a.json:
        print(json.dumps({"found": found, "errors": errors}, ensure_ascii=False, indent=1, default=str))
        return
    for code, t in tg.items():
        print(f"\n## {code}  关键词 {t['keys']}  自 {t['since']}  邮箱 {len(t['boxes'])} 个")
        for r in sorted(found[code], key=lambda r: r["date"]):
            print(f"- {r['date'][:16]} | {r['box']}/{r['folder']} uid {r['uid']} | {r['from'][:28]} | {r['subject']}")
        if not found[code]:
            print("- 没有命中")
    for addr, e in errors.items():
        print(f"\n⚠️ {addr} 读取失败：{e}")


if __name__ == "__main__":
    main()
