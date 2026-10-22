#!/usr/bin/env python3
"""论文邮箱登记与收发：按 JSON 配置连 IMAP（只读）/ SMTP（须确认），并维护「邮箱 → 人 → 论文」登记。

整个仓库的邮箱能力都从这里来：paper-status-check 的 mail_scan / untracked_scan / weekly_report / reminders
用 importlib 按相对路径加载本文件；也能单独当命令用。

配置：环境变量 PAPER_MAILBOXES，默认 ~/.config/paper-desk/mailboxes.json；示例 assets/mailboxes.example.json，字段见 references/registry.md。
投稿账号登记：$PAPER_SUBMIT_HOME/accounts.json（与 paper-submit 共用，默认 ~/.local/share/paper-submit/accounts.json）。
凭证只从配置指定的来源取：password_env（环境变量名）、password_cmd（命令，stdout 为密码），
或 auth=xoauth2 + token_cmd（命令，stdout 为 OAuth2 access token；续期由你的命令负责，本模块不实现 OAuth 流程）。

用法（python3 -I mailboxes.py <命令>）：
  list                                               列出已登记邮箱（不联网、不取凭证）
  check <地址>                                        实测 IMAP 登录并只读打开 INBOX；通过后可把配置里该条标 "readable": true
  inbox <地址> [--limit 20] [--folder INBOX]           最近邮件信头（新的在前）
  search <地址> [--subject S] [--from F] [--body B] [--since YYYY-MM-DD] [--limit 50]
                                                     服务器端 IMAP 搜索；中文关键词走 CHARSET UTF-8
  read <地址> <uid> [--folder INBOX]                   读一封信（不标已读）
  links <地址> <uid> [--folder INBOX]                  列出正文里的链接（验证、确认链接）；只打印，不打开
  send <发件地址> --to A[,B] [--cc C] --subject S (--body T | --body-file F) [--confirm]   不加 --confirm 只预览
  usage <地址>                                        这个邮箱登记给了谁、哪些论文、哪些投稿系统账号
  audit                                              检查登记冲突（一人一箱、关键邮箱可读、用途相符）
  link <地址> --paper P01 --person 姓名 [--role 作者]    在 author_links 登记（写回前备份旧文件）
  unlink <地址> --paper P01 [--person 姓名] [--role R]   取消登记（写回前备份旧文件）
inbox / search / links / usage / audit 可加 --json。
退出码：0 成功；1 连接/凭证/配置失败；2 参数错误；3 违反登记规则（audit 有必须处理项、link 被拒）。
"""
import argparse
import base64
import html
import imaplib
import json
import os
import re
import shutil
import smtplib
import ssl
import stat
import subprocess
import sys
from datetime import date, datetime
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse

NETEASE_HOSTS = ("163.com", "126.com", "yeah.net")   # 网易登录后要先发 IMAP ID，否则 SELECT 报 Unsafe Login
KEY_ROLES = ("通讯", "投稿人")                         # 这两种角色的邮箱必须服务器能读
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


class MailboxError(RuntimeError):
    """配置、凭证或服务器返回的错误。调用方按邮箱分别处理，一个失败不挡其他。"""


class RuleViolation(MailboxError):
    """登记违反一人一箱等规则（退出码 3）。"""


# ---------- 配置 ----------

def config_path():
    return Path(os.environ.get("PAPER_MAILBOXES") or "~/.config/paper-desk/mailboxes.json").expanduser()


def _load_raw():
    """返回 (路径, 整个 JSON, 邮箱映射)。邮箱映射是 JSON 里的同一个 dict，改它再 _save_raw 即写回。"""
    p = config_path()
    if not p.exists():
        raise MailboxError(f"缺邮箱配置 {p}（示例见 assets/mailboxes.example.json）")
    data = json.loads(p.read_text(encoding="utf-8"))
    boxes = data.get("mailboxes", data) if isinstance(data, dict) else None
    if not isinstance(boxes, dict):
        raise MailboxError(f"{p} 顶层应为 {{地址: 配置}} 或 {{\"mailboxes\": {{…}}}}")
    return p, data, boxes


def _real(boxes):
    return {k: v for k, v in boxes.items() if not k.startswith("_")}   # 以 _ 开头的键是注释


def load_accounts():
    """返回 {地址: 配置}。配置文件顶层可以直接是这个映射，也可以是 {"mailboxes": {…}}。"""
    return _real(_load_raw()[2])


def _save_raw(p, data):
    """先把旧文件复制成 <名>.bak-<时间>（保留权限），再原子替换。返回备份路径。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak, n = p.with_name(f"{p.name}.bak-{stamp}"), 1
    while bak.exists():
        bak, n = p.with_name(f"{p.name}.bak-{stamp}-{n}"), n + 1
    shutil.copy2(p, bak)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, stat.S_IMODE(p.stat().st_mode))
    os.replace(tmp, p)
    return bak


def submit_accounts_path():
    return Path(os.environ.get("PAPER_SUBMIT_HOME") or "~/.local/share/paper-submit").expanduser() / "accounts.json"


def load_submit_accounts():
    p = submit_accounts_path()
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise MailboxError(f"{p} 应为 JSON 数组（每个投稿系统账号一条）")
    return data


def acct(addr, accounts=None):
    a = (accounts if accounts is not None else load_accounts()).get(addr)
    if not a:
        raise MailboxError(f"未登记邮箱 {addr}")
    return a


# ---------- 凭证与连接 ----------

def _host_port(s, default_port):
    host, _, port = (s or "").partition(":")
    if not host:
        raise MailboxError("缺服务器地址")
    return host, int(port or default_port)


def _run(cmd, what):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise MailboxError(f"{what} 命令 30 秒没有返回") from None
    v = (r.stdout or "").strip()
    if r.returncode or not v:
        raise MailboxError(f"{what} 命令没有给出值（退出码 {r.returncode}）")
    return v


def secret(a):
    """取密码：password_env 优先，其次 password_cmd。真值只留在内存里。"""
    env = a.get("password_env")
    if env:
        v = os.environ.get(env, "")
        if v:
            return v
        if not a.get("password_cmd"):
            raise MailboxError(f"环境变量 {env} 为空")
    if a.get("password_cmd"):
        return _run(a["password_cmd"], "password_cmd")
    raise MailboxError("没有配置凭证来源（password_env / password_cmd / auth=xoauth2+token_cmd）")


def _xoauth2(a, user):
    if not a.get("token_cmd"):
        raise MailboxError("auth=xoauth2 需要 token_cmd")
    return f"user={user}\x01auth=Bearer {_run(a['token_cmd'], 'token_cmd')}\x01\x01"


def imap_conn(a, addr):
    """登录 IMAP（SSL），返回连接。select() 失败时抛 MailboxError，不静默返回空结果。"""
    host, port = _host_port(a.get("imap"), 993)
    user = a.get("username") or addr
    M = imaplib.IMAP4_SSL(host, port, timeout=30)
    if a.get("auth") == "xoauth2":
        M.authenticate("XOAUTH2", lambda _: _xoauth2(a, user).encode())
    else:
        M.login(user, secret(a))
    if host.endswith(NETEASE_HOSTS):
        imaplib.Commands.setdefault("ID", ("AUTH", "SELECTED"))
        M._simple_command("ID", '("name" "paper-desk" "version" "1.0" "vendor" "paper-desk")')
    real_select = M.select

    def select(mailbox="INBOX", readonly=False):
        typ, data = real_select(mailbox, readonly)
        if typ != "OK":
            raise MailboxError(f"打开 {mailbox} 失败：{data}")
        return typ, data

    M.select = select  # type: ignore[method-assign]
    return M


def _quote(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _open(addr, folder="INBOX"):
    M = imap_conn(acct(addr), addr)
    M.select(_quote(folder), readonly=True)
    return M


# ---------- 读信 ----------

def dh(raw):
    """解码 MIME 编码的信头。"""
    try:
        return str(make_header(decode_header(raw or "")))
    except (ValueError, LookupError, UnicodeDecodeError):
        return raw or ""


def hdr(M, uid):
    typ, d = M.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO DATE)])")
    if not d or not isinstance(d[0], tuple):
        return None
    m = message_from_bytes(d[0][1])
    return {"uid": uid.decode() if isinstance(uid, bytes) else str(uid), "from": dh(m.get("From")),
            "to": dh(m.get("To")), "subject": dh(m.get("Subject")), "date": m.get("Date", "")}


def fetch_message(M, uid):
    typ, d = M.uid("fetch", str(uid).encode(), "(BODY.PEEK[])")
    if not d or not isinstance(d[0], tuple):
        raise MailboxError(f"没有 uid {uid}")
    return message_from_bytes(d[0][1])


def _text_parts(m):
    """[(content_type, 文本)]，跳过附件。"""
    out = []
    for part in m.walk():
        if "attachment" in str(part.get("Content-Disposition") or ""):
            continue
        raw = part.get_payload(decode=True)
        if raw is None:
            continue
        out.append((part.get_content_type(), raw.decode(part.get_content_charset() or "utf-8", "ignore")))
    return out


def extract_body(m):
    """正文：优先 text/plain，没有就把 text/html 去标签。附件跳过。"""
    parts = _text_parts(m)
    plain = "".join(t for ct, t in parts if ct == "text/plain")
    page = "".join(t for ct, t in parts if ct == "text/html")
    if plain.strip():
        return plain
    if page.strip():
        return re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", "", page))
    return ""


def inbox(addr, limit=20, folder="INBOX"):
    """最近 limit 封的信头，新的在前。"""
    M = _open(addr, folder)
    try:
        typ, d = M.uid("search", None, "ALL")
        if typ != "OK":
            raise MailboxError(f"列信失败：{d}")
        uids = (d[0] or b"").split()[-limit:] if limit > 0 else []
        return [h for h in (hdr(M, u) for u in reversed(uids)) if h]
    finally:
        M.logout()


def _imap_date(s):
    d = date.fromisoformat(s)
    return f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"


def search_runs(subject=None, sender=None, body=None, since=None):
    """把条件拆成若干次 SEARCH：[(参数列表, 字面量 bytes 或 None)]，结果取交集。
    imaplib 一条命令只能带一个字面量，非 ASCII 关键词要用 CHARSET UTF-8 + 字面量放在最后，
    所以每个中文关键词单独一次（带上全部 ASCII 条件），英文条件全在一次里。"""
    ascii_args, wide = [], []
    for key, val in (("SUBJECT", subject), ("FROM", sender), ("BODY", body)):
        if val and val.isascii():
            ascii_args += [key, _quote(val)]
        elif val:
            wide.append((key, val))
    if since:
        ascii_args += ["SINCE", _imap_date(since)]
    if not ascii_args and not wide:
        raise MailboxError("search 至少要给 --subject / --from / --body / --since 之一")
    return [(ascii_args + [key], val.encode("utf-8")) for key, val in wide] or [(ascii_args, None)]


def search(addr, subject=None, sender=None, body=None, since=None, limit=50, folder="INBOX"):
    """服务器端搜索，返回信头（新的在前）。服务器不支持 UTF-8 搜索时抛 MailboxError，不退回本地全量下载。"""
    runs = search_runs(subject, sender, body, since)
    M = _open(addr, folder)
    try:
        hits = None
        for args, literal in runs:
            try:
                if literal is None:
                    typ, d = M.uid("search", None, *args)
                else:
                    M.literal = literal
                    typ, d = M.uid("search", "CHARSET", "UTF-8", *args)
            except imaplib.IMAP4.error as e:
                if literal is None:
                    raise MailboxError(f"服务器拒绝搜索：{e}") from None
                raise MailboxError(f"服务器拒绝 UTF-8 中文搜索：{e}。可改用英文关键词，或先 inbox 列信头再看") from None
            if typ != "OK":
                what = "UTF-8 中文搜索" if literal is not None else "搜索"
                raise MailboxError(f"服务器拒绝{what}：{typ} {d}。可改用英文关键词，或先 inbox 列信头再看")
            got = set((d[0] or b"").split())
            hits = got if hits is None else hits & got
        uids = sorted(hits, key=int, reverse=True)[:limit]
        return [h for h in (hdr(M, u) for u in uids) if h]
    finally:
        M.logout()


URL_RE = re.compile(r"""https?://[^\s<>"'(){}\[\]]+""", re.I)
ANCHOR_RE = re.compile(r"""<a\b[^>]*?href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", re.I | re.S)
CONFIRM_HINT = re.compile(r"verif|confirm|activat|validat|affiliat|register|token|code|确认|验证|激活|注册", re.I)


def message_links(m):
    """正文里的 http(s) 链接，按出现顺序去重：[{url, text, hint}]。hint=像验证/确认链接。只解析，不访问。"""
    seen = {}

    def add(url, text=""):
        url = html.unescape(url).strip().rstrip(".,;:!?»。，；）")
        if not url.lower().startswith(("http://", "https://")):
            return
        text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())
        r = seen.setdefault(url, {"url": url, "text": "", "hint": False})
        r["text"] = r["text"] or text            # 纯文本部分先出现时，用 HTML 里的按钮文字补上
        r["hint"] = bool(CONFIRM_HINT.search(url + " " + r["text"]))

    for ct, t in _text_parts(m):
        if ct == "text/html":
            for href, label in ANCHOR_RE.findall(t):
                add(href, label)
            t = re.sub(r"<[^>]+>", " ", t)
        for u in URL_RE.findall(html.unescape(t)):
            add(u)
    return list(seen.values())


# ---------- 发信 ----------

def _split(v):
    if not v:
        return []
    return [x.strip() for x in (v if isinstance(v, (list, tuple)) else str(v).split(",")) if x.strip()]


def build(addr, to, subject, body, cc=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = addr, ", ".join(_split(to)), subject
    if _split(cc):
        m["Cc"] = ", ".join(_split(cc))
    m.set_content(body)
    return m


def send(addr, to, subject, body, accounts=None, cc=None):
    """经该邮箱的 SMTP 发一封纯文本信（To + Cc 都收到）。smtp_tls: ssl（默认，465）或 starttls（587）。
    这是真发：命令行的 send 不加 --confirm 只预览；脚本调用方自己负责「默认预览、显式参数才发」。"""
    a = acct(addr, accounts)
    tls = a.get("smtp_tls", "ssl")
    host, port = _host_port(a.get("smtp"), 465 if tls == "ssl" else 587)
    user = a.get("username") or addr
    msg = build(addr, to, subject, body, cc)
    ctx = ssl.create_default_context()
    s = smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) if tls == "ssl" else smtplib.SMTP(host, port, timeout=30)
    with s:
        if tls != "ssl":
            s.starttls(context=ctx)
        if a.get("auth") == "xoauth2":
            s.ehlo()
            code, resp = s.docmd("AUTH", "XOAUTH2 " + base64.b64encode(_xoauth2(a, user).encode()).decode())
            if code != 235:
                raise MailboxError(f"SMTP XOAUTH2 认证失败：{code} {resp[:200]!r}")
        else:
            s.login(user, secret(a))
        s.send_message(msg)


def preview(addr, to, subject, body, cc=None):
    return (f"── 预览（未发送）──\nFrom: {addr}\nTo: {', '.join(_split(to))}\n"
            + (f"Cc: {', '.join(_split(cc))}\n" if _split(cc) else "")
            + f"Subject: {subject}\n{'-' * 30}\n{body}\n{'-' * 30}")


# ---------- 登记：用途、冲突、author_links ----------

def _code(x):
    return str(x).split()[0] if str(x).split() else ""


def _codes(link):
    return {_code(x) for x in link.get("papers") or []}


def _low(s):
    return str(s or "").strip().lower()


def system_key(a):
    """「同一投稿系统」按账号库算：Elsevier ID 单点登录算一个；其余按系统名 + 站点（域名加第一段路径，EM 每刊一个）。"""
    if a.get("login") == "elsevier-sso":
        return "Elsevier ID"
    u = urlparse(a.get("login_url") or "")
    seg = u.path.strip("/").split("/")[0] if u.path.strip("/") else ""
    return " ".join(x for x in (a.get("system") or "?", u.netloc.lower() + (f"/{seg}" if seg else "")) if x)


def usage(addr):
    boxes = load_accounts()
    key = next((k for k in boxes if _low(k) == _low(addr)), None)
    e = boxes.get(key) or {}
    systems = [{"system": system_key(a), "person": a.get("person", ""), "papers": a.get("paper", ""),
                "browser_profile": a.get("browser_profile", ""), "login_url": a.get("login_url", "")}
               for a in load_submit_accounts() if _low(addr) in (_low(a.get("email")), _low(a.get("username")))]
    if key is None and not systems:
        raise MailboxError(f"{addr} 既不在邮箱登记（{config_path()}）也不在投稿账号登记（{submit_accounts_path()}）里")
    return {"address": key or addr, "registered": key is not None, "owner": e.get("owner", ""),
            "purpose": e.get("purpose", ""), "readable": bool(e.get("readable")), "checked_at": e.get("checked_at", ""),
            "author_links": e.get("author_links") or [], "exceptions": e.get("exceptions") or [], "systems": systems}


def _excepted(entry, person, code):
    return any(x.get("person") == person and code in {_code(c) for c in x.get("papers") or []}
               for x in entry.get("exceptions") or [])


def audit(boxes=None, submit=None):
    """返回 [{level: error|warn, kind, message}]。error = 违反规则必须处理；warn = 按用途文字推断的提示。"""
    boxes = load_accounts() if boxes is None else boxes
    submit = load_submit_accounts() if submit is None else submit
    by_low = {_low(k): (k, v) for k, v in boxes.items()}
    out = []

    def add(level, kind, msg):
        out.append({"level": level, "kind": kind, "message": msg})

    # 1. 同一投稿系统里一个邮箱只对应一个人
    per_sys = {}
    for a in submit:
        mail = _low(a.get("email") or a.get("username"))
        if "@" in mail and a.get("person"):
            per_sys.setdefault((system_key(a), mail), set()).add(a["person"])
    for (sk, mail), people in sorted(per_sys.items()):
        if len(people) > 1:
            add("error", "one-mailbox-one-person", f"{sk} 里 {mail} 对应了多个人：{'、'.join(sorted(people))}")
    # 2. 投稿人、通讯作者的邮箱必须服务器能读
    for mail in sorted({m for _, m in per_sys}):
        if mail not in by_low:
            add("warn", "submitter-unregistered", f"投稿账号用的 {mail} 不在邮箱登记里，服务器读不到期刊来信")
        elif not by_low[mail][1].get("readable"):
            add("error", "key-mailbox-unreadable", f"投稿账号用的 {by_low[mail][0]} 没有标 readable（先 check 实测）")
    for addr, e in boxes.items():
        if e.get("readable"):
            continue
        for link in e.get("author_links") or []:
            if any(r in (link.get("role") or "") for r in KEY_ROLES):
                add("error", "key-mailbox-unreadable",
                    f"{addr} 登记为 {link.get('person')}（{link.get('role')}，{'、'.join(sorted(_codes(link)))}）的邮箱，但没有标 readable")
    # 3. 同一篇论文里两位作者不能用同一邮箱
    for addr, e in boxes.items():
        per_paper = {}
        for link in e.get("author_links") or []:
            for c in _codes(link):
                per_paper.setdefault(c, set()).add(link.get("person") or "?")
        for c, people in sorted(per_paper.items()):
            if len(people) > 1:
                add("error", "shared-in-paper", f"{c} 里 {addr} 同时登记给了 {'、'.join(sorted(people))}")
    # 4. 用途与绑定的人是否相符（按 purpose 文字推断）
    for addr, e in boxes.items():
        purpose, owner, links = e.get("purpose") or "", e.get("owner") or "", e.get("author_links") or []
        if re.search(r"会议|服务", purpose) and links:
            add("warn", "purpose-mismatch", f"{addr} 用途是「{purpose}」，不应登记为论文作者邮箱")
        elif "专用" in purpose and "备用" not in purpose and owner:
            for link in links:
                odd = sorted(c for c in _codes(link) if link.get("person") != owner and not _excepted(e, link.get("person"), c))
                if odd:
                    add("warn", "purpose-mismatch", f"{addr} 用途是「{purpose}」（归 {owner}），却在 {'、'.join(odd)} 登记给了 "
                        f"{link.get('person')}；用户批准的借用请写进 exceptions")
    return out


def link(addr, paper, person, role="作者"):
    """在 author_links 登记 paper · person · role。返回 (备份路径或 None, 说明, 提醒列表)。"""
    p, data, boxes = _load_raw()
    if addr.startswith("_") or addr not in boxes:
        raise MailboxError(f"未登记邮箱 {addr}；先在 {p} 里加这个邮箱")
    e = boxes[addr]
    links = e.setdefault("author_links", [])
    others = sorted({l.get("person") for l in links if l.get("person") != person and paper in _codes(l)})
    if others:
        raise RuleViolation(f"{paper} 里 {addr} 已登记给 {'、'.join(others)}：同一篇论文两位作者不能用同一邮箱。先 unlink 或换邮箱")
    mine = [l for l in links if l.get("person") == person and paper in _codes(l)]
    if mine:
        if any((l.get("role") or "") == role for l in mine):
            return None, f"已登记：{addr} · {paper} · {person}（{role}），未改动", []
        raise RuleViolation(f"{paper} 里 {person} 已登记为「{mine[0].get('role')}」；要改角色先 unlink 再 link")
    target = next((l for l in links if l.get("person") == person and (l.get("role") or "") == role), None)
    if target:
        target.setdefault("papers", []).append(paper)
    else:
        links.append({"person": person, "role": role, "papers": [paper]})
    notes = []
    if any(r in role for r in KEY_ROLES) and not e.get("readable"):
        notes.append(f"{addr} 没有标 readable：{role}的邮箱必须服务器能读，先 check 实测")
    notes += [f["message"] for f in audit(_real(boxes)) if addr in f["message"]]
    return _save_raw(p, data), f"已登记：{addr} · {paper} · {person}（{role}）", notes


def unlink(addr, paper, person=None, role=None):
    p, data, boxes = _load_raw()
    if addr.startswith("_") or addr not in boxes:
        raise MailboxError(f"未登记邮箱 {addr}")
    e, removed = boxes[addr], []
    for l in e.get("author_links") or []:
        if (person and l.get("person") != person) or (role and (l.get("role") or "") != role) or paper not in _codes(l):
            continue
        l["papers"] = [x for x in l.get("papers") or [] if _code(x) != paper]
        removed.append(f"{l.get('person')}（{l.get('role') or ''}）")
    if not removed:
        raise MailboxError(f"{addr} 没有符合条件的 {paper} 登记，未改动")
    e["author_links"] = [l for l in e.get("author_links") or [] if l.get("papers")]
    return _save_raw(p, data), f"已取消：{addr} · {paper} · {'、'.join(removed)}"


# ---------- 命令行 ----------

def _cred_kind(a):
    if a.get("auth") == "xoauth2":
        return "xoauth2(token_cmd)"
    return "env:" + a["password_env"] if a.get("password_env") else ("cmd" if a.get("password_cmd") else "未配置")


def _print_headers(rows):
    for h in rows:
        print(f"{h['uid']}\t{h['date'][:25]}\t{h['from'][:50]}\t{h['subject']}")
    print(f"共 {len(rows)} 封；看正文用 read <地址> <uid>")


def _print_usage(u):
    print(f"{u['address']}\t归属 {u['owner'] or '—'}｜用途 {u['purpose'] or '—'}｜readable="
          f"{'是' if u['readable'] else '否'}" + (f"（{u['checked_at']}）" if u["checked_at"] else "")
          + ("" if u["registered"] else "｜不在邮箱登记里"))
    print("论文登记（author_links）：")
    for l in u["author_links"]:
        print(f"  - {l.get('person')} · {l.get('role') or '—'}：{'、'.join(map(str, l.get('papers') or []))}")
    print("投稿系统账号（accounts.json）：")
    for s in u["systems"]:
        print(f"  - {s['system']} → {s['person']}（论文 {s['papers'] or '—'}，profile {s['browser_profile'] or '—'}）")
    for x in u["exceptions"]:
        print(f"例外：{x.get('person')} {'、'.join(map(str, x.get('papers') or []))}：{x.get('scope', '')} {x.get('reason', '')}")


def _print_links(rows):
    for i, r in enumerate(rows, 1):
        print(f"{i}. {'★ ' if r['hint'] else ''}{r['url']}" + (f"\t「{r['text'][:60]}」" if r["text"] else ""))
    print("★ = 像验证/确认链接。只列出、不打开；点不点由用户决定，或在浏览器里操作。" if rows else "正文里没有链接。")


def _print_audit(rows):
    for r in rows:
        print(f"[{'必须处理' if r['level'] == 'error' else '提示'}] {r['message']}")
    if not rows:
        print("没有发现登记冲突。")


def main(argv=None):
    ap = argparse.ArgumentParser(description="论文邮箱登记与收发（IMAP 只读 / SMTP 须确认）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    js = argparse.ArgumentParser(add_help=False)
    js.add_argument("--json", action="store_true", help="输出 JSON")
    fo = argparse.ArgumentParser(add_help=False)
    fo.add_argument("--folder", default="INBOX")
    sub.add_parser("list")
    x = sub.add_parser("check"); x.add_argument("addr")
    x = sub.add_parser("inbox", parents=[js, fo]); x.add_argument("addr"); x.add_argument("--limit", type=int, default=20)
    x = sub.add_parser("search", parents=[js, fo]); x.add_argument("addr")
    x.add_argument("--subject"); x.add_argument("--from", dest="sender"); x.add_argument("--body")
    x.add_argument("--since", type=date.fromisoformat, help="YYYY-MM-DD"); x.add_argument("--limit", type=int, default=50)
    x = sub.add_parser("read", parents=[fo]); x.add_argument("addr"); x.add_argument("uid")
    x = sub.add_parser("links", parents=[js, fo]); x.add_argument("addr"); x.add_argument("uid")
    x = sub.add_parser("send"); x.add_argument("addr"); x.add_argument("--to", required=True); x.add_argument("--cc")
    x.add_argument("--subject", required=True); g = x.add_mutually_exclusive_group(required=True)
    g.add_argument("--body"); g.add_argument("--body-file"); x.add_argument("--confirm", action="store_true")
    x = sub.add_parser("usage", parents=[js]); x.add_argument("addr")
    sub.add_parser("audit", parents=[js])
    x = sub.add_parser("link"); x.add_argument("addr"); x.add_argument("--paper", required=True)
    x.add_argument("--person", required=True); x.add_argument("--role", default="作者", help="通讯 / 作者 / 投稿人，可组合如 投稿人/通讯")
    x = sub.add_parser("unlink"); x.add_argument("addr"); x.add_argument("--paper", required=True)
    x.add_argument("--person"); x.add_argument("--role")
    a = ap.parse_args(argv)
    dump = getattr(a, "json", False)

    def emit(obj, text):
        print(json.dumps(obj, ensure_ascii=False, indent=1)) if dump else text(obj)

    try:
        if a.cmd == "list":
            for addr, e in load_accounts().items():
                print(f"{addr}\treadable={bool(e.get('readable'))}\t凭证={_cred_kind(e)}\t{e.get('owner', '')}\t{e.get('purpose', '')}")
        elif a.cmd == "check":
            M = imap_conn(acct(a.addr), a.addr)
            _, data = M.select("INBOX", readonly=True)
            M.logout()
            print(f"ok {a.addr} INBOX {data[0].decode() if data and data[0] else '?'} 封")
        elif a.cmd == "inbox":
            emit(inbox(a.addr, a.limit, a.folder), _print_headers)
        elif a.cmd == "search":
            emit(search(a.addr, a.subject, a.sender, a.body, a.since.isoformat() if a.since else None, a.limit, a.folder),
                 _print_headers)
        elif a.cmd in ("read", "links"):
            M = _open(a.addr, a.folder)
            try:
                m = fetch_message(M, a.uid)
            finally:
                M.logout()
            if a.cmd == "links":
                emit(message_links(m), _print_links)
                return 0
            print(f"From: {dh(m.get('From'))}\nTo: {dh(m.get('To'))}\nDate: {m.get('Date')}\nSubject: {dh(m.get('Subject'))}\n{'-' * 50}")
            body = extract_body(m).strip()
            print(body[:6000] + ("\n…（正文已截断）" if len(body) > 6000 else ""))
            atts = [dh(p.get_filename()) for p in m.walk() if p.get_filename()]
            if atts:
                print(f"\n[附件] {', '.join(atts)}")
        elif a.cmd == "send":
            body = Path(a.body_file).read_text(encoding="utf-8") if a.body_file else a.body
            if not a.confirm:
                print(preview(a.addr, a.to, a.subject, body, a.cc) + "\n加 --confirm 才发送。")
                return 0
            send(a.addr, a.to, a.subject, body, cc=a.cc)
            print(f"已发送 → {', '.join(_split(a.to) + _split(a.cc))}  主题：{a.subject}")
        elif a.cmd == "usage":
            emit(usage(a.addr), _print_usage)
        elif a.cmd == "audit":
            found = audit()
            emit(found, _print_audit)
            return 3 if any(r["level"] == "error" for r in found) else 0
        elif a.cmd == "link":
            bak, msg, notes = link(a.addr, a.paper, a.person, a.role)
            print(msg + (f"（旧文件备份 {bak}）" if bak else ""))
            for n in notes:
                print(f"注意：{n}")
        elif a.cmd == "unlink":
            bak, msg = unlink(a.addr, a.paper, a.person, a.role)
            print(f"{msg}（旧文件备份 {bak}）")
    except RuleViolation as e:
        print(f"拒绝：{e}", file=sys.stderr)
        return 3
    except (MailboxError, imaplib.IMAP4.error, smtplib.SMTPException, OSError, json.JSONDecodeError) as e:
        print(f"错误：{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
