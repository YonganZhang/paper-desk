#!/usr/bin/env python3
"""最小邮箱适配：按 JSON 配置连 IMAP / SMTP。mail_scan.py、untracked_scan.py、weekly_report.py 调用它，也能单独当命令用。

配置：环境变量 PAPER_MAILBOXES，默认 ~/.config/paper-desk/mailboxes.json；示例 assets/mailboxes.example.json，字段见 references/config.md。
凭证只从配置指定的来源取：password_env（环境变量名）、password_cmd（命令，stdout 为密码），
或 auth=xoauth2 + token_cmd（命令，stdout 为 OAuth2 access token；续期由你的命令负责，本模块不实现 OAuth 流程）。

用法：
  mailboxes.py list                                   列出已登记邮箱（不联网、不取凭证）
  mailboxes.py check <地址>                            实测 IMAP 登录并只读打开 INBOX；通过后可把配置里该条标 "readable": true
  mailboxes.py read <地址> <uid> [--folder INBOX]      读一封信（不标已读）
  mailboxes.py send <发件地址> --to A[,B] --subject S (--body T | --body-file F) [--confirm]   不加 --confirm 只预览
退出码：0 成功，1 连接/凭证/配置失败，2 参数错误。
"""
import argparse
import base64
import imaplib
import json
import os
import re
import smtplib
import ssl
import subprocess
import sys
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import EmailMessage
from pathlib import Path

NETEASE_HOSTS = ("163.com", "126.com", "yeah.net")   # 网易登录后要先发 IMAP ID，否则 SELECT 报 Unsafe Login


class MailboxError(RuntimeError):
    """配置、凭证或服务器返回的错误。调用方按邮箱分别处理，一个失败不挡其他。"""


def config_path():
    return Path(os.environ.get("PAPER_MAILBOXES") or "~/.config/paper-desk/mailboxes.json").expanduser()


def load_accounts():
    """返回 {地址: 配置}。配置文件顶层可以直接是这个映射，也可以是 {"mailboxes": {…}}。"""
    p = config_path()
    if not p.exists():
        raise MailboxError(f"缺邮箱配置 {p}（示例见 assets/mailboxes.example.json）")
    data = json.loads(p.read_text(encoding="utf-8"))
    boxes = data.get("mailboxes", data) if isinstance(data, dict) else None
    if not isinstance(boxes, dict):
        raise MailboxError(f"{p} 顶层应为 {{地址: 配置}} 或 {{\"mailboxes\": {{…}}}}")
    return {k: v for k, v in boxes.items() if not k.startswith("_")}


def acct(addr, accounts=None):
    a = (accounts if accounts is not None else load_accounts()).get(addr)
    if not a:
        raise MailboxError(f"未登记邮箱 {addr}")
    return a


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


def extract_body(m):
    """正文：优先 text/plain，没有就把 text/html 去标签。附件跳过。"""
    plain, html = "", ""
    for part in m.walk():
        if "attachment" in str(part.get("Content-Disposition") or ""):
            continue
        raw = part.get_payload(decode=True)
        if raw is None:
            continue
        text = raw.decode(part.get_content_charset() or "utf-8", "ignore")
        if part.get_content_type() == "text/plain":
            plain += text
        elif part.get_content_type() == "text/html":
            html += text
    if plain.strip():
        return plain
    if html.strip():
        return re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", "", html))
    return ""


def build(addr, to, subject, body):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = addr, ", ".join(to) if isinstance(to, (list, tuple)) else to, subject
    m.set_content(body)
    return m


def send(addr, to, subject, body, accounts=None):
    """经该邮箱的 SMTP 发一封纯文本信。smtp_tls: ssl（默认，465）或 starttls（587）。"""
    a = acct(addr, accounts)
    tls = a.get("smtp_tls", "ssl")
    host, port = _host_port(a.get("smtp"), 465 if tls == "ssl" else 587)
    user = a.get("username") or addr
    msg = build(addr, to, subject, body)
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


def _cred_kind(a):
    if a.get("auth") == "xoauth2":
        return "xoauth2(token_cmd)"
    return "env:" + a["password_env"] if a.get("password_env") else ("cmd" if a.get("password_cmd") else "未配置")


def main():
    ap = argparse.ArgumentParser(description="最小邮箱适配（IMAP 只读 / SMTP 发信）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    x = sub.add_parser("check"); x.add_argument("addr")
    x = sub.add_parser("read"); x.add_argument("addr"); x.add_argument("uid"); x.add_argument("--folder", default="INBOX")
    x = sub.add_parser("send"); x.add_argument("addr"); x.add_argument("--to", required=True)
    x.add_argument("--subject", required=True); g = x.add_mutually_exclusive_group(required=True)
    g.add_argument("--body"); g.add_argument("--body-file"); x.add_argument("--confirm", action="store_true")
    a = ap.parse_args()
    try:
        if a.cmd == "list":
            for addr, e in load_accounts().items():
                print(f"{addr}\treadable={bool(e.get('readable'))}\t凭证={_cred_kind(e)}\t{e.get('owner', '')}\t{e.get('purpose', '')}")
        elif a.cmd == "check":
            M = imap_conn(acct(a.addr), a.addr)
            _, data = M.select("INBOX", readonly=True)
            M.logout()
            print(f"ok {a.addr} INBOX {data[0].decode() if data and data[0] else '?'} 封")
        elif a.cmd == "read":
            M = imap_conn(acct(a.addr), a.addr)
            M.select(f'"{a.folder}"', readonly=True)
            typ, d = M.uid("fetch", a.uid.encode(), "(BODY.PEEK[])")
            if not d or not isinstance(d[0], tuple):
                raise MailboxError(f"没有 uid {a.uid}")
            m = message_from_bytes(d[0][1])
            print(f"From: {dh(m.get('From'))}\nTo: {dh(m.get('To'))}\nDate: {m.get('Date')}\nSubject: {dh(m.get('Subject'))}\n{'-' * 50}")
            body = extract_body(m).strip()
            print(body[:6000] + ("\n…（正文已截断）" if len(body) > 6000 else ""))
            atts = [dh(p.get_filename()) for p in m.walk() if p.get_filename()]
            if atts:
                print(f"\n[附件] {', '.join(atts)}")
            M.logout()
        elif a.cmd == "send":
            body = Path(a.body_file).read_text(encoding="utf-8") if a.body_file else a.body
            to = [t.strip() for t in a.to.split(",") if t.strip()]
            if not a.confirm:
                print(f"── 预览（未发送）──\nFrom: {a.addr}\nTo: {', '.join(to)}\nSubject: {a.subject}\n{'-' * 30}\n{body}\n{'-' * 30}\n加 --confirm 才发送。")
                return 0
            send(a.addr, to, a.subject, body)
            print(f"已发送 → {', '.join(to)}  主题：{a.subject}")
    except (MailboxError, imaplib.IMAP4.error, smtplib.SMTPException, OSError) as e:
        print(f"错误：{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
