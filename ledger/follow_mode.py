"""论文跟进方式 papers.follow_mode：谁跟进、AI 怎么做，只认这一个字段。

lead_author 只是跟进人姓名；跟进计划的 active 由这里推导并同步写入。
鉴权、事务开关由调用方负责（本模块不 commit）。
"""
from __future__ import annotations

import sqlite3

# 内部值 -> 中文名；'' = 未登记
MODES = {"ai": "AI代查", "self": "本人自查", "student": "学生自管",
         "watch": "学生自管·AI盯截止", "partner": "合作方自管", "": "未登记"}
# 跟进计划 active 的推导；未登记（''）不在表里 = 沿用跟进计划存储值
ACTIVE = {"ai": True, "watch": True, "self": False, "student": False, "partner": False}
# CLI 用 none 表示「未登记」（argparse 不便传空串）
CLI_CHOICES = [k for k in MODES if k] + ["none"]
# 同步时自动填的归档原因前缀；改回 ai/watch 时只清掉这种自动值
AUTO_REASON = "跟进方式："


def label(value: str) -> str:
    return MODES.get(value or "", value or "")


def parse(value) -> str:
    """接受内部值、中文名或 none；其他值 422，不静默当成未登记。"""
    from fastapi import HTTPException
    if value == "none":
        return ""
    for key, name in MODES.items():
        if value in (key, name):
            return key
    raise HTTPException(422, f"follow_mode 只能是 {[k for k in MODES if k]}、'' 或 'none'"
                             f"（中文名 {list(MODES.values())}），收到 {value!r}")


def active_for(mode: str, stored: bool) -> bool:
    return ACTIVE.get(mode or "", stored)


def conflict_message(code: str, mode: str) -> str:
    return (f"{code} 的跟进方式是「{label(mode)}」，跟进计划 active 由它推导；"
            f"要改请用 paper edit {code} --follow-mode {{ai,self,student,watch,partner,none}}")


def sync(conn: sqlite3.Connection, pid: int, mode: str, actor: str) -> bool:
    """把 follow_mode 推导出的 active 写进跟进计划（新版本 + 修订记录）；已一致则不写。"""
    import followup  # followup 在顶层引用本模块，这里延迟导入避免循环
    if mode not in ACTIVE:
        return False
    old = followup.state(conn, pid)
    want = ACTIVE[mode]
    if old["active"] == want:
        return False
    data = dict(old)
    data["active"] = want
    if not want and not (data["archive_reason"] or data["completion_evidence"]):
        data["archive_reason"] = AUTO_REASON + label(mode)
    if want and data["archive_reason"].startswith(AUTO_REASON):
        data["archive_reason"] = ""
    followup.persist(conn, pid, data, old["version"] + 1, actor, "follow_mode." + mode)
    return True
