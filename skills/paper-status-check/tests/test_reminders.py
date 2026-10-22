"""reminders.py：假的台账 JSON → 收件人分组、去重、无法提醒清单、--send 走假 SMTP、记跟进事件的调用参数；
以及 weekly_report.py --remind 的串联。不联网、不调真实台账。

运行（在本技能目录下）：python3 -m pytest -q tests
"""
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

TMP = tempfile.TemporaryDirectory()
os.environ.update({"PAPER_STATUS_CONFIG": str(Path(TMP.name) / "absent.json"), "PAPER_STATUS_WORK": TMP.name,
                   "PAPER_CLI": "paper-test-cli"})
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
with contextlib.redirect_stderr(io.StringIO()):
    import settings  # noqa: E402
import reminders  # noqa: E402

TODAY = date(2026, 10, 22)
NOW = datetime(2026, 10, 22, 10, 0, tzinfo=timezone(timedelta(hours=8)))


def P(code, lead, mode, status="投稿中", **kw):
    return {"code": code, "title": f"Title {code}", "status": status, "lead_author": lead, "follow_mode": mode,
            "current_submission": {"journal": "Example Journal A", "submit_date": "2026-06-01"},
            "submissions": kw.pop("submissions", []), **kw}


def F(code, version=4, stage="under_review", **kw):
    return {"code": code, "version": version, "stage": stage, "stage_label": kw.pop("stage_label", stage), **kw}


OLD_UNCLOSED = [{"seq": 2, "id": 21, "journal": "Example Journal A", "is_current": True, "outcome": ""},
                {"seq": 1, "id": 20, "journal": "Old Journal B", "manuscript_id": "OLD-001",
                 "submit_date": "2026-01-10", "is_current": False, "outcome": "未关闭"}]
PAPERS = [
    P("P01", "李四", "student", revision_days_remaining=10, revision_due_date="2026-11-01"),
    P("P02", "赵六", "watch", revision_days_remaining=3, revision_due_date="2026-10-25"),
    P("P03", "张三", "ai", days_without_progress=75, last_progress_date="2026-08-08"),
    P("P04", "李四", "student"),
    P("P05", "张三", "self", revision_days_remaining=5, revision_due_date="2026-10-27"),
    P("P06", "王五（合作方）", "partner", submissions=OLD_UNCLOSED),
    P("P07", "李四", "student", status="已录用", revision_days_remaining=2, revision_due_date="2026-10-24"),
    P("P08", "王五", "student", revision_days_remaining=5, revision_due_date="2026-10-27"),
    P("P09", "张三", "", days_without_progress=10),
    P("P10", "李四", "student", submissions=OLD_UNCLOSED),
    P("P11", "李四", "student", days_without_progress=30, revision_days_remaining=40, revision_due_date="2026-12-01"),
]
FOLLOWUPS = [
    F("P01", stage="revision_required"), F("P02", stage="revision_required"), F("P03", version=9),
    F("P04", stage="awaiting_author", stage_label="等待作者", waiting_for="等王五确认作者身份",
      next_action="提醒王五点确认链接", waiting_since="2026-10-15T09:00:00+08:00"),
    F("P05", stage="revision_required"), F("P06"), F("P07", stage="accepted"), F("P08", stage="revision_required"),
    F("P09", waiting_for="等李四回复修改稿", action_owner=""), F("P10", version=2), F("P11", waiting_for="外审中"),
]


def config(**reminders_over):
    return settings._merge(settings.DEFAULTS, {
        "self_names": ["张三"],
        "report": {"from": "alice@example.com", "sender_label": "投稿服务器"},
        "people": {"张三": {"email": "alice@example.com", "role": "owner"},
                   "李四": {"email": "lisi@example.com", "role": "student", "cc_owner": True},
                   "王五": {"email": "wangwu@example.org", "role": "external"}},
        "reminders": {"state_file": str(Path(TMP.name) / "state.json"), **reminders_over}})


class FakeSMTP:
    sent, fail_to = [], set()

    def __init__(self, host, port, context=None, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pw):
        pass

    def send_message(self, msg):
        if msg["To"] in FakeSMTP.fail_to:
            raise reminders.mailboxes.smtplib.SMTPRecipientsRefused({msg["To"]: (550, b"no")})
        FakeSMTP.sent.append(msg)


class Base(unittest.TestCase):
    def setUp(self):
        self.state = Path(TMP.name) / "state.json"
        self.state.unlink(missing_ok=True)
        self.mb = Path(TMP.name) / "mailboxes.json"
        self.mb.write_text(json.dumps({"alice@example.com": {"smtp": "smtp.example.com", "password_env": "T_PW"}}),
                           encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"PAPER_MAILBOXES": str(self.mb), "T_PW": "pw"})
        self.env.start()
        FakeSMTP.sent.clear()
        FakeSMTP.fail_to = set()
        self.calls = []

    def tearDown(self):
        self.env.stop()

    def fake_run(self, version_step=1, fail=False):
        def run(cmd, input=None, capture_output=None, text=None, **kw):
            body = json.loads(input)
            v = int(cmd[cmd.index("--expected-version") + 1])
            self.calls.append((cmd, body))
            if fail:
                return subprocess.CompletedProcess(cmd, 1, "", "409 跟进记录已变更")
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"followup": {"version": v + version_step}}), "")
        return run

    def plan(self, cfg=None, state=None):
        return reminders.build(PAPERS, FOLLOWUPS, cfg or config(), state or {"sent": {}}, TODAY)

    def deliver(self, plan, send, cfg=None, **run_kw):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(reminders.mailboxes.smtplib, "SMTP_SSL", FakeSMTP), \
                mock.patch.object(reminders.subprocess, "run", self.fake_run(**run_kw)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            failed = reminders.deliver(plan, cfg or config(), FOLLOWUPS, send=send, now=NOW)
        return failed, out.getvalue(), err.getvalue()


class PlanTest(Base):
    def test_grouping_per_person_with_cc(self):
        plan = self.plan()
        by = {m["to"]: m for m in plan["mails"]}
        self.assertEqual(set(by), {"lisi@example.com", "alice@example.com"})
        lisi, alice = by["lisi@example.com"], by["alice@example.com"]
        self.assertEqual([(i["code"], i["kind"]) for i in lisi["items"]],
                         [("P01", "revision_due"), ("P04", "blocked"), ("P10", "unclosed")])
        self.assertEqual(lisi["cc"], ["alice@example.com"])
        self.assertEqual([(i["code"], i["kind"]) for i in alice["items"]],
                         [("P03", "stalled"), ("P09", "blocked")])     # P10 已在李四那封里抄送本人
        self.assertEqual(alice["cc"], [])
        self.assertTrue(lisi["body"].startswith("李四您好："))
        self.assertIn("等待：等王五确认作者身份", lisi["body"])
        self.assertIn("下一步：提醒王五点确认链接", lisi["body"])
        self.assertIn("不会给期刊发信", alice["body"])
        self.assertEqual(lisi["subject"], "论文跟进提醒（2026-10-22）：3 项")
        codes = {i["code"] for m in plan["mails"] for i in m["items"]}
        self.assertTrue({"P05", "P06", "P07", "P11"}.isdisjoint(codes))     # self、合作方、已录用、未到阈值都不提醒

    def test_unreachable_never_guesses_email(self):
        plan = self.plan()
        self.assertEqual({(u["code"], u["person"]) for u in plan["unreachable"]}, {("P02", "赵六"), ("P08", "王五")})
        lines = reminders.unreachable_lines(plan)
        self.assertIn("无法提醒：P02 返修截止（赵六 没有在 people 里登记邮箱）", lines)
        self.assertTrue(any("P08" in l and "include_external" in l for l in lines))
        plan = self.plan(config(include_external=True))
        self.assertIn("wangwu@example.org", {m["to"] for m in plan["mails"]})
        self.assertEqual({u["code"] for u in plan["unreachable"]}, {"P02"})

    def test_modes_and_thresholds_configurable(self):
        plan = self.plan(config(modes=["ai"], due_days=3, stalled_days=90))
        items = {(i["code"], i["kind"]) for m in plan["mails"] for i in m["items"]}
        self.assertEqual(items, {("P09", "blocked"), ("P10", "unclosed")})  # 未关闭总要告诉本人；合作方论文除外

    def test_dedupe_within_min_interval(self):
        recent = {"sent": {"P01|revision_due|2026-11-01": (TODAY - timedelta(days=3)).isoformat()}}
        plan = self.plan(state=recent)
        self.assertEqual([(s["code"], s["last_sent"]) for s in plan["skipped"]], [("P01", "2026-10-19")])
        self.assertNotIn("P01", {i["code"] for m in plan["mails"] for i in m["items"]})
        old = {"sent": {"P01|revision_due|2026-11-01": (TODAY - timedelta(days=8)).isoformat()}}
        self.assertEqual(self.plan(state=old)["skipped"], [])


class DeliverTest(Base):
    def test_preview_only_by_default(self):
        failed, out, _ = self.deliver(self.plan(), send=False)
        self.assertEqual(failed, 0)
        self.assertIn("预览（未发送）", out)
        self.assertIn("Cc: alice@example.com", out)
        self.assertIn("无法提醒：P02", out)
        self.assertEqual((FakeSMTP.sent, self.calls), ([], []))
        self.assertFalse(self.state.exists())

    def test_send_records_state_and_ledger_events(self):
        failed, out, err = self.deliver(self.plan(), send=True)
        self.assertEqual(failed, 0, err)
        self.assertEqual({(m["To"], m["Cc"]) for m in FakeSMTP.sent},
                         {("lisi@example.com", "alice@example.com"), ("alice@example.com", None)})
        sent = json.loads(self.state.read_text(encoding="utf-8"))["sent"]
        self.assertEqual(sent["P01|revision_due|2026-11-01"], "2026-10-22")
        self.assertEqual(sent["P10|unclosed|seq1"], "2026-10-22")
        self.assertEqual(sent["P04|blocked|2026-10-15"], "2026-10-22")
        cmd, body = self.calls[0]
        self.assertEqual(cmd[:7], ["paper-test-cli", "--json", "followup", "event", "P01", "--from-json", "-"])
        self.assertEqual(cmd[7:], ["--expected-version", "4"])
        self.assertEqual(body["kind"], "outgoing")
        self.assertEqual(body["text"], "已提醒 李四：返修截止 2026-11-01")
        self.assertEqual(body["occurred_at"], "2026-10-22T10:00:00+08:00")
        self.assertRegex(body["idempotency_key"], r"^remind:2026-10-22:P01:[0-9a-f]{12}$")
        p10 = [(c[c.index("--expected-version") + 1], b["text"]) for c, b in self.calls if c[4] == "P10"]
        self.assertEqual(p10, [("2", "已提醒 李四：旧轮未关闭 seq1")])   # 本人已在李四那封里抄送
        self.assertTrue(all(re.fullmatch(r"[A-Za-z0-9._:-]{1,180}", b["idempotency_key"]) for _, b in self.calls))
        again = self.plan(state=json.loads(self.state.read_text(encoding="utf-8")))
        self.assertEqual(again["mails"], [])                          # 7 天内再跑不重复发

    def test_versions_chain_when_two_mails_touch_one_paper(self):
        cfg = config()
        cfg["people"]["李四"]["cc_owner"] = False
        failed, _, err = self.deliver(self.plan(cfg), send=True, cfg=cfg)
        self.assertEqual(failed, 0, err)
        p10 = [(c[c.index("--expected-version") + 1], b["text"]) for c, b in self.calls if c[4] == "P10"]
        self.assertEqual(p10, [("2", "已提醒 李四：旧轮未关闭 seq1"), ("3", "已提醒 张三：旧轮未关闭 seq1")])  # 版本号接上一条

    def test_one_failed_mail_does_not_block_others(self):
        FakeSMTP.fail_to = {"lisi@example.com"}
        failed, _, err = self.deliver(self.plan(), send=True)
        self.assertEqual(failed, 1)
        self.assertIn("李四", err)
        sent = json.loads(self.state.read_text(encoding="utf-8"))["sent"]
        self.assertIn("P03|stalled|2026-08-08", sent)
        self.assertNotIn("P01|revision_due|2026-11-01", sent)
        self.assertNotIn("P10|unclosed|seq1", sent)                   # 两人都要收到的事，一封失败就不算发过
        self.assertEqual({c[4] for c, _ in self.calls}, {"P03", "P09"})

    def test_ledger_failure_only_warns(self):
        failed, out, err = self.deliver(self.plan(), send=True, fail=True)
        self.assertEqual(failed, 0)
        self.assertIn("记跟进事件失败", err)
        self.assertEqual(len(FakeSMTP.sent), 2)
        self.assertTrue(self.state.exists())

    def test_send_without_sender_fails_loud(self):
        cfg = config()
        cfg["report"]["from"] = ""
        failed, _, err = self.deliver(self.plan(cfg), send=True, cfg=cfg)
        self.assertEqual(failed, 2)
        self.assertIn("reminders.from", err)
        self.assertEqual(FakeSMTP.sent, [])


class WeeklyRemindTest(Base):
    def test_weekly_report_remind_previews_and_lists_unreachable(self):
        with contextlib.redirect_stderr(io.StringIO()):
            import weekly_report as wr

        def fake_paper(*args):
            return {"papers": PAPERS} if args == ("list",) else {"papers": FOLLOWUPS}

        out = io.StringIO()
        with mock.patch.object(wr, "paper", fake_paper), mock.patch.object(wr.reminders.settings, "paper", fake_paper), \
                mock.patch.object(wr, "CFG", config()), mock.patch.object(wr, "OUT", Path(TMP.name) / "weekly"), \
                mock.patch.object(wr.scan, "scan_all", lambda codes, since: ({}, {}, {})), \
                mock.patch.object(wr.track, "scan", lambda since, data: ([], {})), \
                mock.patch.object(wr.mailboxes.smtplib, "SMTP_SSL", FakeSMTP), \
                mock.patch.object(sys, "argv", ["weekly_report.py", "--no-browser", "--no-checkin", "--remind"]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            wr.main()
        text = out.getvalue()
        five = text[text.index("五、本次没查到的"):text.index("── 催人跟进 ──")]
        self.assertIn("无法提醒：P02 返修截止", five)
        self.assertIn("To: lisi@example.com", text[text.index("── 催人跟进 ──"):])
        self.assertIn("只预览未发送", text)
        self.assertEqual(FakeSMTP.sent, [])
        archived = json.loads(next((Path(TMP.name) / "weekly").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual({u["code"] for u in archived["reminders"]["unreachable"]}, {"P02", "P08"})


if __name__ == "__main__":
    unittest.main()
