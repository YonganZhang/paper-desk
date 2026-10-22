"""投稿轮次与论文分类的规则：旧轮真实结局、补录历史轮、合作方分类。

只放规则与数据库操作，路由仍在 app.py；鉴权、事务开关由调用方负责。
"""
from __future__ import annotations

import sqlite3

# 旧轮真实结局。'' = 未记录（页面照旧显示「已转投」）。
OUTCOMES = ["", "被拒", "撤回", "编辑建议转投", "编辑移除", "未关闭"]
UNCLOSED = "未关闭"

# papers.category 内部值 -> 对外中文名
CATEGORY_NAMES = {"main": "主序列", "extra": "其他论文（不计入主序列）", "partner": "合作方论文"}


def category_name(value: str) -> str:
    return CATEGORY_NAMES.get(value, CATEGORY_NAMES["main"])


def parse_category(value) -> str:
    """接受内部值或中文名；其他值报 422，不再静默当成主序列。"""
    from fastapi import HTTPException
    for key, name in CATEGORY_NAMES.items():
        if value in (key, name):
            return key
    raise HTTPException(422, f"category 只能是 {list(CATEGORY_NAMES)} 或 {list(CATEGORY_NAMES.values())}，收到 {value!r}")


def check_outcome(value) -> str:
    from fastapi import HTTPException
    if not isinstance(value, str) or value not in OUTCOMES:
        raise HTTPException(422, f"outcome 只能是 {OUTCOMES} 之一，收到 {value!r}")
    return value


def display_status(status: str, outcome: str, is_current: bool) -> str:
    """最新轮显示真实 status；旧轮按 outcome 显示，未记录时为「已转投」。"""
    if is_current:
        return status
    if not outcome:
        return "已转投"
    if outcome == UNCLOSED:
        return "未关闭（原刊流程仍在）"
    return f"已转投（{outcome}）"


def history_seq(conn: sqlite3.Connection, pid: int, submit_date: str) -> int:
    """为补录的历史轮腾出位置，返回新轮应占用的 seq。

    找第一个 submit_date 非空且晚于新日期的轮次 k；原 seq>=k 的各轮按降序逐条 +1，
    即使以后给 (paper_id, seq) 加唯一约束也不会中途冲突。找不到 k 说明新轮会成为
    最新一轮，那是转投而不是补录，报 422。调用方须已开启写事务。
    """
    from fastapi import HTTPException
    row = conn.execute(
        "SELECT seq FROM submissions WHERE paper_id=? AND submit_date!='' AND submit_date>? "
        "ORDER BY seq LIMIT 1", (pid, submit_date)).fetchone()
    if not row:
        raise HTTPException(422, "补录的历史轮不能晚于当前轮，转投请不加 --history")
    k = row["seq"]
    for r in conn.execute("SELECT id FROM submissions WHERE paper_id=? AND seq>=? ORDER BY seq DESC",
                          (pid, k)).fetchall():
        conn.execute("UPDATE submissions SET seq=seq+1 WHERE id=?", (r["id"],))
    return k


def unclosed_old_rounds(papers: list) -> list:
    """从 API 论文 JSON 里挑出「投稿中」且有旧轮 outcome=未关闭 的轮次（防一稿多投）。"""
    out = []
    for p in papers:
        if p.get("status") != "投稿中":
            continue
        for s in p.get("submissions") or []:
            if not s.get("is_current") and s.get("outcome") == UNCLOSED:
                out.append({"code": p["code"], "seq": s["seq"], "submission_id": s["id"],
                            "journal": s["journal"], "manuscript_id": s["manuscript_id"],
                            "submit_date": s["submit_date"]})
    return out
