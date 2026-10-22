#!/usr/bin/env python3
"""每周投稿情况追踪：读台账、扫近一周期刊来信、读投稿系统列表页和作者确认页，生成中文报告并按配置发信。

只读：不点稿件按钮、不回信、不改投稿状态；系统页读到时给台账记一条 check-in（--no-checkin 关掉）。
范围：跟进方式为 ai 的在投论文；self（本人自查）列在「不查」；student／watch／partner 只列编号，watch 另提醒返修截止。
发件人、收件人、主题、称呼、时区、存档目录都在配置的 report 段（references/config.md）。定时运行见 references/weekly-report.md。
用法：weekly_report.py [--send] [--test] [--no-browser] [--no-checkin] [--days 7]
不加 --send 只打印和存档；--test 在邮件主题前加【测试】。存档：<out_dir>/<日期>.md 与 .json。
"""
import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # -I 运行时脚本目录不在 sys.path
import access_audit as audit  # noqa: E402
import mail_scan as scan  # noqa: E402
import mailboxes  # noqa: E402
import settings  # noqa: E402
import untracked_scan as track  # noqa: E402

CFG, R = settings.CFG, settings.CFG["report"]
TZ = settings.tz()
WORK = settings.WORK                                     # playwright-cli 会往当前目录写快照，固定到工作目录
OUT = Path(R["out_dir"]).expanduser()
BROWSER = settings.PAPER_BROWSER
SKIP_STATUS = ("已录用", "撰写中", "被拒", "撤稿")
# 确认信写明「合著者全部确认前不进入编辑流程」的刊（references/systems.md）；其他刊的未确认只作提示
BLOCKING_CONFIRM = set(CFG["blocking_confirm_journals"])
NEAR_ACCEPTANCE = set(CFG["near_acceptance_stages"])
# 例行信：回执、注册、作者确认、编辑接手。其余期刊来信都请用户看一眼，宁可多报
ROUTINE = re.compile(r"confirming your submission|verify your contribution|confirm co-?authorship|manuscript received|"
                     r"receipt of|submission to .+ - |editor handles|registration|account|注册|投稿成功|收稿回执", re.I)
EM_MS = re.compile(r"^[A-Z]{2,}-D-\d{2}-\d{4,6}$")
JS_PAGE = r"""() => { const docs = [document];
  for (const f of document.querySelectorAll('iframe, frame')) { try { if (f.contentDocument) docs.push(f.contentDocument); } catch (e) {} }
  const rows = [], pdf = [];
  for (const d of docs) {
    for (const tr of d.querySelectorAll('tr')) { const c = Array.from(tr.cells).map(x => x.innerText.trim()); if (c.length > 1) rows.push(c); }
    const h = d.documentElement ? d.documentElement.innerHTML : '';
    for (const m of h.matchAll(/viewAuthorPDFs\((\d+),\s*'([^']+)',\s*\d+,\s*'(\{[^}]+\})'/g)) pdf.push([m[1], m[2], m[3]]);
  }
  return JSON.stringify({url: location.href, title: document.title, rows: rows.slice(0, 300), pdf,
    text: docs.map(d => d.body ? d.body.innerText : '').join('\n').slice(0, 8000)}); }"""
paper = settings.paper


def now():
    return datetime.now().astimezone(TZ)


def label(p):
    t, cn = (p.get("title") or "").strip(), (p.get("title_cn") or "").strip()
    return f"{p['code']}《{t or cn}》" + (f"（{cn}）" if cn and t and cn != t else "")


def cur(p):
    return p.get("current_submission") or {}


# ---------- 范围 ----------

def classify(papers):
    mine, others, skipped = [], [], []
    for p in papers:
        if p["status"] in SKIP_STATUS:
            continue
        mode = audit.follow_mode(p)          # 跟进方式只认台账 follow_mode；未登记时按负责人推（见 access_audit）
        if mode == "self":
            skipped.append((p, "本人自查"))
        elif mode == "ai":
            mine.append(p)
        else:
            others.append(p)
    return mine, others, skipped


# ---------- 投稿系统（只读） ----------

def pw(sid, *args, timeout=90):
    return subprocess.run([settings.PWCLI, f"-s={sid}", *args], capture_output=True, text=True,
                          timeout=timeout, cwd=WORK, stdin=subprocess.DEVNULL)


def busy(profile):
    """别的会话正在用这个投稿人 profile 时不碰：goto 会把对方的页面跳走。"""
    if pw(f"submit-{profile}", "eval", "() => 1", timeout=30).returncode == 0:
        return True
    pattern = re.escape(str(settings.SUBMIT_HOME / "profiles" / profile)) + "( |$)"
    return subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0


def read_page(sid, url, want):
    pw(sid, "goto", url)
    data = {}
    for _ in range(3):                      # EM 列表在 iframe 里，晚几秒才出来
        out = pw(sid, "eval", JS_PAGE).stdout
        m = re.search(r"### Result\n(.*?)\n### Ran", out, re.S)
        if m:
            data = json.loads(json.loads(m.group(1).strip()))
            if want(data):
                return data
        time.sleep(4)
    return data


def login_lost(data):
    head = " ".join([data.get("url", ""), data.get("title", ""), data.get("text", "")[:3000]])
    return bool(re.search(r"login|log in|sign in|username and password", head, re.I))


def ref_of(snap, pattern):
    m = re.search(pattern + r'[^\n]*?\[ref=([a-z0-9]+)\]', snap, re.I)
    return m.group(1) if m else None


def login_page(sid, base):
    pw(sid, "goto", base + "login.ashx")
    snap = ""
    for _ in range(3):                      # 登录框在 iframe 里，晚几秒才出来
        time.sleep(3)
        snap = pw(sid, "snapshot").stdout
        if re.search(r'textbox "username"|Elsevier account login', snap, re.I):
            break
    return snap


def logged_in(sid, tries=8):
    """登录后会跳转好几次（单点登录尤其慢），看到主菜单才算登上。"""
    for _ in range(tries):
        time.sleep(4)
        m = re.search(r"### Result\n(.*?)\n###", pw(sid, "eval", "() => document.title").stdout, re.S)
        if m and "Main Menu" in m.group(1):
            return True
    return False


def em_login(sid, base, acct):
    """EM 登录失效时自己登，不叫用户登录。login=elsevier-sso 的点 Elsevier account login，用 profile 里保存的
    Elsevier ID 登录态；登记了用户名和密码 secret 名的填用户名和 secret 名，浏览器配置替换成真值、输出打码。
    密码每次运行只试一次，避免把账号试锁；单点登录不涉及密码，网络中断时再点一次。"""
    key, user = str(acct.get("password_key") or ""), acct.get("username") or ""
    if acct.get("login") == "elsevier-sso":
        for _ in range(2):
            b = ref_of(login_page(sid, base), r'button "Elsevier account login"')
            if not b:
                return False
            pw(sid, "click", b, timeout=120)
            if logged_in(sid):
                return True
        return False
    if re.fullmatch(r"[A-Z][A-Z0-9_]+", key) and user:
        snap = login_page(sid, base)
        alt = ref_of(snap, r'(?:button|link) "Alternatively, use your username and password"')
        if alt:                             # Elsevier 刊默认只显示单点登录，用户名密码框要先展开
            pw(sid, "click", alt)
            time.sleep(2)
            snap = pw(sid, "snapshot").stdout
        u, p, b = (ref_of(snap, r'textbox "username"'), ref_of(snap, r'textbox "password"'),
                   ref_of(snap, r'button "Author Login"'))
        if not (u and p and b):
            return False
        pw(sid, "fill", u, user)
        pw(sid, "fill", p, key)
        pw(sid, "click", b)
        return logged_in(sid)
    return False


def em_account(accounts, prof, base):
    for a in accounts:
        if a.get("browser_profile") == prof and (a.get("login_url") or "").startswith(base):
            return a
    return {}


def em_list(data):
    rows = {}
    for c in data.get("rows", []):
        for i, cell in enumerate(c):
            if EM_MS.match(cell) and len(c) >= i + 4:
                rows[cell] = {"status": c[-1], "status_date": re.sub(r"\s+\d{1,2}:\d.*$", "", c[-2])}
    return rows


def em_confirmations(data):
    seen = {}
    for c in data.get("rows", []):
        conf = next((x for x in c if re.match(r"^(Yes|No Response|No\b|Declined)", x)), None)
        if len(c) < 4 or not c[0].isdigit() or not conf:
            continue
        email = next((m.group(0) for x in c for m in [re.search(r"[\w.+-]+@[\w.-]+\w", x)] if m), "")
        seen[c[1]] = {"name": c[1], "email": email, "confirmed": " ".join(conf.split())}
    return list(seen.values())


def snapp_status(data):
    lines = [l.strip() for l in data.get("text", "").splitlines() if l.strip()]
    if "CURRENT STATUS" not in lines:
        return None
    status = lines[lines.index("CURRENT STATUS") + 1]
    doing = [lines[k - 1] for k in range(1, len(lines)) if lines[k] == "- in progress"]
    return status + (f"（进行中：{'、'.join(doing)}）" if doing else "")


def system_pages(mine, accounts):
    """从投稿账号登记取要读的页：EM 读该账号的列表页（一页列出账号下全部稿件），Springer 读稿件详情页。"""
    codes = {p["code"]: p for p in mine}
    pages = {}
    for a in accounts:
        prof, system = a.get("browser_profile") or "", a.get("system") or ""
        hits = [t for t in str(a.get("paper") or "").split() if t in codes]
        if not hits or not prof:
            continue
        if "Editorial Manager" in system:
            base = re.match(r"https://www\.editorialmanager\.com/[^/]+/", a.get("login_url") or "")
            if base:
                pages.setdefault(prof, {}).setdefault(("em", base.group(0)), set()).update(hits)
        elif "Springer" in system:
            for c in hits:
                if cur(codes[c]).get("manuscript_id"):
                    pages.setdefault(prof, {}).setdefault(("snapp", cur(codes[c])["manuscript_id"]), set()).add(c)
    return pages


def check_systems(mine, ms_code):
    result, problems = {}, []
    WORK.mkdir(parents=True, exist_ok=True)
    accounts = settings.submit_accounts()
    for prof, targets in system_pages(mine, accounts).items():
        if busy(prof):
            problems.append(f"投稿人浏览器 {prof} 正被别的会话使用，本次跳过：" + "、".join(sorted(set().union(*targets.values()))))
            continue
        sid = f"submit-{prof}"
        r = subprocess.run(["bash", str(BROWSER), "open", prof, "about:blank"], capture_output=True, text=True,
                           timeout=120, stdin=subprocess.DEVNULL)
        if r.returncode:
            problems.append(f"投稿人浏览器 {prof} 打不开：{(r.stderr or r.stdout).strip()[:160]}")
            continue
        try:
            for (kind, key), codes in targets.items():
                if kind == "snapp":
                    data = read_page(sid, f"https://submission.springernature.com/submission-details/{key}",
                                     lambda d: "CURRENT STATUS" in d.get("text", ""))
                    st = snapp_status(data)
                    for c in codes:
                        result[c] = {"system": "Springer Nature", "status": st} if st else \
                            {"system": "Springer Nature", "error": "登录失效" if login_lost(data) else "页面没读到状态"}
                    continue
                data = read_page(sid, key + "default2.aspx", lambda d: bool(em_list(d)))
                rows = em_list(data)
                if not rows and login_lost(data):
                    em_login(sid, key, em_account(accounts, prof, key))
                if not rows:                # 刚登录或框架停在主菜单时 default2 不显示列表，直接开 Submissions Being Processed
                    data = read_page(sid, key + "auth_pendSubmissions.asp?currentPage=1", lambda d: bool(em_list(d)))
                    rows = em_list(data)
                if not rows:
                    for c in codes:
                        result[c] = {"system": "Editorial Manager", "error": "登录失效" if login_lost(data) else "列表页没读到稿件"}
                    continue
                pdf = {ms: (doc, msid) for doc, ms, msid in data.get("pdf", [])}
                for ms, row in rows.items():
                    c = ms_code.get(ms)
                    if not c or c not in {p["code"] for p in mine}:
                        continue
                    row = {"system": "Editorial Manager", "ms": ms, **row}
                    if ms in pdf:
                        doc, msid = pdf[ms]
                        sd = read_page(sid, f"{key}ContributingAuthorStatus.aspx?docID={doc}&msid={msid}&revision=0",
                                       lambda d: bool(em_confirmations(d)))
                        row["confirm"] = em_confirmations(sd)
                    result[c] = row
                for c in codes - set(result):
                    result[c] = {"system": "Editorial Manager", "error": "列表页里没有本稿（可能挂在别的账号下）"}
        finally:
            subprocess.run(["bash", str(BROWSER), "stop", prof], capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
    return result, problems


# ---------- 邮件 ----------

def local_time(raw):
    try:
        return parsedate_to_datetime(raw).astimezone(TZ)
    except (TypeError, ValueError):
        return None


def mails(mine, since):
    _, found, errors = scan.scan_all([p["code"] for p in mine], since)
    out = {}
    floor = datetime.min.replace(tzinfo=timezone.utc)
    for code, rows in found.items():
        merged = {}
        for r in rows:                      # 同一通知常同时发给几位作者、在几个邮箱里各有一份
            t = local_time(r["date"])
            m = merged.setdefault((r["subject"], f"{t:%m-%d %H:%M}" if t else r["date"]), {**r, "boxes": []})
            m["boxes"].append(r["box"])
        out[code] = sorted(merged.values(), key=lambda r: local_time(r["date"]) or floor)
    return out, errors


# ---------- 邮箱混用提醒 ----------

def mailbox_reminders(papers, accounts):
    """邮箱登记里标了 remind: near-acceptance 的在投例外：相关稿件进入小修或已录用时，提醒用户把邮箱改回规定的人。"""
    by = {p["code"]: p for p in papers}
    out = []
    for addr, a in accounts.items():
        for x in a.get("exceptions") or []:
            if x.get("remind") != "near-acceptance":
                continue
            hit = [by[c] for c in x.get("papers", []) if c in by
                   and (by[c].get("review_stage") in NEAR_ACCEPTANCE or by[c].get("status") == "已录用")]
            if hit:
                out.append(f"邮箱混用待清理：{'、'.join(label(p) for p in hit)} 已到"
                           f"{'／'.join(sorted({p.get('review_stage') or p['status'] for p in hit}))}。{addr} 在这些稿件里登记的是 "
                           f"{x.get('person', '?')}（{x.get('scope', '')}）。{x.get('reason', '')}")
    return out


# ---------- 报告 ----------

def compose(today, mine, others, skipped, sysres, problems, mailres, mail_errors, prev, since, everyone, accounts,
            untracked=(), watched=frozenset()):
    by = {p["code"]: p for p in mine}
    actions, changes, lines = [], [], []

    for code, r in sysres.items():
        p = by[code]
        pending = [a for a in r.get("confirm", []) if not a["confirmed"].startswith("Yes")]
        if pending and cur(p).get("journal") in BLOCKING_CONFIRM:
            who = "、".join(f"{a['name']}（{a['email']}）" for a in pending)
            actions.append(f"{label(p)}｜{cur(p).get('journal')}｜{r.get('ms')}\n"
                           f"   还没确认作者身份：{who}。该刊要求全部合著者确认后才进入编辑流程。\n"
                           f"   请他们在邮箱里搜主题「Please verify your contribution to」加论文题目开头几个词的邮件"
                           f"（发件人是 {cur(p).get('journal')}，地址在 editorialmanager.com 域名下，认准稿号 {r.get('ms')}），"
                           f"点信里的「Yes, I am affiliated」，网页打开后按「Submit to Publication」，看到 Thank you for verifying 才算完成。")
        old = (prev.get("system") or {}).get(code, {})
        if old.get("status") and r.get("status") and old["status"] != r["status"]:
            changes.append(f"{label(p)}：{old['status']} → {r['status']}")

    for code, rows in mailres.items():
        # 只讲旧轮稿号的信（旧稿关闭、客服工单）照列在第三节，不算待办：旧轮已转投，由用户决定是否再管
        old_ms = {s["manuscript_id"] for s in by[code].get("submissions") or []
                  if s.get("manuscript_id") and s.get("manuscript_id") != cur(by[code]).get("manuscript_id")}
        # 中文刊来信常不带稿号，只在发件人里带刊名：发件人是旧轮期刊、不是当前期刊的，也算旧轮来信
        cur_journal = cur(by[code]).get("journal") or ""
        old_journals = {s["journal"] for s in by[code].get("submissions") or []
                        if s.get("journal") and s["journal"] != cur_journal and re.search(r"[一-鿿]", s["journal"])}
        for m in rows:
            if not ROUTINE.search(m["subject"]) and not any(ms in m["subject"] for ms in old_ms) \
                    and not any(j in m["from"] for j in old_journals):
                t = local_time(m["date"])
                actions.append(f"{label(by[code])}\n   {t:%m-%d %H:%M} 收到「{m['subject']}」（{m['from']}，"
                               f"收件邮箱 {'、'.join(sorted(set(m['boxes'])))}），请看信。" if t else
                               f"{label(by[code])}\n   收到「{m['subject']}」（{m['from']}），请看信。")

    for p in mine:
        left = p.get("revision_days_remaining")
        if left is not None and left <= 21:
            actions.append(f"{label(p)}：返修截止 {p.get('revision_due_date')}，还剩 {left} 天。")
    for p in others:                        # 学生改、但要求 AI 盯着的（follow_mode=watch）：只提醒返修截止
        left = p.get("revision_days_remaining")
        if p["code"] in watched and left is not None and left <= 21:
            actions.append(f"{label(p)}：返修截止 {p.get('revision_due_date')}，还剩 {left} 天"
                           f"（{p.get('lead_author') or '学生'}在改，请确认进度）。")
    actions += mailbox_reminders(everyone, accounts)
    for r in untracked:                     # 台账没有这个稿号：多半是漏登了整篇或一轮
        actions.append(f"台账漏登？{r['ms']}｜{r['subject']}" + (f"｜{r['title']}" if r["title"] else "")
                       + f"\n   {r['date'][:16]} 收到投稿确认信（{r['box']} UID {r['uid']}），台账里没有这个稿号。请确认要不要建档或补一轮。")

    stamp = now()
    lines.append(f"{R['greeting']}\n")
    lines.append(f"这是本周投稿论文情况追踪（{since:%m-%d} 至 {today:%m-%d}），由{R['sender_label']}在 "
                 f"{stamp:%Y-%m-%d %H:%M}（{stamp.tzname()}）自动生成。\n")
    lines.append(f"一、需要您处理（{len(actions)} 项）")
    lines += [f"{i}. {a}" for i, a in enumerate(actions, 1)] or ["本周没有需要您处理的事。"]

    lines.append(f"\n二、本周系统状态变化（{len(changes)} 项）")
    lines += [f"- {c}" for c in changes] or (["- 没有变化。"] if prev else ["- 第一次生成报告，下周起和本周对比。"])

    total = sum(len(v) for v in mailres.values())
    lines.append(f"\n三、近 {(today - since).days} 天的期刊来信（{total} 封）")
    for code, rows in mailres.items():
        if rows:
            lines.append(label(by[code]))
            for m in rows:
                t = local_time(m["date"])
                lines.append(f"   - {t:%m-%d %H:%M}｜{m['from']}｜{m['subject']}｜收件邮箱 {'、'.join(sorted(set(m['boxes'])))}"
                             if t else f"   - {m['from']}｜{m['subject']}")
    if not total:
        lines.append("- 没有新来信。")

    lines.append("\n四、各篇论文当前状态")
    lines.append("【AI 代查】")
    for p in mine:
        c, r = cur(p), sysres.get(p["code"], {})
        if r.get("status"):
            st = f"系统显示 {r['status']}" + (f"（{r['status_date']}）" if r.get("status_date") else "")
            pend = [a["name"] for a in r.get("confirm", []) if not a["confirmed"].startswith("Yes")]
            if r.get("confirm"):
                st += f"；合著者确认 {len(r['confirm']) - len(pend)}/{len(r['confirm'])}"
            if pend:
                st += f"（未确认：{'、'.join(pend)}" + ("）" if c.get("journal") in BLOCKING_CONFIRM else "，该刊不卡流程）")
        else:
            st = f"台账状态 {p['status']}" + (f"／{p['review_stage']}" if p.get("review_stage") and p["review_stage"] != "未标注" else "") \
                + "（系统未自动查，见第五节）"
        lines.append(f"- {label(p)}\n   {c.get('journal') or '—'}｜稿号 {c.get('manuscript_id') or '暂无'}｜{st}｜已投 {p.get('days_since_current_submit')} 天"
                     + (f"｜返修截止 {p['revision_due_date']}" if p.get("revision_due_date") else ""))
    if others:                              # 学生或合作方自己管，不查不提醒，只列名字备查
        lines.append("【学生或合作方跟进，不查】" + "；".join(f"{p['code']}（{p.get('lead_author') or '跟进人未登记'}）" for p in others))
    if skipped:
        lines.append("【不查】" + "；".join(f"{label(p)}（{why}）" for p, why in skipped))

    lines.append("\n五、本次没查到的")
    gaps = [f"- {label(by[c])}：{r['system']} {r['error']}（已按账号登记自动登录，仍没读到）。" for c, r in sysres.items() if r.get("error")]
    gaps += [f"- {label(p)}：投稿系统没有接入自动查询（{cur(p).get('journal')}），只看了邮件。" for p in mine if p["code"] not in sysres]
    gaps += [f"- {x}" for x in problems] + [f"- 邮箱 {a} 读取失败：{e}" for a, e in mail_errors.items()]
    lines += gaps or ["- 无。"]
    lines.append(f"\n——\n本邮件由{R['sender_label']}{R['schedule_label']}自动发送（paper-status-check 每周报告）。"
                 "全程只读，不点任何稿件按钮，不回复期刊邮件。")
    return "\n".join(lines), actions, changes


def main():
    ap = argparse.ArgumentParser(description="每周投稿情况追踪报告（只读）")
    ap.add_argument("--send", action="store_true", help="按配置 report.from / report.to 发信；不加只打印和存档")
    ap.add_argument("--test", action="store_true", help="邮件主题前加【测试】")
    ap.add_argument("--no-browser", action="store_true", help="不读投稿系统页面")
    ap.add_argument("--no-checkin", action="store_true", help="不往台账记 check-in")
    ap.add_argument("--days", type=int, default=7, help="扫多少天内的来信（默认 7）")
    a = ap.parse_args()
    if a.send and not (R["from"] and R["to"]):
        sys.exit("--send 需要配置 report.from 和 report.to（见 references/config.md）")

    today = now().date()
    since = today - timedelta(days=a.days)
    data = paper("list")["papers"]
    try:
        accounts = mailboxes.load_accounts()
    except mailboxes.MailboxError as e:
        sys.exit(str(e))
    ms_code = {s["manuscript_id"]: p["code"] for p in data for s in p.get("submissions") or [] if s.get("manuscript_id")}
    mine, others, skipped = classify(data)
    sysres, problems = ({}, []) if a.no_browser else check_systems(mine, ms_code)
    mailres, mail_errors = mails(mine, since)
    untracked, track_errors = track.scan(since, data)
    if not CFG["always_scan"]:
        problems.append("配置 always_scan 为空：本次没查台账漏登，也没扫本人邮箱")
    mail_errors.update({k: f"查漏登时{v}" for k, v in track_errors.items() if k not in mail_errors})

    OUT.mkdir(parents=True, exist_ok=True)
    prevs = sorted(f for f in OUT.glob("*.json") if f.stem < today.isoformat())
    prev = json.loads(prevs[-1].read_text(encoding="utf-8")) if prevs else {}
    watched = {p["code"] for p in others if audit.follow_mode(p) == "watch"}
    body, actions, changes = compose(today, mine, others, skipped, sysres, problems, mailres, mail_errors, prev, since, data,
                                     accounts, untracked, watched)
    subject = ("【测试】" if a.test else "") + R["subject"].format(date=today.isoformat())

    (OUT / f"{today}.md").write_text(f"# {subject}\n\n{body}\n", encoding="utf-8")
    (OUT / f"{today}.json").write_text(json.dumps({"date": str(today), "system": sysres, "actions": actions, "changes": changes,
                                                   "mails": mailres, "mail_errors": mail_errors, "problems": problems},
                                                  ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if not a.no_checkin:
        for code, r in sysres.items():
            if r.get("status"):
                note = f"[每周自动查 {today}] {r['system']}：{r['status']}" + (f"（{r['status_date']}）" if r.get("status_date") else "")
                if r.get("confirm"):
                    pend = [x["name"] for x in r["confirm"] if not x["confirmed"].startswith("Yes")]
                    note += f"；合著者确认 {len(r['confirm']) - len(pend)}/{len(r['confirm'])}" + (f"，未确认 {'、'.join(pend)}" if pend else "")
                c = subprocess.run([*settings.PAPER_CMD, "check-in", code, "--note", note], capture_output=True, text=True,
                                   stdin=subprocess.DEVNULL)
                if c.returncode:
                    print(f"警告：{code} check-in 失败：{c.stderr.strip()[:160]}", file=sys.stderr)
    print(f"主题：{subject}\n\n{body}")
    if a.send:
        to = R["to"] if isinstance(R["to"], list) else [R["to"]]
        try:
            mailboxes.send(R["from"], to, subject, body, accounts)
        except (mailboxes.MailboxError, OSError) as e:   # 含 SMTP 错误；发信失败要让定时任务以非零退出，日志里看得到
            sys.exit(f"发信失败：{type(e).__name__}: {e}")
        print(f"已发送 → {', '.join(to)}")


if __name__ == "__main__":
    main()
