#!/usr/bin/env python3
"""投稿台账命令行。在服务所在机器上直接用（远程机器经 SSH 调用），不需要浏览器。

走 HTTP API（默认 http://127.0.0.1:8611/api/v1，可用 PORTAL_LOCAL_BASE 改），
所以写操作同样有审计日志和删除前快照。token 优先读 PORTAL_TOKEN_FILE / PORTAL_WRITE_TOKEN_FILE，
没设就从本地数据库（PORTAL_DATA_DIR）只读取出。

    paper list                          全部论文
    paper list --status 投稿中           筛选
    paper show P02                      单篇详情
    paper stats                         统计
    paper new  --title "<标题>" [--authors "A;B;C"] [--cn 简称] [--pos 第一作者]
    paper edit P02 --title "<标题>" --notes "<备注>" --status 投稿中
    paper edit P02 --follow-mode ai --current "外审中，等第二位审稿人"   跟进方式 / 当前情况
    paper submit P02 --journal "X" --date 2026-09-09 [--ms-id <稿号>] [--url <投稿系统网址>]
    paper submit P02 --journal "Old" --date 2025-03-01 --history --outcome 被拒   补录更早的一轮
    paper sub-edit 19 --status 被拒 --ms-id ABC-D-26-XXXXX   （记录号见 paper show 每行末尾）
    paper sub-edit 19 --outcome 未关闭                   旧轮真实结局
    paper upload P02 /path/to/pkg.zip [--label "第3轮投稿包"] [--seq 3]
    paper rm-sub 63 --yes                删一条投稿记录（自动快照）
    paper rm-file P02 123 --yes          删一个附件（自动快照；磁盘文件不进快照）
    paper rm P14 --yes                   删整篇（自动快照）
    paper json <任意上面的查询>           输出原始 JSON
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sqlite3
import sys
import urllib.error
import urllib.request
import uuid
import tracking_cli
import tracking
import followup_cli
import rounds
import follow_mode
import db
from pathlib import Path

BASE = os.environ.get("PORTAL_LOCAL_BASE", "http://127.0.0.1:8611/api/v1")
DB = db.DB_PATH


def token(write: bool = False) -> str:
    token_path=os.environ.get('PORTAL_WRITE_TOKEN_FILE' if write else 'PORTAL_TOKEN_FILE')
    if token_path:return Path(token_path).read_text().strip()
    key = "api_write_token" if write else "api_token"
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        c.close()
    except sqlite3.Error as e:
        sys.exit(f"读不到本地数据库 {DB}：{e}")
    if not row or not row[0]:
        sys.exit(f"{key} 还没生成。登录网站「管理」页生成一个。")
    return row[0]


def call(method: str, path: str, body=None, write: bool = False, files=None):
    url = BASE + path
    headers = {"Authorization": "Bearer " + token(write),
               "User-Agent": "paper-cli/1.0", "Accept": "application/json"}
    data = None
    if files:
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in (body or {}).items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
        fp = Path(files)
        ctype = mimetypes.guess_type(fp.name)[0] or "application/octet-stream"
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"f\"; "
                     f"filename=\"{fp.name}\"\r\nContent-Type: {ctype}\r\n\r\n".encode())
        parts.append(fp.read_bytes())
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        sys.exit(f"HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        sys.exit(f"连不上 {BASE}（服务没起？或 PORTAL_LOCAL_BASE 不对）：{e.reason}")


def brief(p: dict) -> None:
    mine = p["my_author_position"] or "位次未标"
    if p["i_am_corresponding"]:
        mine += "+通讯"
    n = p["submission_count"]
    d = p.get("days_since_current_submit")
    age = f"  {d}天" if d is not None else ""
    status = (p.get("current_submission") or {}).get("display_status") or p["status"]
    print(f"{p['code']:<5}{status:<6}{mine:<12}{(p['current_journal'] or '—')[:30]:<32}"
          f"{'x%d' % n if n > 1 else '  ':<4}{age:<7}{(p['title_cn'] or p['title'])[:38]}")


def detail(p: dict) -> None:
    print(f"\n[{p['code']}] {p['status']}   我：{p['my_author_position'] or '未标'}"
          f"{' + 通讯' if p['i_am_corresponding'] else ''}   {p['category']}")
    print(f"  {p['title']}")
    if p["title_cn"]:
        print(f"  简称 {p['title_cn']}")
    print(f"  作者 {' / '.join(p['authors']) if p['authors'] else '未录入'}")
    print(f"  通讯 {p['corresponding'] or '未填'}    负责人 {p['lead_author'] or '未填'}"
          f"    跟进方式 {p.get('follow_mode_label') or '未登记'}")
    print(f"  已投 {p.get('days_since_current_submit')} 天；无进展 {p.get('days_without_progress')} 天；阶段 {p.get('review_stage') or '未标注'}")
    print(f"  最近核查 {p.get('last_checked_date') or '未登记'}；返修截止 {p.get('revision_due_date') or '—'}")
    if p.get("current_note"):
        print(f"  当前情况 {p['current_note']}")
    if p["notes"]:
        print(f"  备注 {p['notes']}")
    for s in p["submissions"]:
        tag = "← 当前" if s["is_current"] else "（历史）"
        print(f"    第{s['seq']}次 {s['journal']:<34}{s['submit_date'] or '无日期':<12}"
              f"{s.get('display_status', s['status']):<7}{tag}  [记录号 {s.get('id', '?')}]")
        if s["manuscript_id"]:
            print(f"            稿号 {s['manuscript_id']}")
        if s["site_url"]:
            print(f"            {s['site_url']}")
    for f in p.get("files", []):
        print(f"    附件 #{f.get('id','?')} [{f.get('kind','other')}] {f['name']}  {f['size_mb']} MB  {f['label']}")


FOLLOW_HELP = "ai AI代查 / self 本人自查 / student 学生自管 / watch 学生自管·AI盯截止 / partner 合作方自管 / none 未登记"


def paper_category(args):
    """--category 与兼容参数 --extra 合并；两者矛盾时报错，不猜。"""
    if args.extra and args.category not in (None, "extra"):
        sys.exit("--extra 与 --category 矛盾，只给一个")
    return "extra" if args.extra else args.category


def kv(args, pairs) -> dict:
    out = {}
    for cli_name, api_name in pairs:
        v = getattr(args, cli_name, None)
        if v is not None:
            out[api_name] = v
    if "authors" in out and isinstance(out["authors"], str):
        out["authors"] = [a.strip() for a in out["authors"].replace("；", ";").split(";") if a.strip()]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="paper", description="投稿台账命令行（本机直连，远程用 SSH；API 可用 token 文件）",
        epilog="例：paper watch --days 30；paper progress P02 --stage 外审中；paper credentials set P02 --from-json -；paper download P02 --latest --kind latex --out latest.zip")
    ap.add_argument("--json", action="store_true", help="输出原始 JSON")
    sp = ap.add_subparsers(dest="cmd", required=True)
    tracking_cli.arguments(sp)
    followup_cli.arguments(sp)

    q = sp.add_parser("list", help="论文列表")
    q.add_argument("--status"); q.add_argument("--position"); q.add_argument("-q", dest="q")
    sp.add_parser("stats", help="统计")
    s1 = sp.add_parser("show", help="单篇详情"); s1.add_argument("code")

    n = sp.add_parser("new", help="新建论文")
    n.add_argument("--title", required=True); n.add_argument("--cn", dest="title_cn")
    n.add_argument("--authors"); n.add_argument("--corresponding"); n.add_argument("--lead")
    n.add_argument("--pos", dest="author_pos"); n.add_argument("--notes")
    n.add_argument("--status"); n.add_argument("--extra", action="store_true", help="同 --category extra（兼容旧参数）")
    n.add_argument("--category", choices=list(rounds.CATEGORY_NAMES), help="main 主序列 / extra 其他论文（不计入主序列） / partner 合作方论文")
    n.add_argument("--follow-mode", dest="follow_mode", choices=follow_mode.CLI_CHOICES, help=FOLLOW_HELP)
    n.add_argument("--current", dest="current_note", help="当前情况（一两句，整段覆盖）")

    e = sp.add_parser("edit", help="改论文字段"); e.add_argument("code")
    e.add_argument("--title"); e.add_argument("--cn", dest="title_cn"); e.add_argument("--authors")
    e.add_argument("--corresponding"); e.add_argument("--lead"); e.add_argument("--pos", dest="author_pos")
    e.add_argument("--notes"); e.add_argument("--status")
    e.add_argument("--extra", action="store_true", help="同 --category extra（兼容旧参数）")
    e.add_argument("--category", choices=list(rounds.CATEGORY_NAMES), help="main 主序列 / extra 其他论文（不计入主序列） / partner 合作方论文")
    e.add_argument("--follow-mode", dest="follow_mode", choices=follow_mode.CLI_CHOICES,
                   help=FOLLOW_HELP + "；同时决定跟进计划是否活跃")
    e.add_argument("--current", dest="current_note", help="当前情况（一两句，整段覆盖；备注 --notes 是历史记录）")
    e.add_argument("--from-json");e.add_argument("--is-corresponding",action=argparse.BooleanOptionalAction,default=None)

    b = sp.add_parser("submit", help="新增一轮投稿（转投）"); b.add_argument("code")
    b.add_argument("--journal", required=True); b.add_argument("--date", dest="submit_date")
    b.add_argument("--ms-id", dest="manuscript_id"); b.add_argument("--url", dest="site_url")
    b.add_argument("--status"); b.add_argument("--notes")
    b.add_argument("--account", dest="sys_account"); b.add_argument("--password", dest="sys_password",help="兼容参数，推荐 --password-file")
    b.add_argument('--password-file');b.add_argument('--from-json')
    b.add_argument("--history", action="store_true", help="补录更早的一轮：按 --date 插到对应位置，后面的轮次顺延，不改当前轮和论文状态")
    b.add_argument("--outcome", choices=rounds.OUTCOMES, help="旧轮真实结局（主要给 --history 用）")

    se = sp.add_parser("sub-edit", help="改某条投稿记录"); se.add_argument("sid", type=int)
    se.add_argument("--journal"); se.add_argument("--date", dest="submit_date")
    se.add_argument("--ms-id", dest="manuscript_id"); se.add_argument("--url", dest="site_url")
    se.add_argument("--status"); se.add_argument("--result-date", dest="result_date")
    se.add_argument("--notes")
    se.add_argument('--account',dest='sys_account');se.add_argument('--password-file');se.add_argument('--from-json')
    se.add_argument("--outcome", choices=rounds.OUTCOMES, help="旧轮真实结局；空串 '' 清除")

    u = sp.add_parser("upload", help="上传附件"); u.add_argument("code"); u.add_argument("path")
    u.add_argument("--label", default=""); u.add_argument("--seq", default="")
    u.add_argument("--kind",choices=tracking.FILE_KINDS,default="other")

    d1 = sp.add_parser("rm-sub", help="删一条投稿记录"); d1.add_argument("sid", type=int)
    d1.add_argument("--yes", action="store_true")
    d2 = sp.add_parser("rm", help="删整篇论文"); d2.add_argument("code")
    d2.add_argument("--yes", action="store_true")
    d3 = sp.add_parser("rm-file", help="删一个附件（核对附件属于该论文；删前快照数据库，磁盘文件不可恢复）")
    d3.add_argument("code"); d3.add_argument("fid", type=int)
    d3.add_argument("--yes", action="store_true")

    a = ap.parse_args()
    out = None
    if followup_cli.execute(a,sys.modules[__name__]):return
    if tracking_cli.execute(a,sys.modules[__name__]):return

    if a.cmd == "list":
        qs = "&".join(f"{k}={urllib.request.quote(v)}" for k, v in
                      (("status", a.status), ("position", a.position), ("q", a.q)) if v)
        out = call("GET", "/papers" + ("?" + qs if qs else ""))
        if not a.json:
            print(f"{'编号':<5}{'状态':<6}{'我的身份':<12}{'当前期刊':<32}{'轮':<4}{'已投':<7}标题")
            for p in out["papers"]:
                brief(p)
            print(f"\n共 {out['count']} 篇   {out['timezone']}")
    elif a.cmd == "stats":
        out = call("GET", "/stats")
        if not a.json:
            main = out["main_series"]
            cats = out["by_category"]
            print(f"共 {out['total']} 篇：主序列 {main['total']} 篇；"
                  f"其他论文 {cats[rounds.CATEGORY_NAMES['extra']]} 篇、合作方论文 {cats['合作方论文']} 篇单列，不计入主序列")
            for title, key in (("主序列 · 按状态", "by_status"), ("主序列 · 按我的位次", "by_author_position")):
                print(f"\n{title}:")
                for k, v in sorted(main[key].items(), key=lambda x: -x[1]):
                    print(f"  {k:<10}{v}")
            print(f"  {'通讯作者':<10}{main['corresponding_count']}")
    elif a.cmd == "show":
        out = call("GET", f"/papers/{a.code}")
        if not a.json:
            detail(out)
    elif a.cmd == "new":
        body = kv(a, [("title", "title"), ("title_cn", "title_cn"), ("authors", "authors"),
                      ("corresponding", "corresponding"), ("lead", "lead_author"),
                      ("author_pos", "author_pos"), ("notes", "notes"), ("status", "status"),
                      ("current_note", "current_note"), ("follow_mode", "follow_mode")])
        category = paper_category(a)
        if category:
            body["category"] = category
        out = call("POST", "/papers", body, write=True)
        print(f"已新建 {out['code']}") if not a.json else None
        if not a.json:
            detail(out)
    elif a.cmd == "edit":
        body = kv(a, [("title", "title"), ("title_cn", "title_cn"), ("authors", "authors"),
                      ("corresponding", "corresponding"), ("lead", "lead_author"),
                      ("author_pos", "author_pos"), ("notes", "notes"), ("status", "status"),
                      ("current_note", "current_note"), ("follow_mode", "follow_mode")])
        if a.from_json:body.update(tracking_cli.json_file(a.from_json))
        if a.is_corresponding is not None:body["is_corresponding"]=a.is_corresponding
        category = paper_category(a)
        if category:
            body["category"] = category
        if not body:
            sys.exit("没给任何要改的字段")
        out = call("PATCH", f"/papers/{a.code}", body, write=True)
        if not a.json:
            detail(out)
    elif a.cmd == "submit":
        body = kv(a, [("journal", "journal"), ("submit_date", "submit_date"),
                      ("manuscript_id", "manuscript_id"), ("site_url", "site_url"),
                      ("status", "status"), ("notes", "notes"),
                      ("sys_account", "sys_account"), ("sys_password", "sys_password"),
                      ("outcome", "outcome")])
        if a.history:
            if not a.submit_date:
                sys.exit("--history 补录历史轮必须给 --date YYYY-MM-DD")
            body["history"] = True
        if a.from_json:body.update(tracking_cli.json_file(a.from_json))
        if a.password_file:body['sys_password']=tracking_cli.text_file(a.password_file).rstrip('\r\n')
        out = call("POST", f"/papers/{a.code}/submissions", body, write=True)
        if not a.json:
            detail(out)
    elif a.cmd == "sub-edit":
        body = kv(a, [("journal", "journal"), ("submit_date", "submit_date"),
                      ("manuscript_id", "manuscript_id"), ("site_url", "site_url"),
                      ("status", "status"), ("result_date", "result_date"), ("notes", "notes"), ("sys_account", "sys_account"),
                      ("outcome", "outcome")])
        if a.from_json:body.update(tracking_cli.json_file(a.from_json))
        if a.password_file:body["sys_password"]=tracking_cli.text_file(a.password_file).rstrip("\r\n")
        if not body:
            sys.exit("没给任何要改的字段")
        out = call("PATCH", f"/submissions/{a.sid}", body, write=True)
        if not a.json:
            detail(out)
    elif a.cmd == "upload":
        if not Path(a.path).is_file():
            sys.exit(f"文件不存在：{a.path}")
        out = call("POST", f"/papers/{a.code}/files",
                   {"label": a.label, "submission_seq": a.seq,"kind":a.kind}, write=True, files=a.path)
        if not a.json:
            print(f"已上传 {out['name']}  {out['size_mb']} MB → {out['paper']}"
                  + (f" 第{out['submission_seq']}轮" if out.get("submission_seq") else ""))
    elif a.cmd in ("rm", "rm-sub", "rm-file"):
        if not a.yes:
            sys.exit("删除不可恢复。确认请加 --yes（删前会自动打数据库快照）")
        if a.cmd == "rm":
            out = call("DELETE", f"/papers/{a.code}?confirm={a.code}", write=True)
        elif a.cmd == "rm-file":
            # 服务端按 paper= 核对附件归属，不属于该论文直接拒绝
            out = call("DELETE", f"/files/{a.fid}?confirm={a.fid}&paper={urllib.request.quote(a.code)}", write=True)
        else:
            out = call("DELETE", f"/submissions/{a.sid}?confirm={a.sid}", write=True)
        if not a.json:
            print(f"已删除。回滚快照：{out['snapshot']}"
                  + ("（只含数据库记录，附件文件本身已从磁盘删除）" if a.cmd == "rm-file" else ""))

    if a.json and out is not None:
        print(json.dumps(out, ensure_ascii=False, indent=2))


def download(path, output):
    req=urllib.request.Request(BASE+path,headers={"Authorization":"Bearer "+token(True),"User-Agent":"paper-cli/2.0"})
    try:
        with urllib.request.urlopen(req,timeout=300) as r:
            while True:
                block=r.read(1024*1024)
                if not block:break
                output.write(block)
            return int(r.headers['X-File-Id'])
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: 下载失败") from None
    except urllib.error.URLError:
        raise RuntimeError('下载连接失败') from None


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as e:
        print(f"paper: {e}", file=sys.stderr)
        sys.exit(1)
