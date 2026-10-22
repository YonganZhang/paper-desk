#!/usr/bin/env python3
"""催人跟进：按台账给组内跟进人发汇总提醒（返修将到期、跟进计划卡住、在审太久无进展、旧轮未关闭）。

只提醒人，绝不给期刊或编辑部发信。默认只打印预览；--send 才经 paper-mailbox 的 send 发出，
发出后按（编号, 提醒类型, 截止日）记上次发送日去重，并给台账记一条 outgoing 跟进事件（失败只告警）。
数据：paper --json list、paper --json followup list。配置：status-check.json 的 people 与 reminders 段（references/reminders.md）。
用法：reminders.py [--send] [--json]；weekly_report.py --remind 在周报之后调用同一套逻辑。
退出码：0 成功（含没有要发的）；1 有提醒发送失败或配置缺失。
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # -I 运行时脚本目录不在 sys.path
import settings  # noqa: E402
from settings import mailboxes  # noqa: E402  paper-mailbox/scripts/mailboxes.py

KIND_LABEL = {"revision_due": "返修截止", "blocked": "跟进卡点", "stalled": "久无进展", "unclosed": "旧轮未关闭"}
UNCLOSED = "未关闭"
SUFFIX = re.compile(r"\s*[（(][^）)]*[）)]\s*$")          # 「某人（挂名）」这类后缀，查 people 时去掉再试


def label(p):
    t, cn = (p.get("title") or "").strip(), (p.get("title_cn") or "").strip()
    return f"{p['code']}《{t or cn}》"


def mode_of(p, fu, self_names):
    """跟进方式只认台账 follow_mode；没登记时与 access_audit 同口径：负责人是本人 → ai（跟进计划写了「本人自查」→ self），其余 → student。"""
    m = p.get("follow_mode") or ""
    if m:
        return m
    if (p.get("lead_author") or "") in self_names:
        return "self" if "本人自查" in (fu.get("action_owner") or "") else "ai"
    return "student"


def owner_name(cfg):
    return cfg["reminders"].get("owner") or (cfg["self_names"][0] if cfg["self_names"] else "")


def find_person(name, cfg):
    """返回 (姓名, 登记) 或 (None, 无法提醒的原因)。不猜邮箱：people 里没有就不提醒。"""
    people, R = cfg["people"], cfg["reminders"]
    if not name:
        return None, "负责人未登记"
    key = name if name in people else SUFFIX.sub("", name)
    entry = people.get(key)
    if not isinstance(entry, dict) or not entry.get("email"):
        return None, f"{name} 没有在 people 里登记邮箱"
    if entry.get("role") == "external" and not R.get("include_external"):
        return None, f"{name} 是外部人员（role=external），未开 reminders.include_external"
    return key, entry


def items_for(p, fu, cfg):
    """一篇论文要提醒的事：[{code, kind, due, text, to: [姓名…]}]。to 里是台账上的姓名，find_person 再解析。"""
    R = cfg["reminders"]
    if p.get("status") != "投稿中":
        return []
    mode = mode_of(p, fu, set(cfg["self_names"]))
    lead, owner = p.get("lead_author") or fu.get("lead_author") or "", owner_name(cfg)
    remind_lead = mode in R["modes"]
    out = []

    def add(kind, due, text, to):
        to = [x for i, x in enumerate(to) if x is not None and x not in to[:i]]
        if to:
            out.append({"code": p["code"], "kind": kind, "due": str(due or ""), "text": text, "to": to, "mode": mode})

    left = p.get("revision_days_remaining")
    if left is None and fu.get("due_in_days") is not None and fu.get("due_source") == "ledger":
        left = fu["due_in_days"]
    due = p.get("revision_due_date") or (fu.get("due_at") or "")[:10]
    if remind_lead and left is not None and left <= R["due_days"]:
        when = f"还剩 {left} 天" if left >= 0 else f"已逾期 {-left} 天"
        add("revision_due", due, f"{label(p)}：返修截止 {due}，{when}。请确认修改进度和回复信。", [lead])

    waiting = (fu.get("waiting_for") or "").strip()
    named = any(n and n in waiting for n in cfg["people"])
    if remind_lead and (fu.get("stage") in R["blocked_stages"] or (waiting and (named or (R["waiting_pattern"] and re.search(R["waiting_pattern"], waiting))))):
        text = f"{label(p)}：跟进计划停在「{fu.get('stage_label') or fu.get('stage') or '—'}」。"
        text += f"\n   等待：{waiting}" if waiting else ""
        text += f"\n   下一步：{fu['next_action']}" if fu.get("next_action") else ""
        add("blocked", (fu.get("waiting_since") or "")[:10], text, [lead])

    idle = p.get("days_without_progress")
    if idle is None:
        idle = fu.get("days_without_progress")
    if remind_lead and fu.get("stage") in ("submitted", "under_review") and idle is not None and idle >= R["stalled_days"]:
        cur = p.get("current_submission") or {}
        since = p.get("last_progress_date") or cur.get("submit_date") or ""
        add("stalled", since, f"{label(p)}：{cur.get('journal') or '当前期刊'} 已 {idle} 天没有进展（自 {since or '投稿'}起）。"
            "可以考虑问一下编辑部；是否联系、怎么写由您决定，本提醒不会给期刊发信。", [lead])

    for s in p.get("submissions") if mode != "partner" else []:   # 合作方论文由合作方自管，旧轮也不提醒
        if not s.get("is_current") and s.get("outcome") == UNCLOSED:
            add("unclosed", f"seq{s.get('seq')}",
                f"{label(p)}：旧轮 {s.get('journal') or '—'}（稿号 {s.get('manuscript_id') or '暂无'}，{s.get('submit_date') or '日期未录'} 投）"
                "在台账里是「未关闭」，原刊流程可能还在。请确认已撤回或已收到结论，防止一稿多投。",
                [lead if remind_lead else None, owner])         # 防一稿多投：本人总要知道，负责人按跟进方式
    return out


def state_path(cfg):
    return Path(cfg["reminders"].get("state_file") or settings.WORK / "reminders-state.json").expanduser()


def load_state(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"sent": {}}


def state_key(it):
    return f"{it['code']}|{it['kind']}|{it['due']}"


def build(papers, followups, cfg, state, today):
    """返回 {mails, unreachable, skipped}。mails：每人一封 {name, to, cc, subject, body, items}。"""
    R = cfg["reminders"]
    fu_by = {f["code"]: f for f in followups}
    mails, unreachable, skipped = {}, [], []
    owner = owner_name(cfg)
    owner_hit = find_person(owner, cfg) if owner else (None, "没有配置 reminders.owner 或 self_names")
    for p in papers:
        for it in items_for(p, fu_by.get(p["code"], {}), cfg):
            last = state.get("sent", {}).get(state_key(it))
            if last and (today - date.fromisoformat(last)).days < R["min_interval_days"]:
                skipped.append({**it, "last_sent": last})
                continue
            for who in it["to"]:
                name, entry = find_person(who, cfg)
                if name is None:
                    unreachable.append({"code": it["code"], "kind": it["kind"], "person": who, "reason": entry})
                    continue
                m = mails.setdefault(entry["email"].lower(), {"name": name, "to": entry["email"], "cc": [], "items": []})
                if it not in m["items"]:
                    m["items"].append(it)
                if entry.get("cc_owner") and owner_hit[0] and owner_hit[0] != name and owner_hit[1]["email"] not in m["cc"]:
                    m["cc"].append(owner_hit[1]["email"])
    if owner_hit[0]:                                          # 本人已在别人的信里抄送过的事，自己那封不再重复
        own_key = owner_hit[1]["email"].lower()
        own = mails.get(own_key)
        if own:
            cc_seen = [it for k, m in mails.items() if k != own_key and owner_hit[1]["email"] in m["cc"] for it in m["items"]]
            own["items"] = [it for it in own["items"] if it not in cc_seen]
            if not own["items"]:
                del mails[own_key]
    sender = R.get("sender_label") or cfg["report"]["sender_label"]
    for m in mails.values():
        lines = [R["greeting"].format(name=m["name"]), "", f"以下 {len(m['items'])} 项需要您跟进："]
        lines += [f"{i}. [{KIND_LABEL[it['kind']]}] {it['text']}" for i, it in enumerate(m["items"], 1)]
        lines += ["", R["signature"].format(sender_label=sender, date=today.isoformat())]
        m["subject"] = R["subject"].format(name=m["name"], date=today.isoformat(), count=len(m["items"]))
        m["body"] = "\n".join(lines)
    return {"mails": list(mails.values()), "unreachable": unreachable, "skipped": skipped}


def unreachable_lines(plan):
    """给周报第五节用。"""
    return [f"无法提醒：{u['code']} {KIND_LABEL[u['kind']]}（{u['reason']}）" for u in plan["unreachable"]]


def ledger_event(code, version, body):
    """paper followup event；返回新版本号，失败返回 None 并告警（不中断其他提醒）。"""
    r = subprocess.run([*settings.PAPER_CMD, "--json", "followup", "event", code, "--from-json", "-",
                        "--expected-version", str(version)], input=json.dumps(body, ensure_ascii=False),
                       capture_output=True, text=True)
    if r.returncode:
        print(f"警告：{code} 记跟进事件失败（提醒已发出）：{(r.stderr or r.stdout).strip()[:200]}", file=sys.stderr)
        return None
    try:
        return json.loads(r.stdout)["followup"]["version"]
    except (ValueError, KeyError, TypeError):
        return None


def deliver(plan, cfg, followups, send=False, now=None, accounts=None):
    """预览或发送。send=True 时：逐封发，成功的记去重状态和台账事件。返回发送失败的封数。"""
    now = now or datetime.now().astimezone(settings.tz())
    today = now.date()
    R = cfg["reminders"]
    sender = R.get("from") or cfg["report"]["from"]
    for m in plan["mails"]:
        print(mailboxes.preview(sender or "（未配置 reminders.from / report.from）", m["to"], m["subject"], m["body"], m["cc"]))
    for s in plan["skipped"]:
        print(f"跳过（{s['last_sent']} 已提醒，{R['min_interval_days']} 天内不重复）：{s['code']} {KIND_LABEL[s['kind']]}")
    for line in unreachable_lines(plan):
        print(line)
    if not send:
        print(f"提醒共 {len(plan['mails'])} 封，只预览未发送；加 --send 才发。")
        return 0
    if plan["mails"] and not sender:
        print("错误：发提醒需要配置 reminders.from 或 report.from", file=sys.stderr)
        return len(plan["mails"])
    versions = {f["code"]: f.get("version") for f in followups}
    ok_keys, bad_keys, failed = set(), set(), 0
    for m in plan["mails"]:
        keys = {state_key(it) for it in m["items"]}
        try:
            mailboxes.send(sender, [m["to"]], m["subject"], m["body"], accounts, cc=m["cc"])
        except (mailboxes.MailboxError, OSError) as e:      # 含 SMTP 错误；一封失败不挡其他人
            print(f"错误：给 {m['name']} 的提醒没发出：{type(e).__name__}: {e}", file=sys.stderr)
            bad_keys |= keys
            failed += 1
            continue
        print(f"已提醒 → {m['name']} {m['to']}" + (f"（抄送 {', '.join(m['cc'])}）" if m["cc"] else ""))
        ok_keys |= keys
        by_code = {}
        for it in m["items"]:
            by_code.setdefault(it["code"], []).append(it)
        for code, its in by_code.items():
            if versions.get(code) is None:
                print(f"警告：{code} 没有跟进计划版本号，未记跟进事件", file=sys.stderr)
                continue
            kinds = ",".join(sorted({it["kind"] for it in its}))
            digest = hashlib.sha1(f"{code}|{m['name']}|{kinds}|{today}".encode()).hexdigest()[:12]
            body = {"kind": "outgoing", "occurred_at": now.isoformat(timespec="seconds"),
                    "text": f"已提醒 {m['name']}：" + "；".join(KIND_LABEL[it["kind"]] + (f" {it['due']}" if it["due"] else "") for it in its),
                    "evidence_ref": f"reminders {today}", "idempotency_key": f"remind:{today}:{re.sub(r'[^A-Za-z0-9._-]', '_', code)}:{digest}"}
            v = ledger_event(code, versions[code], body)
            if v is not None:
                versions[code] = v
    path = state_path(cfg)
    state = load_state(path)
    for k in ok_keys - bad_keys:                              # 同一事要发给两个人时，两封都成功才算发过
        state.setdefault("sent", {})[k] = today.isoformat()
    if ok_keys - bad_keys:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return failed


def run(cfg, send=False, papers=None, accounts=None):
    """从台账取数据、生成并投递提醒。返回 (plan, 失败封数)。papers 可传入已取到的 paper list，省一次调用。"""
    papers = papers if papers is not None else settings.paper("list")["papers"]
    followups = settings.paper("followup", "list")["papers"]
    now = datetime.now().astimezone(settings.tz())
    plan = build(papers, followups, cfg, load_state(state_path(cfg)), now.date())
    return plan, deliver(plan, cfg, followups, send, now, accounts)


def main():
    ap = argparse.ArgumentParser(description="催人跟进：给组内跟进人发汇总提醒（默认只预览，不给期刊发信）")
    ap.add_argument("--send", action="store_true", help="真的发出，并记去重状态和台账跟进事件")
    ap.add_argument("--json", action="store_true", help="只输出提醒计划 JSON，不发送")
    a = ap.parse_args()
    cfg = settings.CFG
    if a.json:
        papers, followups = settings.paper("list")["papers"], settings.paper("followup", "list")["papers"]
        today = datetime.now().astimezone(settings.tz()).date()
        print(json.dumps(build(papers, followups, cfg, load_state(state_path(cfg)), today), ensure_ascii=False, indent=1))
        return 0
    accounts = None
    if a.send:
        try:
            accounts = mailboxes.load_accounts()
        except mailboxes.MailboxError as e:
            print(f"错误：{e}", file=sys.stderr)
            return 1
    return 1 if run(cfg, a.send, accounts=accounts)[1] else 0


if __name__ == "__main__":
    sys.exit(main())
