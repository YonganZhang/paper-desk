#!/usr/bin/env python3
"""初始化投稿台账：建表、建管理员，可选生成 API token、导入虚构样例。幂等，可重复跑。

    python3 seed.py                    # 建管理员（已有管理员则跳过）
    python3 seed.py --api-tokens       # 另外生成只读 / 写 API token（已有则不动）
    python3 seed.py --samples          # 另外导入 examples/sample_papers.json 的虚构样例

管理员账号取 PAPER_DESK_ADMIN_USER（默认 admin）；口令取 PAPER_DESK_ADMIN_PASSWORD，
没设时在终端里交互输入（非交互环境直接报错退出，不会偷偷生成弱口令）。
数据目录取 PORTAL_DATA_DIR（默认 ./data）。

导入样例只 INSERT 缺失的论文（按编号判断），已有的编号整篇跳过；从不删除或覆盖已有记录。
退出码：0 成功，1 失败（原因写在 stderr）。
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import secrets
import sys
from pathlib import Path

import db

SAMPLES = Path(__file__).resolve().parent / "examples" / "sample_papers.json"


def ask_password() -> str:
    pw = os.environ.get("PAPER_DESK_ADMIN_PASSWORD", "")
    if pw:
        return pw
    if not sys.stdin.isatty():
        sys.exit("seed: 没有 PAPER_DESK_ADMIN_PASSWORD，且当前不是交互终端，无法询问管理员口令")
    pw = getpass.getpass("设置管理员口令（至少 8 位）：")
    if len(pw) < 8:
        sys.exit("seed: 口令太短，至少 8 位")
    if getpass.getpass("再输一次：") != pw:
        sys.exit("seed: 两次输入不一致")
    return pw


def ensure_tokens(conn) -> list:
    made = []
    for key in ("api_token", "api_write_token"):
        if not db.get_setting(conn, key):
            db.set_setting(conn, key, secrets.token_urlsafe(32))
            made.append(key)
    return made


def import_samples(conn, path: Path) -> tuple:
    data = json.loads(path.read_text(encoding="utf-8"))
    owner = conn.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()["id"]
    added, skipped = [], []
    for r in data.get("roster", []):
        if not conn.execute("SELECT 1 FROM roster WHERE en_name=? AND cn_name=?",
                            (r.get("en_name", ""), r.get("cn_name", ""))).fetchone():
            conn.execute("INSERT INTO roster(cn_name,en_name,email,affiliation,role_note,notes,sort_order) "
                         "VALUES(?,?,?,?,?,?,?)",
                         (r.get("cn_name", ""), r.get("en_name", ""), r.get("email", ""),
                          r.get("affiliation", ""), r.get("role_note", ""), r.get("notes", ""),
                          int(r.get("sort_order", 100))))
    for p in data["papers"]:
        code = p["code"]
        if conn.execute("SELECT 1 FROM papers WHERE code=? COLLATE NOCASE", (code,)).fetchone():
            skipped.append(code)
            continue
        subs = p.get("submissions", [])
        # 论文状态 = 最新一轮的状态；没有投稿记录时用样例里写的（默认撰写中）
        status = subs[-1].get("status", "投稿中") if subs else p.get("status", "撰写中")
        ts = db.now()
        pid = conn.execute(
            "INSERT INTO papers(owner_id,title,title_cn,lead_author,authors,corresponding,status,notes,"
            "current_note,author_pos,is_corresponding,category,code,follow_mode,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (owner, p["title"], p.get("title_cn", ""), p.get("lead_author", ""),
             "\n".join(p.get("authors", [])), p.get("corresponding", ""), status, p.get("notes", ""),
             p.get("current_note", ""), p.get("author_pos", ""), 1 if p.get("is_corresponding") else 0,
             p.get("category", "main"), code, p.get("follow_mode", ""), ts, ts)).lastrowid
        for seq, s in enumerate(subs, 1):
            conn.execute(
                "INSERT INTO submissions(paper_id,seq,journal,site_url,submit_date,manuscript_id,status,"
                "result_date,notes,outcome,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, seq, s["journal"], s.get("site_url", ""), s.get("submit_date", ""),
                 s.get("manuscript_id", ""), s.get("status", "投稿中"), s.get("result_date", ""),
                 s.get("notes", ""), s.get("outcome", ""), ts, ts))
        added.append(code)
    conn.commit()
    return added, skipped


def main() -> None:
    ap = argparse.ArgumentParser(prog="seed.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api-tokens", action="store_true", help="生成只读 / 写 API token（已有则不动）")
    ap.add_argument("--samples", nargs="?", const=str(SAMPLES), metavar="JSON",
                    help=f"导入虚构样例（默认 {SAMPLES.relative_to(Path(__file__).resolve().parent)}）")
    a = ap.parse_args()

    db.init_db(create_admin=False)
    conn = db.connect()
    try:
        user = db.admin_username()
        if conn.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
            print("管理员已存在，跳过创建（改口令请登录网页「我的账号」）")
        else:
            db.ensure_admin(conn, user, ask_password())
            print(f"已创建管理员 {user}")
        if a.api_tokens:
            made = ensure_tokens(conn)
            print("已生成 " + "、".join(made) if made else "API token 已存在，未改动",
                  "（本机 paper 命令会自动从数据库读取；在网页「管理」页可查看和轮换）")
        if a.samples:
            added, skipped = import_samples(conn, Path(a.samples))
            print(f"样例导入：新增 {added or '无'}；编号已存在而跳过 {skipped or '无'}")
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as e:
        sys.exit(f"seed: {e}")
    finally:
        conn.close()
    print(f"数据库：{db.DB_PATH}")


if __name__ == "__main__":
    main()
