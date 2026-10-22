"""课题组投稿台账 — Web 应用。

功能范围：
  - 学生自助注册 / 登录，只看得到自己的论文
  - 管理员（首次启动时创建，见 README「初始化管理员」）看得到全部论文和归属人
  - 每篇论文记录：标题、作者顺序、通讯作者、负责人
  - 每次投稿 / 转投一条记录：期刊、投稿系统网址、账号、密码、投稿日期、稿号、状态
  - 投稿包上传（word / pdf / latex zip 等，单文件 100 MB 上限）
  - 公共投稿账号池 + 课题组花名册（所有登录用户可见）
  - 新手教程页

启动：
    python3 app.py                                    # 默认 127.0.0.1:8611
    PORT=8611 PORTAL_DATA_DIR=/srv/paper-desk python3 app.py
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer

import db
import tracking
import followup
import follow_mode
import rounds

BASE_DIR = Path(__file__).resolve().parent
COOKIE_NAME = "portal_session"

SECRET_FILE = db.DATA_DIR / ".session_secret"


def _secret() -> str:
    db.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(uuid.uuid4().hex + uuid.uuid4().hex, encoding="utf-8")
        SECRET_FILE.chmod(0o600)
    return SECRET_FILE.read_text(encoding="utf-8").strip()


signer = URLSafeSerializer(_secret(), salt="portal-session")

db.init_db()

app = FastAPI(title="课题组投稿台账", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ------------------------------------------------------------------ 基础设施

def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def current_user(request: Request, conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        data = signer.loads(raw)
    except BadSignature:
        return None
    row = conn.execute(
        "SELECT * FROM users WHERE id=? AND active=1", (data.get("uid"),)
    ).fetchone()
    return row


def require_user(request: Request, conn: sqlite3.Connection) -> sqlite3.Row:
    user = current_user(request, conn)
    if not user:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return user


def require_admin(request: Request, conn: sqlite3.Connection) -> sqlite3.Row:
    user = require_user(request, conn)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/v1/"):
        return JSONResponse({"detail":exc.detail},status_code=exc.status_code,headers=exc.headers)
    if exc.status_code == 307 and exc.headers and "Location" in exc.headers:
        return RedirectResponse(exc.headers["Location"], status_code=303)
    return HTMLResponse(
        f"<div style='font-family:system-ui;padding:48px;max-width:640px;margin:auto'>"
        f"<h2>{exc.status_code}</h2><p>{exc.detail}</p>"
        f"<p><a href='/'>返回首页</a></p></div>",
        status_code=exc.status_code,
    )


def render(request: Request, conn: sqlite3.Connection, tpl: str, **ctx) -> HTMLResponse:
    user = ctx.pop("user", None)
    if user is None:
        user = current_user(request, conn)
    base = {
        "user": user,
        "site_title": db.get_setting(conn, "site_title", "课题组投稿台账"),
        "notice": db.get_setting(conn, "notice", ""),
        "PAPER_STATUS": db.PAPER_STATUS,
        # 位次只留到第四；再往后统一「其他位置」，不细分。通讯是独立的勾选框。
        "AUTHOR_POS": ["第一作者", "第二作者", "第三作者", "第四作者", "其他位置", "非作者"],
        # 「在投 / 已发表」不再是独立字段，直接由 status 推导，避免两层同义词
        "PUB_FILTER": {"未投稿": ["撰写中"], "在投": ["投稿中", "被拒"],
                       "已发表": ["已录用"], "已撤稿": ["撤稿"]},
        "SUBMISSION_STATUS": db.SUBMISSION_STATUS,
        "FOLLOW_MODES": follow_mode.MODES,
        # 作者位次、是否通讯是相对「本人」记的；名字来自 PAPER_DESK_OWNER_NAMES
        "owner_label": db.OWNER_LABEL,
        "timezone": db.TIMEZONE,
        "tz_offset": db.tz_offset(),
    }
    base.update(ctx)
    return templates.TemplateResponse(request, tpl, base)


def back(url: str, msg: str = "") -> RedirectResponse:
    if msg:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}msg={msg}"
    return RedirectResponse(url, status_code=303)


# ------------------------------------------------------------------ 登录 / 注册

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, conn: sqlite3.Connection = Depends(get_conn), msg: str = ""):
    if current_user(request, conn):
        return RedirectResponse("/", status_code=303)
    return render(request, conn, "login.html", msg=msg)


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    username = username.strip()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row or not db.verify_password(password, row["password_hash"]):
        return back("/login", "账号或密码不对")
    if not row["active"]:
        return back("/login", "账号已被停用，请找管理员")
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(
        COOKIE_NAME,
        signer.dumps({"uid": row["id"]}),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    db.log(conn, username, "login")
    return resp


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, conn: sqlite3.Connection = Depends(get_conn), msg: str = ""):
    return render(
        request,
        conn,
        "register.html",
        msg=msg,
        invite_needed=db.get_setting(conn, "invite_code_enabled", "0") == "1",
    )


@app.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    display_name: str = Form(""),
    invite: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
):
    username = username.strip()
    display_name = display_name.strip() or username
    if db.get_setting(conn, "invite_code_enabled", "0") == "1":
        if invite.strip() != db.get_setting(conn, "invite_code", ""):
            return back("/register", "邀请码不对，问一下管理员")
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{2,32}", username):
        return back("/register", "账号只能用英文字母、数字、下划线，2~32 位")
    if len(password) < 4:
        return back("/register", "密码至少 4 位")
    if password != password2:
        return back("/register", "两次输入的密码不一样")
    if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        return back("/register", "这个账号已经有人用了")
    conn.execute(
        "INSERT INTO users(username, password_hash, display_name, role, active, created_at) "
        "VALUES(?,?,?,'student',1,?)",
        (username, db.hash_password(password), display_name, db.now()),
    )
    conn.commit()
    db.log(conn, username, "register")
    return back("/login", "注册成功，用新账号登录吧")


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


@app.post("/me/password")
def change_password(
    request: Request,
    old: str = Form(...),
    new: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    user = require_user(request, conn)
    if not db.verify_password(old, user["password_hash"]):
        return back("/me", "原密码不对")
    if len(new) < 4:
        return back("/me", "新密码至少 4 位")
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (db.hash_password(new), user["id"]))
    conn.commit()
    return back("/me", "密码已改")


@app.get("/me", response_class=HTMLResponse)
def me(request: Request, conn: sqlite3.Connection = Depends(get_conn), msg: str = ""):
    user = require_user(request, conn)
    return render(request, conn, "me.html", user=user, msg=msg)


# ------------------------------------------------------------------ 论文列表

def _papers_for(conn: sqlite3.Connection, user: sqlite3.Row, q: str = "",
                status: str = "", role: str = "", pub: str = ""):
    sql = """
        SELECT p.*, u.display_name AS owner_name, u.username AS owner_username,
               (SELECT COUNT(*) FROM submissions s WHERE s.paper_id = p.id) AS n_sub,
               (SELECT COUNT(*) FROM files f WHERE f.paper_id = p.id) AS n_file,
               (SELECT s.journal FROM submissions s WHERE s.paper_id = p.id
                 ORDER BY s.seq DESC LIMIT 1) AS last_journal,
               (SELECT s.status FROM submissions s WHERE s.paper_id = p.id
                 ORDER BY s.seq DESC LIMIT 1) AS last_sub_status,
               (SELECT s.submit_date FROM submissions s WHERE s.paper_id = p.id
                 ORDER BY s.seq DESC LIMIT 1) AS last_date
        FROM papers p JOIN users u ON u.id = p.owner_id
        WHERE 1=1
    """
    args: list = []
    if user["role"] != "admin":
        sql += " AND p.owner_id = ?"
        args.append(user["id"])
    if q:
        sql += (
            " AND (p.title LIKE ? OR p.title_cn LIKE ? OR p.authors LIKE ?"
            " OR p.lead_author LIKE ? OR u.display_name LIKE ?"
            " OR p.code LIKE ?"
            " OR EXISTS(SELECT 1 FROM submissions s WHERE s.paper_id=p.id AND s.journal LIKE ?))"
        )
        args += [f"%{q}%"] * 7
    if status:
        sql += " AND p.status = ?"
        args.append(status)
    if pub:
        group = PUB_FILTER.get(pub)
        if group:
            sql += " AND p.status IN (%s)" % ",".join("?" * len(group))
            args += group
    if role and user["role"] == "admin":
        if role in ("__extra__", "__partner__", "__main__"):
            sql += " AND p.category = ?"
            args.append(role.strip("_"))
        elif role == "__corr__":
            sql += " AND p.is_corresponding = 1"
        else:
            sql += " AND p.author_pos = ?"
            args.append(role)
    sql += " ORDER BY CASE WHEN p.code='' THEN 1 ELSE 0 END, p.code, p.updated_at DESC"
    return conn.execute(sql, args).fetchall()


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    q: str = "",
    status: str = "",
    role: str = "",
    pub: str = "",
    msg: str = "",
):
    user = require_user(request, conn)
    papers = _papers_for(conn, user, q.strip(), status, role, pub)
    counts = {}
    for p in papers:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    scope = "" if user["role"] == "admin" else f" WHERE owner_id={user['id']}"
    by_status = {r["status"]: r["c"] for r in conn.execute(
        f"SELECT status, COUNT(*) c FROM papers{scope} GROUP BY status")}
    pub_counts = {k: sum(by_status.get(v, 0) for v in vs) for k, vs in PUB_FILTER.items()}
    role_counts = {}
    if user["role"] == "admin":
        for r in conn.execute(
            "SELECT author_pos k, COUNT(*) c FROM papers WHERE author_pos!='' GROUP BY k"):
            role_counts[r["k"]] = r["c"]
        role_counts["__corr__"] = conn.execute(
            "SELECT COUNT(*) c FROM papers WHERE is_corresponding=1").fetchone()["c"]
        for cat in rounds.CATEGORY_NAMES:
            role_counts[f"__{cat}__"] = conn.execute(
                "SELECT COUNT(*) c FROM papers WHERE category=?", (cat,)).fetchone()["c"]
    return render(
        request, conn, "index.html", user=user, papers=papers, q=q, status=status,
        role=role, pub=pub, msg=msg, counts=counts, role_counts=role_counts,
        pub_counts=pub_counts,
    )


@app.get("/api/pulse")
def pulse(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """轮询用：返回可见论文的最新变更戳，前端发现变化就自动刷新。"""
    user = current_user(request, conn)
    if not user:
        return JSONResponse({"v": ""})
    if user["role"] == "admin":
        row = conn.execute("SELECT COUNT(*) c, MAX(updated_at) m FROM papers").fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) c, MAX(updated_at) m FROM papers WHERE owner_id=?", (user["id"],)
        ).fetchone()
    return JSONResponse({"v": f"{row['c']}|{row['m']}"})


# ------------------------------------------------------------------ 论文增删改

@app.get("/paper/new", response_class=HTMLResponse)
def paper_new_page(request: Request, conn: sqlite3.Connection = Depends(get_conn), msg: str = ""):
    user = require_user(request, conn)
    roster = conn.execute("SELECT * FROM roster ORDER BY sort_order, id").fetchall()
    return render(request, conn, "paper_form.html", user=user, paper=None, roster=roster, msg=msg)


@app.post("/paper/new")
def paper_new(
    request: Request,
    title: str = Form(...),
    title_cn: str = Form(""),
    lead_author: str = Form(""),
    authors: str = Form(""),
    corresponding: str = Form(""),
    status: str = Form("撰写中"),
    notes: str = Form(""),
    current_note: str = Form(""),
    author_pos: str = Form(""),
    is_corresponding: str = Form(""),
    is_extra: str = Form(""),
    category: str = Form(""),
    follow_mode_value: str = Form("", alias="follow_mode"),
    journal: str = Form(""),
    site_url: str = Form(""),
    sys_account: str = Form(""),
    sys_password: str = Form(""),
    submit_date: str = Form(""),
    manuscript_id: str = Form(""),
    sub_status: str = Form("投稿中"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    user = require_user(request, conn)
    # 角色和论文分类是管理员的口径，学生提交的这些字段一律忽略
    is_admin = user["role"] == "admin"
    cat = _form_category(category, is_extra) if is_admin else "main"
    mode = follow_mode.parse(follow_mode_value) if is_admin else ""
    title = title.strip()
    if not title:
        return back("/paper/new", "论文标题不能为空")
    ts = db.now()
    cur = conn.execute(
        "INSERT INTO papers(owner_id,title,title_cn,lead_author,authors,corresponding,"
        "status,notes,author_pos,is_corresponding,category,code,follow_mode,current_note,"
        "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            user["id"], title, title_cn.strip(), lead_author.strip() or user["display_name"],
            authors.strip(), corresponding.strip(), status, notes.strip(),
            author_pos.strip() if is_admin else "",
            1 if (is_corresponding and is_admin) else 0,
            cat, next_code(conn, cat, status), mode, current_note.strip(), ts, ts,
        ),
    )
    pid = cur.lastrowid
    follow_mode.sync(conn, pid, mode, user["username"])
    if journal.strip() or submit_date.strip():
        conn.execute(
            "INSERT INTO submissions(paper_id,seq,journal,site_url,sys_account,sys_password,"
            "submit_date,manuscript_id,status,created_at,updated_at) "
            "VALUES(?,1,?,?,?,?,?,?,?,?,?)",
            (
                pid, journal.strip(), site_url.strip(), sys_account.strip(),
                sys_password, submit_date.strip(), manuscript_id.strip(), sub_status, ts, ts,
            ),
        )
    conn.commit()
    db.log(conn, user["username"], "paper.new", f"#{pid} {title}")
    return back(f"/paper/{pid}", "论文已创建")


def _form_category(category: str, is_extra: str) -> str:
    """网页表单的分类：新下拉框 category 优先，旧勾选框 is_extra 兼容。"""
    if category:
        if category not in rounds.CATEGORY_NAMES:
            raise HTTPException(422, f"未知论文分类 {category!r}")
        return category
    return "extra" if is_extra else "main"


def next_code(conn: sqlite3.Connection, category: str = "main",
              status: str = "投稿中") -> str:
    """下一个编号。在投 P01..、其他论文 X01..、已发表 F01.. 三条独立序列，互不占号。
    合作方论文（partner）不另设前缀，沿用 P/F。
    编号一旦分配就不随状态变化自动改，避免引用失效；要改由管理员手动改。"""
    prefix = "X" if category == "extra" else ("F" if status == "已录用" else "P")
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(code,2) AS INTEGER)) m FROM papers WHERE code LIKE ?",
        (prefix + "%",),
    ).fetchone()
    return f"{prefix}{(row['m'] or 0) + 1:02d}"


PUB_FILTER = {"未投稿": ["撰写中"], "在投": ["投稿中", "被拒"],
              "已发表": ["已录用"], "已撤稿": ["撤稿"]}


def sync_paper_status(conn: sqlite3.Connection, pid: int) -> None:
    """论文状态 = 最新一次投稿的状态。

    只有最新那次有真状态。更早的记录在页面上一律显示「已转投」——
    它是结构推导的（后面还有一次投稿 = 这一家已经转走了），不存库、不给选，
    所以不存在「到底记被拒还是记转投」这种要人去确认的细节。
    """
    row = conn.execute(
        "SELECT seq, status FROM submissions WHERE paper_id=? ORDER BY seq DESC LIMIT 1", (pid,)
    ).fetchone()
    if not row:
        return
    conn.execute("UPDATE papers SET status=?, updated_at=? WHERE id=?",
                 (row["status"], db.now(), pid))


def _load_paper(conn: sqlite3.Connection, user: sqlite3.Row, pid: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT p.*, u.display_name AS owner_name, u.username AS owner_username "
        "FROM papers p JOIN users u ON u.id=p.owner_id WHERE p.id=?",
        (pid,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "论文不存在")
    if user["role"] != "admin" and row["owner_id"] != user["id"]:
        raise HTTPException(403, "这不是你的论文，只有管理员能看别人的记录")
    return row


@app.get("/paper/{pid}", response_class=HTMLResponse)
def paper_detail(
    pid: int, request: Request, conn: sqlite3.Connection = Depends(get_conn), msg: str = ""
):
    user = require_user(request, conn)
    paper = _load_paper(conn, user, pid)
    subs = conn.execute(
        "SELECT * FROM submissions WHERE paper_id=? ORDER BY seq DESC", (pid,)
    ).fetchall()
    files = conn.execute(
        "SELECT f.*, u.display_name AS uploader FROM files f "
        "LEFT JOIN users u ON u.id=f.uploader_id WHERE f.paper_id=? ORDER BY f.id DESC",
        (pid,),
    ).fetchall()
    users = (
        conn.execute("SELECT id, display_name, username FROM users WHERE active=1 ORDER BY id").fetchall()
        if user["role"] == "admin"
        else []
    )
    roster = conn.execute("SELECT * FROM roster ORDER BY sort_order, id").fetchall()
    followup_secrets = _stored_secrets(conn)
    followup_scrub = lambda value: _scrub(value, followup_secrets)
    return render(
        request, conn, "paper_detail.html", user=user, paper=paper, subs=subs,
        files=files, users=users, roster=roster, msg=msg,
        max_mb=db.MAX_UPLOAD_BYTES // (1024 * 1024),
        progress=tracking.summary(conn,subs[0] if subs else None),
        events=tracking.events(conn,pid),
        followup=followup.get(conn,paper,followup_scrub),
        followup_events=followup.events(conn,pid,scrub=followup_scrub),
        followup_state_history=followup.revisions(conn,pid,followup_scrub),
        followup_stages=followup.LABELS,
        display_status=rounds.display_status, OUTCOMES=rounds.OUTCOMES,
        CATEGORY_NAMES=rounds.CATEGORY_NAMES,
    )


@app.post("/paper/{pid}/edit")
def paper_edit(
    pid: int,
    request: Request,
    title: str = Form(...),
    title_cn: str = Form(""),
    lead_author: str = Form(""),
    authors: str = Form(""),
    corresponding: str = Form(""),
    status: str = Form("撰写中"),
    notes: str = Form(""),
    current_note: Optional[str] = Form(None),
    code: str = Form(""),
    author_pos: str = Form(""),
    is_corresponding: str = Form(""),
    is_extra: str = Form(""),
    category: str = Form(""),
    follow_mode_value: Optional[str] = Form(None, alias="follow_mode"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    user = require_user(request, conn)
    cur = _load_paper(conn, user, pid)
    # 编号只有管理员能改，学生改不动（表单里对学生是只读的）
    is_admin = user["role"] == "admin"
    new_code = code.strip() if is_admin else cur["code"]
    new_pos = author_pos.strip() if is_admin else cur["author_pos"]
    new_corr = (1 if is_corresponding else 0) if is_admin else cur["is_corresponding"]
    new_cat = _form_category(category, is_extra) if is_admin else cur["category"]
    # 跟进方式是管理员口径（同 category）；字段缺省时沿用原值，旧页面提交不会清空
    new_mode = (follow_mode.parse(follow_mode_value)
                if is_admin and follow_mode_value is not None else cur["follow_mode"])
    new_current = cur["current_note"] if current_note is None else current_note.strip()
    conn.execute(
        "UPDATE papers SET title=?,title_cn=?,lead_author=?,authors=?,corresponding=?,"
        "status=?,notes=?,code=?,author_pos=?,is_corresponding=?,"
        "category=?,follow_mode=?,current_note=?,updated_at=? WHERE id=?",
        (
            title.strip(), title_cn.strip(), lead_author.strip(), authors.strip(),
            corresponding.strip(), status, notes.strip(), new_code,
            new_pos, new_corr, new_cat, new_mode, new_current, db.now(), pid,
        ),
    )
    follow_mode.sync(conn, pid, new_mode, user["username"])
    conn.commit()
    db.log(conn, user["username"], "paper.edit", f"#{pid}")
    return back(f"/paper/{pid}", "已保存")


@app.post("/paper/{pid}/transfer")
def paper_transfer(
    pid: int,
    request: Request,
    owner_id: int = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    user = require_admin(request, conn)
    conn.execute("UPDATE papers SET owner_id=?, updated_at=? WHERE id=?", (owner_id, db.now(), pid))
    conn.commit()
    db.log(conn, user["username"], "paper.transfer", f"#{pid} -> user {owner_id}")
    return back(f"/paper/{pid}", "归属已转移")


@app.post("/paper/{pid}/delete")
def paper_delete(pid: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    user = require_user(request, conn)
    _load_paper(conn, user, pid)
    conn.execute("DELETE FROM files WHERE paper_id=?", (pid,))
    conn.execute("DELETE FROM submissions WHERE paper_id=?", (pid,))
    conn.execute("DELETE FROM papers WHERE id=?", (pid,))
    conn.commit()
    folder = db.UPLOAD_DIR / str(pid)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    db.log(conn, user["username"], "paper.delete", f"#{pid}")
    return back("/", "论文已删除")


# ------------------------------------------------------------------ 投稿 / 转投记录

@app.post("/paper/{pid}/submission/new")
def submission_new(
    pid: int,
    request: Request,
    journal: str = Form(""),
    site_url: str = Form(""),
    sys_account: str = Form(""),
    sys_password: str = Form(""),
    submit_date: str = Form(""),
    manuscript_id: str = Form(""),
    status: str = Form("投稿中"),
    notes: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
):
    user = require_user(request, conn)
    _load_paper(conn, user, pid)
    row = conn.execute("SELECT MAX(seq) m FROM submissions WHERE paper_id=?", (pid,)).fetchone()
    seq = (row["m"] or 0) + 1
    ts = db.now()
    conn.execute(
        "INSERT INTO submissions(paper_id,seq,journal,site_url,sys_account,sys_password,"
        "submit_date,manuscript_id,status,notes,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            pid, seq, journal.strip(), site_url.strip(), sys_account.strip(), sys_password,
            submit_date.strip(), manuscript_id.strip(), status, notes.strip(), ts, ts,
        ),
    )
    conn.execute("UPDATE papers SET updated_at=? WHERE id=?", (ts, pid))
    conn.commit()
    sync_paper_status(conn, pid)
    conn.commit()
    db.log(conn, user["username"], "submission.new", f"paper#{pid} seq{seq} {journal}")
    return back(f"/paper/{pid}", f"第 {seq} 次投稿记录已添加")


@app.post("/submission/{sid}/edit")
def submission_edit(
    sid: int,
    request: Request,
    journal: str = Form(""),
    site_url: str = Form(""),
    sys_account: str = Form(""),
    sys_password: str = Form(""),
    submit_date: str = Form(""),
    manuscript_id: str = Form(""),
    status: str = Form("投稿中"),
    result_date: str = Form(""),
    notes: str = Form(""),
    outcome: Optional[str] = Form(None),
    conn: sqlite3.Connection = Depends(get_conn),
):
    user = require_user(request, conn)
    sub = conn.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
    if not sub:
        raise HTTPException(404, "投稿记录不存在")
    _load_paper(conn, user, sub["paper_id"])
    # 旧轮结局是管理员口径；学生表单不带这个字段，后端也不收
    new_outcome = sub["outcome"]
    if outcome is not None and user["role"] == "admin":
        new_outcome = rounds.check_outcome(outcome)
    ts = db.now()
    conn.execute(
        "UPDATE submissions SET journal=?,site_url=?,sys_account=?,sys_password=?,"
        "submit_date=?,manuscript_id=?,status=?,result_date=?,notes=?,outcome=?,updated_at=? WHERE id=?",
        (
            journal.strip(), site_url.strip(), sys_account.strip(), sys_password,
            submit_date.strip(), manuscript_id.strip(), status, result_date.strip(),
            notes.strip(), new_outcome, ts, sid,
        ),
    )
    conn.execute("UPDATE papers SET updated_at=? WHERE id=?", (ts, sub["paper_id"]))
    conn.commit()
    sync_paper_status(conn, sub['paper_id'])
    conn.commit()
    db.log(conn, user["username"], "submission.edit", f"#{sid}")
    return back(f"/paper/{sub['paper_id']}", "投稿记录已更新")


@app.post("/submission/{sid}/delete")
def submission_delete(sid: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    user = require_user(request, conn)
    sub = conn.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
    if not sub:
        raise HTTPException(404, "投稿记录不存在")
    _load_paper(conn, user, sub["paper_id"])
    conn.execute("DELETE FROM submissions WHERE id=?", (sid,))
    conn.commit()
    sync_paper_status(conn, sub['paper_id'])
    conn.commit()
    db.log(conn, user["username"], "submission.delete", f"#{sid}")
    return back(f"/paper/{sub['paper_id']}", "投稿记录已删除")


# ------------------------------------------------------------------ 投稿包文件

SAFE_NAME = re.compile(r"[^\w.\-一-鿿]+")


@app.post("/paper/{pid}/upload")
async def upload(
    pid: int,
    request: Request,
    label: str = Form(""),
    submission_id: str = Form(""),
    f: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    user = require_user(request, conn)
    _load_paper(conn, user, pid)
    orig = os.path.basename(f.filename or "unnamed")
    safe = SAFE_NAME.sub("_", orig)[:120] or "unnamed"
    folder = db.UPLOAD_DIR / str(pid)
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / f"{uuid.uuid4().hex[:8]}__{safe}"

    size = 0
    too_big = False
    with open(stored, "wb") as out:
        while True:
            chunk = await f.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > db.MAX_UPLOAD_BYTES:
                too_big = True
                break
            out.write(chunk)
    if too_big:
        stored.unlink(missing_ok=True)
        return back(f"/paper/{pid}", f"文件超过 {db.MAX_UPLOAD_BYTES // 1024 // 1024} MB 上限，没有保存")
    if size == 0:
        stored.unlink(missing_ok=True)
        return back(f"/paper/{pid}", "空文件，没有保存")

    sub_id = int(submission_id) if submission_id.strip().isdigit() else None
    conn.execute(
        "INSERT INTO files(paper_id,submission_id,orig_name,stored_path,size,label,"
        "uploader_id,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (pid, sub_id, orig, str(stored.relative_to(db.DATA_DIR)), size, label.strip(),
         user["id"], db.now()),
    )
    conn.execute("UPDATE papers SET updated_at=? WHERE id=?", (db.now(), pid))
    conn.commit()
    db.log(conn, user["username"], "file.upload", f"paper#{pid} {orig} {size}B")
    return back(f"/paper/{pid}", "文件已上传")


@app.get("/file/{fid}")
def download(fid: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    user = require_user(request, conn)
    row = conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
    if not row:
        raise HTTPException(404, "文件不存在")
    _load_paper(conn, user, row["paper_id"])
    path = db.DATA_DIR / row["stored_path"]
    if not path.exists():
        raise HTTPException(404, "文件已丢失（磁盘上找不到）")
    return FileResponse(path, filename=row["orig_name"], media_type="application/octet-stream")


@app.post("/file/{fid}/delete")
def file_delete(fid: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    user = require_user(request, conn)
    row = conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
    if not row:
        raise HTTPException(404, "文件不存在")
    _load_paper(conn, user, row["paper_id"])
    (db.DATA_DIR / row["stored_path"]).unlink(missing_ok=True)
    conn.execute("DELETE FROM files WHERE id=?", (fid,))
    conn.commit()
    db.log(conn, user["username"], "file.delete", f"#{fid}")
    return back(f"/paper/{row['paper_id']}", "文件已删除")


# ------------------------------------------------------------------ 公共投稿账号

@app.get("/accounts", response_class=HTMLResponse)
def accounts(request: Request, conn: sqlite3.Connection = Depends(get_conn), msg: str = ""):
    user = require_user(request, conn)
    rows = conn.execute("SELECT * FROM shared_accounts ORDER BY sort_order, id").fetchall()
    return render(request, conn, "accounts.html", user=user, rows=rows, msg=msg)


@app.post("/accounts/save")
def accounts_save(
    request: Request,
    id: str = Form(""),
    label: str = Form(""),
    platform: str = Form(""),
    url: str = Form(""),
    account: str = Form(""),
    password: str = Form(""),
    notes: str = Form(""),
    sort_order: str = Form("100"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    user = require_admin(request, conn)
    so = int(sort_order) if sort_order.strip().lstrip("-").isdigit() else 100
    if id.strip().isdigit():
        conn.execute(
            "UPDATE shared_accounts SET label=?,platform=?,url=?,account=?,password=?,"
            "notes=?,sort_order=?,updated_at=?,updated_by=? WHERE id=?",
            (label.strip(), platform.strip(), url.strip(), account.strip(), password,
             notes.strip(), so, db.now(), user["username"], int(id)),
        )
    else:
        conn.execute(
            "INSERT INTO shared_accounts(label,platform,url,account,password,notes,"
            "sort_order,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?,?)",
            (label.strip(), platform.strip(), url.strip(), account.strip(), password,
             notes.strip(), so, db.now(), user["username"]),
        )
    conn.commit()
    db.log(conn, user["username"], "account.save", label)
    return back("/accounts", "已保存")


@app.post("/accounts/{aid}/delete")
def accounts_delete(aid: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    user = require_admin(request, conn)
    conn.execute("DELETE FROM shared_accounts WHERE id=?", (aid,))
    conn.commit()
    db.log(conn, user["username"], "account.delete", str(aid))
    return back("/accounts", "已删除")


# ------------------------------------------------------------------ 花名册

@app.get("/roster", response_class=HTMLResponse)
def roster_page(request: Request, conn: sqlite3.Connection = Depends(get_conn), msg: str = ""):
    user = require_user(request, conn)
    rows = conn.execute("SELECT * FROM roster ORDER BY sort_order, id").fetchall()
    return render(request, conn, "roster.html", user=user, rows=rows, msg=msg)


@app.post("/roster/save")
def roster_save(
    request: Request,
    id: str = Form(""),
    cn_name: str = Form(""),
    en_name: str = Form(""),
    email: str = Form(""),
    affiliation: str = Form(""),
    role_note: str = Form(""),
    notes: str = Form(""),
    sort_order: str = Form("100"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    user = require_admin(request, conn)
    so = int(sort_order) if sort_order.strip().lstrip("-").isdigit() else 100
    if id.strip().isdigit():
        conn.execute(
            "UPDATE roster SET cn_name=?,en_name=?,email=?,affiliation=?,role_note=?,"
            "notes=?,sort_order=? WHERE id=?",
            (cn_name.strip(), en_name.strip(), email.strip(), affiliation.strip(),
             role_note.strip(), notes.strip(), so, int(id)),
        )
    else:
        conn.execute(
            "INSERT INTO roster(cn_name,en_name,email,affiliation,role_note,notes,sort_order) "
            "VALUES(?,?,?,?,?,?,?)",
            (cn_name.strip(), en_name.strip(), email.strip(), affiliation.strip(),
             role_note.strip(), notes.strip(), so),
        )
    conn.commit()
    db.log(conn, user["username"], "roster.save", cn_name or en_name)
    return back("/roster", "已保存")


@app.post("/roster/{rid}/delete")
def roster_delete(rid: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    user = require_admin(request, conn)
    conn.execute("DELETE FROM roster WHERE id=?", (rid,))
    conn.commit()
    return back("/roster", "已删除")


# ------------------------------------------------------------------ 教程 / 管理

@app.get("/guide", response_class=HTMLResponse)
def guide(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    return render(request, conn, "guide.html", max_mb=db.MAX_UPLOAD_BYTES // (1024 * 1024))


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, conn: sqlite3.Connection = Depends(get_conn), msg: str = ""):
    user = require_admin(request, conn)
    users = conn.execute(
        "SELECT u.*, (SELECT COUNT(*) FROM papers p WHERE p.owner_id=u.id) AS n_paper "
        "FROM users u ORDER BY u.id"
    ).fetchall()
    logs = conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 80").fetchall()
    return render(
        request, conn, "admin.html", user=user, users=users, logs=logs, msg=msg,
        invite_enabled=db.get_setting(conn, "invite_code_enabled", "0") == "1",
        invite_code=db.get_setting(conn, "invite_code", ""),
        api_token=db.get_setting(conn, "api_token", ""),
        api_write_token=db.get_setting(conn, "api_write_token", ""),
    )


@app.post("/admin/settings")
def admin_settings(
    request: Request,
    site_title: str = Form(""),
    notice: str = Form(""),
    invite_enabled: str = Form(""),
    invite_code: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
):
    user = require_admin(request, conn)
    db.set_setting(conn, "site_title", site_title.strip() or "课题组投稿台账")
    db.set_setting(conn, "notice", notice.strip())
    db.set_setting(conn, "invite_code_enabled", "1" if invite_enabled else "0")
    db.set_setting(conn, "invite_code", invite_code.strip())
    db.log(conn, user["username"], "settings.save")
    return back("/admin", "设置已保存")


@app.post("/admin/user/{uid}/toggle")
def admin_user_toggle(uid: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    user = require_admin(request, conn)
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        raise HTTPException(404, "用户不存在")
    if row["role"] == "admin":
        return back("/admin", "管理员账号不能停用")
    conn.execute("UPDATE users SET active=? WHERE id=?", (0 if row["active"] else 1, uid))
    conn.commit()
    db.log(conn, user["username"], "user.toggle", row["username"])
    return back("/admin", "已切换该账号状态")


@app.post("/admin/user/{uid}/reset")
def admin_user_reset(
    uid: int,
    request: Request,
    new_password: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    user = require_admin(request, conn)
    if len(new_password) < 4:
        return back("/admin", "新密码至少 4 位")
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (db.hash_password(new_password), uid))
    conn.commit()
    db.log(conn, user["username"], "user.reset", str(uid))
    return back("/admin", "密码已重置")


@app.get("/export.csv")
def export_csv(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    user = require_user(request, conn)
    if user["role"] == "admin":
        rows = conn.execute(
            "SELECT p.code, p.author_pos, p.is_corresponding, p.category, u.display_name owner, p.lead_author, p.title, p.title_cn, p.authors,"
            " p.corresponding, p.status, s.seq, s.journal, s.site_url, s.submit_date,"
            " s.manuscript_id, s.status sub_status, s.result_date, s.notes "
            "FROM papers p JOIN users u ON u.id=p.owner_id "
            "LEFT JOIN submissions s ON s.paper_id=p.id ORDER BY p.id, s.seq"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT p.code, p.author_pos, p.is_corresponding, p.category, u.display_name owner, p.lead_author, p.title, p.title_cn, p.authors,"
            " p.corresponding, p.status, s.seq, s.journal, s.site_url, s.submit_date,"
            " s.manuscript_id, s.status sub_status, s.result_date, s.notes "
            "FROM papers p JOIN users u ON u.id=p.owner_id "
            "LEFT JOIN submissions s ON s.paper_id=p.id WHERE p.owner_id=? ORDER BY p.id, s.seq",
            (user["id"],),
        ).fetchall()
    buf = io.StringIO()
    buf.write("﻿")  # Excel 中文 BOM
    w = csv.writer(buf)
    w.writerow([
        "编号", "作者位次", "是否通讯", "类别", "归属账号", "负责人", "英文标题", "中文标题", "作者顺序", "通讯作者",
        "论文状态", "第几次投稿", "期刊", "投稿系统网址", "投稿日期", "稿号",
        "本次投稿状态", "结果日期", "备注",
    ])
    for r in rows:
        w.writerow([r[k] if r[k] is not None else "" for k in r.keys()])
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="submissions.csv"'},
    )



# ================================================================== 只读 JSON API
# 给外部 AI / 脚本查论文进度用。Bearer token 认证，token 在管理页生成。
# 🔴 永不返回投稿系统账号密码——外部只读接口不碰凭证。

def api_auth(request: Request, conn: sqlite3.Connection, need_write: bool = False) -> str:
    """读 token 只能读；写 token 可读可写。返回本次用的是哪种，供审计。

    两个 token 分开是有意的：只读集成（例如只查进度的外部脚本）不该因为
    后来加了写能力就获得改数据的权限。
    """
    ro = db.get_setting(conn, "api_token", "")
    rw = db.get_setting(conn, "api_write_token", "")
    sent = request.headers.get("authorization", "")
    if sent.startswith("Bearer "):
        sent = sent[7:]
    sent = sent.strip()
    if not sent:
        raise HTTPException(401, "缺 Authorization: Bearer <token>")
    if rw and secrets.compare_digest(sent, rw):
        return "write"
    if not need_write and ro and secrets.compare_digest(sent, ro):
        return "read"
    if ro and secrets.compare_digest(sent, ro) and need_write:
        raise HTTPException(403, "这是只读 token，写操作需要写 token")
    if not ro and not rw:
        raise HTTPException(503, "API 未启用：请管理员先在管理页生成 token")
    raise HTTPException(401, "token 不对")


# API 输出字段白名单。加字段前先问：这条会不会把凭证带出去。
PAPER_FIELDS = ("code", "title", "title_cn", "status", "authors", "corresponding",
                "lead_author", "follow_mode", "follow_mode_label", "my_author_position",
                "i_am_corresponding", "category", "current_note", "notes", "updated_at", "submission_count", "current_journal",
                "submissions", "current_submission", "days_since_current_submit", "files", "events",
                "review_stage", "last_progress_date", "last_checked_date", "days_without_progress",
                "days_since_last_check", "revision_due_date", "revision_days_remaining", "progress_date_basis")
SUBMISSION_FIELDS = ("id", "seq", "journal", "submit_date", "manuscript_id", "status",
                     "outcome", "display_status",
                     "is_current", "result_date", "site_url", "notes")

# 兜底脱敏：自由文本（notes / 标题 / 网址…）万一被人粘进凭证，不许经接口出去。
_CRED_PAT = re.compile(r"(?:密码|password|passwd|pwd|口令|token|secret)\s*[:：=]\s*\S+"
                       r"|://[^/\s:]+:[^@\s]+@", re.I)
_NAME_LIKE = re.compile(r"[A-Za-z][A-Za-z .'-]{2,}$")


def _stored_secrets(conn: sqlite3.Connection) -> list:
    """库里存着的真实凭证值，用来反查自由文本。排除被误填成人名的账号栏。"""
    out = credential_vault.secret_values(conn)
    for sql in ("SELECT DISTINCT sys_password v FROM submissions WHERE LENGTH(sys_password)>=6",
                "SELECT DISTINCT sys_account  v FROM submissions WHERE LENGTH(sys_account)>=6",
                "SELECT DISTINCT password v FROM shared_accounts WHERE LENGTH(password)>=6",
                "SELECT DISTINCT account  v FROM shared_accounts WHERE LENGTH(account)>=6",
                "SELECT DISTINCT sys_cookie v FROM submissions WHERE LENGTH(sys_cookie)>=1"):
        for r in conn.execute(sql):
            if not _NAME_LIKE.fullmatch(r["v"] or ""):
                out.append(r["v"])
    # Extra credentials may contain arbitrary nested cookies/tokens.
    def values(v):
        if isinstance(v,str):return [v] if len(v)>=4 else []
        if isinstance(v,dict):return [x for child in v.values() for x in values(child)]
        if isinstance(v,list):return [x for child in v for x in values(child)]
        return []
    for row in conn.execute("SELECT credential_extra FROM submissions"):
        extra=json.loads(row[0])
        out.extend(values(extra))
    # Cookie values often occur without their cookie names in pasted notes.
    for row in conn.execute("SELECT sys_cookie FROM submissions WHERE sys_cookie!=''"):
        raw=row[0]
        try:
            parsed=json.loads(raw)
        except json.JSONDecodeError:
            out.extend(v.strip() for k,v in re.findall(r'([^;=]+)=([^;]+)',raw) if len(v.strip())>=4)
        else:
            out.extend(values(parsed))
    return sorted(set(out),key=len,reverse=True)


def _scrub(text: str, secrets_list: list) -> str:
    if not text:
        return text
    for sec in secrets_list:
        if sec and sec in text:
            text = text.replace(sec, "[已脱敏]")
    return _CRED_PAT.sub("[已脱敏]", text)


def _days_since(date_str: str) -> Optional[int]:
    """submit_date 到今天的自然日数。日期是不带时区的纯日期，按服务器本地日期算。"""
    try:
        d = datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None
    return (datetime.now().date() - d).days


def _paper_json(conn: sqlite3.Connection, p: sqlite3.Row, with_subs: bool = True,
                secrets_list: Optional[list] = None) -> dict:
    sl = secrets_list if secrets_list is not None else _stored_secrets(conn)
    sc = lambda t: _scrub(t, sl)
    d = {
        "code": p["code"],
        "title": sc(p["title"]),
        "title_cn": sc(p["title_cn"]),
        "status": p["status"],
        "authors": [a.strip() for a in (p["authors"] or "").replace("\r", "\n").split("\n") if a.strip()],
        "corresponding": sc(p["corresponding"]),
        "lead_author": sc(p["lead_author"]),
        "follow_mode": p["follow_mode"],
        "follow_mode_label": follow_mode.label(p["follow_mode"]),
        "current_note": sc(p["current_note"]),
        "my_author_position": p["author_pos"],
        "i_am_corresponding": bool(p["is_corresponding"]),
        "category": rounds.category_name(p["category"]),
        "notes": sc(p["notes"]),
        "updated_at": p["updated_at"],
    }
    if with_subs:
        subs = conn.execute(
            "SELECT * FROM submissions WHERE paper_id=? ORDER BY seq DESC", (p["id"],)
        ).fetchall()
        items = [{
            "id": s["id"],  # paper sub-edit / rm-sub 用的记录号
            "seq": s["seq"],
            "journal": sc(s["journal"]),
            "submit_date": s["submit_date"] or None,
            "manuscript_id": s["manuscript_id"] or None,
            # 只有最新一次有真状态；更早的一律「已转投」（由结构推导，非存储值）
            "status": s["status"] if i == 0 else "已转投",
            # 旧轮真实结局（补录值）与给人看的状态；status 保持原取值兼容老调用方
            "outcome": s["outcome"],
            "display_status": rounds.display_status(s["status"], s["outcome"], i == 0),
            "is_current": i == 0,
            "result_date": s["result_date"] or None,
            "site_url": sc(s["site_url"]) or None,
            "notes": sc(s["notes"]) or None,
        } for i, s in enumerate(subs)]
        d["submission_count"] = len(items)
        d["current_journal"] = items[0]["journal"] if items else None
        d["current_submission"] = items[0] if items else None
        d["days_since_current_submit"] = (
            _days_since(items[0]["submit_date"]) if items and items[0]["submit_date"] else None)
        d["submissions"] = items
        d.update(tracking.summary(conn,subs[0] if subs else None))
        for item, sub in zip(items, subs):
            item['credentials_present'] = {k: bool(sub[k]) for k in ('sys_account','sys_password','sys_cookie')}
    return d


@app.get("/api/v1/papers")
def api_papers(
    request: Request,
    status: str = "",
    position: str = "",
    q: str = "",
    conn: sqlite3.Connection = Depends(get_conn),
):
    api_auth(request, conn)
    sql, args = "SELECT * FROM papers WHERE 1=1", []
    if status:
        sql += " AND status=?"; args.append(status)
    if position:
        sql += " AND author_pos=?"; args.append(position)
    if q:
        sql += " AND (title LIKE ? OR title_cn LIKE ? OR code LIKE ?)"; args += [f"%{q}%"] * 3
    sql += " ORDER BY code"
    rows = conn.execute(sql, args).fetchall()
    sl = _stored_secrets(conn)
    return JSONResponse({
        "count": len(rows),
        "server_time": db.now(),
        "timezone": db.TIMEZONE,
        "papers": [_paper_json(conn, r, secrets_list=sl) for r in rows],
    })


@app.get("/api/v1/papers/{code}")
def api_paper(code: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    api_auth(request, conn)
    row = conn.execute("SELECT * FROM papers WHERE code=? COLLATE NOCASE", (code,)).fetchone()
    if not row:
        raise HTTPException(404, f"没有编号为 {code} 的论文")
    d = _paper_json(conn, row)
    sl = _stored_secrets(conn)
    d["files"] = [{"id": f["id"], "kind": f["kind"], "submission_id": f["submission_id"], "name": _scrub(f["orig_name"], sl),
                   "size_mb": round(f["size"] / 1048576, 2),
                   "label": _scrub(f["label"], sl), "uploaded_at": f["created_at"]}
                  for f in conn.execute(
                      "SELECT * FROM files WHERE paper_id=? ORDER BY id", (row["id"],))]
    d["events"] = tracking.events(conn,row["id"],scrub=lambda t:_scrub(t,sl))
    d["server_time"] = db.now()
    d["timezone"] = db.TIMEZONE
    return JSONResponse(d)


@app.get("/api/v1/stats")
def api_stats(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    api_auth(request, conn)
    g = lambda sql: {r[0]: r[1] for r in conn.execute(sql)}
    return JSONResponse({
        "total": conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
        "by_status": g("SELECT status, COUNT(*) FROM papers GROUP BY status"),
        "by_author_position": g(
            "SELECT author_pos, COUNT(*) FROM papers WHERE author_pos!='' GROUP BY author_pos"),
        "corresponding_count": conn.execute(
            "SELECT COUNT(*) FROM papers WHERE is_corresponding=1").fetchone()[0],
        # 其他论文、合作方论文单列；main_series 只算主序列，不含这两类
        "by_category": {name: conn.execute("SELECT COUNT(*) FROM papers WHERE category=?",
                                           (key,)).fetchone()[0]
                        for key, name in rounds.CATEGORY_NAMES.items()},
        "main_series": {
            "total": conn.execute("SELECT COUNT(*) FROM papers WHERE category='main'").fetchone()[0],
            "by_status": g("SELECT status, COUNT(*) FROM papers WHERE category='main' GROUP BY status"),
            "by_author_position": g("SELECT author_pos, COUNT(*) FROM papers "
                                    "WHERE category='main' AND author_pos!='' GROUP BY author_pos"),
            "corresponding_count": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE category='main' AND is_corresponding=1").fetchone()[0],
        },
        "generated_at": db.now(),
        "timezone": db.TIMEZONE,
    })


@app.get("/api/v1/openapi.json")
def api_openapi(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    api_auth(request, conn)
    spec = BASE_DIR.parent / "docs" / "api" / "openapi.json"
    if not spec.exists():
        raise HTTPException(404, "openapi.json 不在服务器上")
    return JSONResponse(json.loads(spec.read_text(encoding="utf-8")))


@app.post("/admin/api-token")
def admin_api_token(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    user = require_admin(request, conn)
    db.set_setting(conn, "api_token", secrets.token_urlsafe(32))
    db.log(conn, user["username"], "api_token.rotate")
    return back("/admin", "API token 已重新生成")



# ============================================================ 写接口（需写 token）
# 只有写 token 能调。所有写操作都记审计日志，删除前自动打数据库快照。

PAPER_WRITABLE = {"title", "title_cn", "lead_author", "authors", "corresponding",
                  "status", "notes", "current_note", "author_pos", "is_corresponding", "category",
                  "code", "follow_mode"}
SUB_WRITABLE = {"journal", "site_url", "sys_account", "sys_password", "submit_date",
                "manuscript_id", "status", "result_date", "notes", "outcome"}


def _snapshot(tag: str) -> str:
    """破坏性操作前的数据库快照。删除不可恢复、库又小，这一步不省。"""
    out = db.DATA_DIR / "backups" / f"portal.{datetime.now():%Y%m%d-%H%M%S}.{tag}.db"
    out.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(db.DB_PATH); dst = sqlite3.connect(out)
    src.backup(dst); dst.close(); src.close()
    return out.name


def _norm_authors(v) -> str:
    if isinstance(v, list):
        return "\n".join(str(x).strip() for x in v if str(x).strip())
    return str(v or "")


def _check_enum(field: str, val: str, allowed: list) -> None:
    if val and val not in allowed:
        raise HTTPException(422, f"{field} 只能是 {allowed} 之一，收到 {val!r}")


async def _body(request: Request) -> dict:
    try:
        d = await request.json()
    except Exception:
        raise HTTPException(400, "请求体必须是 JSON")
    if not isinstance(d, dict):
        raise HTTPException(400, "请求体必须是 JSON 对象")
    return d


def _paper_by_code(conn: sqlite3.Connection, code: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM papers WHERE code=? COLLATE NOCASE", (code,)).fetchone()
    if not row:
        raise HTTPException(404, f"没有编号为 {code} 的论文")
    return row


@app.post("/api/v1/papers", status_code=201)
async def api_paper_create(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    api_auth(request, conn, need_write=True)
    b = await _body(request)
    title = str(b.get("title", "")).strip()
    if not title:
        raise HTTPException(422, "title 必填")
    _check_enum("status", b.get("status", ""), db.PAPER_STATUS)
    status = b.get("status") or "撰写中"
    cat = rounds.parse_category(b["category"]) if b.get("category") else "main"
    mode = follow_mode.parse(b.get("follow_mode", ""))
    admin = conn.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
    ts = db.now()
    pid = conn.execute(
        "INSERT INTO papers(owner_id,title,title_cn,lead_author,authors,corresponding,"
        "status,notes,current_note,author_pos,is_corresponding,category,code,follow_mode,"
        "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (admin["id"], title, str(b.get("title_cn", "")).strip(),
         str(b.get("lead_author", "")).strip(), _norm_authors(b.get("authors")),
         str(b.get("corresponding", "")).strip(), status, str(b.get("notes", "")).strip(),
         str(b.get("current_note", "")).strip(),
         str(b.get("author_pos", "")).strip(), 1 if b.get("is_corresponding") else 0,
         cat, next_code(conn, cat, status), mode, ts, ts)).lastrowid
    follow_mode.sync(conn, pid, mode, "api")
    conn.commit()
    row = conn.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
    db.log(conn, "api", "paper.new", f"{row['code']} {title[:40]}")
    return JSONResponse(_paper_json(conn, row), status_code=201)


@app.patch("/api/v1/papers/{code}")
async def api_paper_patch(code: str, request: Request,
                          conn: sqlite3.Connection = Depends(get_conn)):
    api_auth(request, conn, need_write=True)
    row = _paper_by_code(conn, code)
    b = await _body(request)
    bad = set(b) - PAPER_WRITABLE
    if bad:
        raise HTTPException(422, f"这些字段不可写：{sorted(bad)}；可写：{sorted(PAPER_WRITABLE)}")
    _check_enum("status", b.get("status", ""), db.PAPER_STATUS)
    # 先校验再动任何数据：非法 follow_mode 不能让前面的状态改动留在事务里
    mode = follow_mode.parse(b["follow_mode"]) if "follow_mode" in b else None
    latest=conn.execute('SELECT id,status FROM submissions WHERE paper_id=? ORDER BY seq DESC LIMIT 1',(row['id'],)).fetchone()
    if b.get('status')=='撰写中' and latest:
        raise HTTPException(422,'已有投稿记录不能改为撰写中；请更新当前轮状态')
    if b.get('status') and latest:
        tracking.record_status_change(conn,row['id'],latest['id'],latest['status'],b['status'])
        conn.execute('UPDATE submissions SET status=?,updated_at=? WHERE id=?',(b['status'],db.now(),latest['id']))
    sets, args = [], []
    for k, v in b.items():
        if k == "authors":
            v = _norm_authors(v)
        elif k == "is_corresponding":
            v = 1 if v else 0
        elif k == "category":
            v = rounds.parse_category(v)
        elif k == "follow_mode":
            v = mode
        else:
            v = str(v).strip()
        sets.append(f"{k}=?"); args.append(v)
    if sets:
        sets.append("updated_at=?"); args.append(db.now()); args.append(row["id"])
        conn.execute(f"UPDATE papers SET {','.join(sets)} WHERE id=?", args)
        if mode is not None:
            follow_mode.sync(conn, row["id"], mode, "api")
        conn.commit()
    db.log(conn, "api", "paper.edit", f"{row['code']} 字段 {sorted(b)}")
    return JSONResponse(_paper_json(conn, conn.execute(
        "SELECT * FROM papers WHERE id=?", (row["id"],)).fetchone()))


@app.post("/api/v1/papers/{code}/submissions", status_code=201)
async def api_sub_create(code: str, request: Request,
                         conn: sqlite3.Connection = Depends(get_conn)):
    """新增一轮投稿（= 转投）。旧轮自动变历史，不会被删。

    history=true 是补录更早的一轮：按 submit_date 插到对应位置，后面的轮次顺延，
    论文状态和当前轮不变。"""
    api_auth(request, conn, need_write=True)
    row = _paper_by_code(conn, code)
    b = await _body(request)
    history = b.pop("history", False)
    if type(history) is not bool:
        raise HTTPException(422, "history 必须是布尔值")
    for key in ('submit_date','result_date'):
        if key in b:tracking.valid_date(b[key],key,allow_empty=True)
    if history:
        tracking.valid_date(b.get("submit_date", ""), "submit_date（补录历史轮必填）")
    bad = set(b) - SUB_WRITABLE
    if bad:
        raise HTTPException(422, f"这些字段不可写：{sorted(bad)}")
    if not str(b.get("journal", "")).strip():
        raise HTTPException(422, "journal 必填")
    _check_enum("status", b.get("status", ""), db.SUBMISSION_STATUS)
    if "outcome" in b:
        rounds.check_outcome(b["outcome"])
    conn.execute("BEGIN IMMEDIATE")
    if history:
        try:
            seq = rounds.history_seq(conn, row["id"], b["submit_date"])
        except HTTPException:
            conn.rollback()
            raise
    else:
        seq = (conn.execute("SELECT MAX(seq) m FROM submissions WHERE paper_id=?",
                            (row["id"],)).fetchone()["m"] or 0) + 1
    ts = db.now()
    conn.execute(
        "INSERT INTO submissions(paper_id,seq,journal,site_url,sys_account,sys_password,"
        "submit_date,manuscript_id,status,result_date,notes,outcome,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (row["id"], seq, str(b.get("journal")).strip(), str(b.get("site_url", "")).strip(),
         str(b.get("sys_account", "")).strip(), str(b.get("sys_password", "")),
         str(b.get("submit_date", "")).strip(), str(b.get("manuscript_id", "")).strip(),
         b.get("status") or "投稿中", str(b.get("result_date", "")).strip(),
         str(b.get("notes", "")).strip(), b.get("outcome", ""), ts, ts))
    if history:
        # 补录不碰论文状态；只刷新更新时间让列表页轮询感知
        conn.execute("UPDATE papers SET updated_at=? WHERE id=?", (ts, row["id"]))
        conn.commit()
        db.log(conn, "api", "submission.history",
               f"{row['code']} 补录 seq{seq} {b.get('journal')} {b['submit_date']}，原 seq>={seq} 顺延 +1")
    else:
        sync_paper_status(conn, row["id"]); conn.commit()
        db.log(conn, "api", "submission.new", f"{row['code']} seq{seq} {b.get('journal')}")
    return JSONResponse(_paper_json(conn, conn.execute(
        "SELECT * FROM papers WHERE id=?", (row["id"],)).fetchone()), status_code=201)


@app.patch("/api/v1/submissions/{sid}")
async def api_sub_patch(sid: int, request: Request,
                        conn: sqlite3.Connection = Depends(get_conn)):
    api_auth(request, conn, need_write=True)
    sub = conn.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
    if not sub:
        raise HTTPException(404, f"没有 id={sid} 的投稿记录")
    b = await _body(request)
    for key in ('submit_date','result_date'):
        if key in b:tracking.valid_date(b[key],key,allow_empty=True)
    bad = set(b) - SUB_WRITABLE
    if bad:
        raise HTTPException(422, f"这些字段不可写：{sorted(bad)}")
    _check_enum("status", b.get("status", ""), db.SUBMISSION_STATUS)
    if "outcome" in b:
        rounds.check_outcome(b["outcome"])
    sets, args = [], []
    for k, v in b.items():
        sets.append(f"{k}=?"); args.append(v if k == "sys_password" else str(v).strip())
    sets.append("updated_at=?"); args.append(db.now()); args.append(sid)
    conn.execute(f"UPDATE submissions SET {','.join(sets)} WHERE id=?", args)
    if b.get('status'):
        tracking.record_status_change(conn,sub['paper_id'],sid,sub['status'],b['status'])
    sync_paper_status(conn, sub["paper_id"]); conn.commit()
    p = conn.execute("SELECT * FROM papers WHERE id=?", (sub["paper_id"],)).fetchone()
    db.log(conn, "api", "submission.edit", f"{p['code']} sub#{sid} 字段 {sorted(b)}")
    return JSONResponse(_paper_json(conn, p))


@app.post("/api/v1/papers/{code}/files", status_code=201)
async def api_file_upload(code: str, request: Request,
                          label: str = Form(""), submission_seq: str = Form(""),
                          kind: str = Form("other"),
                          f: UploadFile = File(...),
                          conn: sqlite3.Connection = Depends(get_conn)):
    """上传投稿包 / 修改稿 / LaTeX 源。multipart/form-data。"""
    api_auth(request, conn, need_write=True)
    row = _paper_by_code(conn, code)
    if kind not in tracking.FILE_KINDS:
        raise HTTPException(422,'无效附件 kind')
    if submission_seq and (not submission_seq.isdigit() or int(submission_seq)<1):
        raise HTTPException(422,'submission_seq 必须为正整数')
    sub_id = None
    if str(submission_seq).strip().isdigit():
        r = conn.execute("SELECT id FROM submissions WHERE paper_id=? AND seq=?",
                         (row["id"], int(submission_seq))).fetchone()
        if not r:
            raise HTTPException(422, f"{row['code']} 没有第 {submission_seq} 次投稿")
        sub_id = r["id"]
    orig = os.path.basename(f.filename or "unnamed")
    safe = SAFE_NAME.sub("_", orig)[:120] or "unnamed"
    folder = db.UPLOAD_DIR / str(row["id"]); folder.mkdir(parents=True, exist_ok=True)
    stored = folder / f"{uuid.uuid4().hex[:8]}__{safe}"
    size, too_big = 0, False
    with open(stored, "wb") as out:
        while True:
            chunk = await f.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > db.MAX_UPLOAD_BYTES:
                too_big = True; break
            out.write(chunk)
    if too_big or size == 0:
        stored.unlink(missing_ok=True)
        raise HTTPException(413 if too_big else 422,
                            f"超过 {db.MAX_UPLOAD_BYTES // 1048576} MB 上限" if too_big else "空文件")
    cur = conn.execute(
        "INSERT INTO files(paper_id,submission_id,orig_name,stored_path,size,label,kind,"
        "uploader_id,created_at) VALUES(?,?,?,?,?,?,?,NULL,?)",
        (row["id"], sub_id, orig, str(stored.relative_to(db.DATA_DIR)), size,
         label.strip(), kind, db.now()))
    conn.execute("UPDATE papers SET updated_at=? WHERE id=?", (db.now(), row["id"]))
    conn.commit()
    db.log(conn, "api", "file.upload", f"{row['code']} {orig} {size}B")
    return JSONResponse({"ok": True, "id": cur.lastrowid, "kind": kind, "paper": row["code"], "name": orig,
                         "size_mb": round(size / 1048576, 2),
                         "submission_seq": int(submission_seq) if sub_id else None},
                        status_code=201)


@app.delete("/api/v1/submissions/{sid}")
def api_sub_delete(sid: int, request: Request, confirm: str = "",
                   conn: sqlite3.Connection = Depends(get_conn)):
    api_auth(request, conn, need_write=True)
    sub = conn.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
    if not sub:
        raise HTTPException(404, f"没有 id={sid} 的投稿记录")
    if confirm != str(sid):
        raise HTTPException(428, f"删除不可恢复。确认请带 ?confirm={sid}")
    snap = _snapshot(f"before-del-sub{sid}")
    conn.execute("DELETE FROM submissions WHERE id=?", (sid,))
    sync_paper_status(conn, sub["paper_id"]); conn.commit()
    db.log(conn, "api", "submission.delete", f"sub#{sid} 快照 {snap}")
    return JSONResponse({"ok": True, "deleted_submission": sid, "snapshot": snap})


@app.delete("/api/v1/papers/{code}")
def api_paper_delete(code: str, request: Request, confirm: str = "",
                     conn: sqlite3.Connection = Depends(get_conn)):
    api_auth(request, conn, need_write=True)
    row = _paper_by_code(conn, code)
    if confirm != row["code"]:
        raise HTTPException(428, f"删除会连投稿记录和附件一起删且不可恢复。"
                                 f"确认请带 ?confirm={row['code']}")
    snap = _snapshot(f"before-del-{row['code']}")
    conn.execute("DELETE FROM files WHERE paper_id=?", (row["id"],))
    conn.execute("DELETE FROM submissions WHERE paper_id=?", (row["id"],))
    conn.execute("DELETE FROM papers WHERE id=?", (row["id"],))
    conn.commit()
    shutil.rmtree(db.UPLOAD_DIR / str(row["id"]), ignore_errors=True)
    db.log(conn, "api", "paper.delete", f"{row['code']} 快照 {snap}")
    return JSONResponse({"ok": True, "deleted_paper": row["code"], "snapshot": snap})


@app.post("/admin/api-write-token")
def admin_api_write_token(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    user = require_admin(request, conn)
    db.set_setting(conn, "api_write_token", secrets.token_urlsafe(32))
    db.log(conn, user["username"], "api_write_token.rotate")
    return back("/admin", "写 token 已重新生成")


import sys
import credential_vault
import tracking_api
tracking_api.register(app, sys.modules[__name__])
import followup_api
followup_api.register(app, sys.modules[__name__])
credential_vault.register(app, sys.modules[__name__])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8611"))
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port, log_level="info")
