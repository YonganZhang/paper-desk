"""课题组投稿台账 — 数据层。

单文件 SQLite，落在 `$PORTAL_DATA_DIR/portal.db`（默认 `ledger/data/`）。
上传的投稿包落在 `$PORTAL_DATA_DIR/uploads/<paper_id>/`。
部署相关的配置项（环境变量）都在本文件顶部读取，说明见 README「配置项」。
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# 默认放在程序目录下的 data/（已在 .gitignore 里排除），部署时建议用 PORTAL_DATA_DIR 指到程序目录之外
DATA_DIR = Path(os.environ.get("PORTAL_DATA_DIR", Path(__file__).resolve().parent / "data"))
DB_PATH = DATA_DIR / "portal.db"
UPLOAD_DIR = DATA_DIR / "uploads"

# 台账「本人」的姓名（作者位次、是否通讯都是相对这个人记的）。逗号分隔，可写中英文多个写法；
# 界面标签用第一个，没配置时显示「本人」。
OWNER_NAMES = [n.strip() for n in os.environ.get("PAPER_DESK_OWNER_NAMES", "").split(",") if n.strip()]
OWNER_LABEL = OWNER_NAMES[0] if OWNER_NAMES else "本人"

# 跟进计划时间戳与接口 timezone 字段用的时区（IANA 名）。纯日期（投稿日、天数）按服务器本地日期算，
# 部署时让进程的 TZ 与它一致。
TIMEZONE = os.environ.get("PAPER_DESK_TZ", "Asia/Shanghai")


def tz_offset() -> str:
    """TIMEZONE 此刻的 UTC 偏移，形如 +08:00；网页表单提交本地时间时拼在后面。"""
    from zoneinfo import ZoneInfo
    raw = datetime.now(ZoneInfo(TIMEZONE)).strftime("%z")
    return f"{raw[:3]}:{raw[3:]}"

MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB

# 状态只有这几个。核心判断：「投稿中」就是在审，转投不是新状态——
# 转投只是「投稿的第 N 次」，次数由 submissions.seq 表达，不占状态位。
PAPER_STATUS = [
    "撰写中",     # 还没投出去
    "投稿中",     # 投出去了、在审（第几次看 seq）
    "已录用",
    "被拒",       # 最新一次被拒、还没转投下一家
    "撤稿",
]

# 单次投稿的结局。和论文状态共用同一套词，去掉「撰写中」。
SUBMISSION_STATUS = ["投稿中", "已录用", "被拒", "撤稿"]

# 同词表，最新一次投稿的状态直接就是论文状态
SUB_TO_PAPER = {k: k for k in SUBMISSION_STATUS}


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: async 路由的依赖在线程池里建连接、在事件循环线程里用。
    # 每个请求一条独立连接，不跨请求共享，所以线程校验可以关掉。
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name  TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'student',   -- admin / student
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS papers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id       INTEGER NOT NULL REFERENCES users(id),
    title          TEXT NOT NULL,
    title_cn       TEXT NOT NULL DEFAULT '',
    lead_author    TEXT NOT NULL DEFAULT '',   -- 论文负责人 / 主要写作人（中文名）
    authors        TEXT NOT NULL DEFAULT '',   -- 作者顺序，一行一个或逗号分隔
    corresponding  TEXT NOT NULL DEFAULT '',   -- 通讯作者
    status         TEXT NOT NULL DEFAULT '撰写中',
    notes          TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS submissions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id      INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL DEFAULT 1,      -- 第几次投稿（1 = 首投，2+ = 转投）
    journal       TEXT NOT NULL DEFAULT '',
    site_url      TEXT NOT NULL DEFAULT '',        -- 投稿系统网址
    sys_account   TEXT NOT NULL DEFAULT '',        -- 投稿系统账号
    sys_password  TEXT NOT NULL DEFAULT '',        -- 投稿系统密码
    submit_date   TEXT NOT NULL DEFAULT '',
    manuscript_id TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT '投稿中',
    result_date   TEXT NOT NULL DEFAULT '',
    notes         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id      INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    submission_id INTEGER,
    orig_name     TEXT NOT NULL,
    stored_path   TEXT NOT NULL,
    size          INTEGER NOT NULL DEFAULT 0,
    label         TEXT NOT NULL DEFAULT '',
    uploader_id   INTEGER,
    created_at    TEXT NOT NULL
);

-- 公共投稿账号池：所有登录用户可见（老师的个人投稿邮箱 / 各系统账号）
CREATE TABLE IF NOT EXISTS shared_accounts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    label      TEXT NOT NULL DEFAULT '',   -- 例如「Elsevier 通用投稿邮箱」
    platform   TEXT NOT NULL DEFAULT '',   -- Elsevier EM / ScholarOne / Springer 等
    url        TEXT NOT NULL DEFAULT '',
    account    TEXT NOT NULL DEFAULT '',
    password   TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 100,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT ''
);

-- 课题组花名册：所有登录用户可见
CREATE TABLE IF NOT EXISTS roster (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cn_name     TEXT NOT NULL DEFAULT '',
    en_name     TEXT NOT NULL DEFAULT '',
    email       TEXT NOT NULL DEFAULT '',
    affiliation TEXT NOT NULL DEFAULT '',
    role_note   TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL,
    actor  TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sub_paper ON submissions(paper_id);
CREATE INDEX IF NOT EXISTS idx_file_paper ON files(paper_id);
CREATE INDEX IF NOT EXISTS idx_paper_owner ON papers(owner_id);
"""


# ---------------------------------------------------------------- 密码

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"pbkdf2_sha256$200000${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iters))
    return secrets.compare_digest(dk.hex(), digest)


# ---------------------------------------------------------------- 设置

def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def log(conn: sqlite3.Connection, actor: str, action: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO audit(ts, actor, action, detail) VALUES(?,?,?,?)",
        (now(), actor, action, detail),
    )
    conn.commit()


# ---------------------------------------------------------------- 初始化

def ensure_admin(conn: sqlite3.Connection, username: str, password: str) -> bool:
    """没有管理员账号时建一个；已有管理员则不动（口令由管理员自己在「我的账号」改）。返回是否新建。"""
    if conn.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        return False
    if not password:
        raise ValueError("管理员口令不能为空")
    if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        raise ValueError(f"账号 {username!r} 已存在但不是管理员；换一个 PAPER_DESK_ADMIN_USER")
    conn.execute(
        "INSERT INTO users(username, password_hash, display_name, role, active, created_at) "
        "VALUES(?,?,?,?,1,?)",
        (username, hash_password(password), "管理员", "admin", now()),
    )
    conn.commit()
    return True


def admin_username() -> str:
    return os.environ.get("PAPER_DESK_ADMIN_USER", "admin").strip() or "admin"


def init_db(create_admin: bool = True) -> None:
    """建表 + 增量迁移 + 默认设置。create_admin=False 留给 seed.py（它自己交互式问口令）。"""
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    from tracking import migrate
    migrate(conn)
    from followup import migrate as migrate_followup
    migrate_followup(conn)

    # 首次启动建管理员：账号/口令取环境变量；没给口令就随机生成，只在 stderr 打印这一次
    if create_admin:
        username = admin_username()
        password = os.environ.get("PAPER_DESK_ADMIN_PASSWORD", "")
        generated = not password
        if generated:
            password = secrets.token_urlsafe(12)
        if ensure_admin(conn, username, password) and generated:
            print(f"[paper-desk] 首次启动，已创建管理员 {username}，初始口令：{password}\n"
                  f"[paper-desk] 口令只显示这一次，登录后请在「我的账号」修改。", file=sys.stderr, flush=True)

    if not get_setting(conn, "site_title"):
        set_setting(conn, "site_title", "课题组投稿台账")
    # 新装默认关闭开放注册：要邀请码（随机生成，管理员在后台查看或修改），想完全开放可在后台关掉邀请码
    if not get_setting(conn, "invite_code_enabled"):
        set_setting(conn, "invite_code_enabled", "1")
    if not get_setting(conn, "invite_code"):
        set_setting(conn, "invite_code", secrets.token_urlsafe(8))
    if not get_setting(conn, "notice"):
        set_setting(
            conn,
            "notice",
            "投稿 / 转投后请当天在这里补一条记录：期刊、投稿系统网址、账号密码、投稿日期，并把投稿包传上来。",
        )
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"initialized: {DB_PATH}")
