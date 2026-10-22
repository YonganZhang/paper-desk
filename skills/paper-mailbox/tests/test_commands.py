"""mailboxes.py 新子命令：假 IMAP 上的 inbox / search / links，send 预览与 --confirm，
临时 JSON 上的 usage / audit / link / unlink。不联网。

运行（在本技能目录下）：python3 -m pytest -q tests
"""
import contextlib
import imaplib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from email import message_from_bytes
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mailboxes  # noqa: E402


def _msg(sender, subject, date, plain=None, page=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Date"] = sender, "alice@example.com", subject, date
    if plain is not None:
        m.set_content(plain)
    if page is not None:
        if plain is None:
            m.set_content(page, subtype="html")
        else:
            m.add_alternative(page, subtype="html")
    return m.as_bytes()


MESSAGES = {
    "1": _msg("Journal <journal@example.com>", "Submission received", "Thu, 01 Oct 2026 09:00:00 +0800", plain="Thanks."),
    "2": _msg("Editor <editor@example.org>", "请确认作者身份 Please verify", "Sat, 10 Oct 2026 09:00:00 +0800",
              plain="Confirm: https://em.example.com/confirm?id=1&t=2.\nHelp: https://example.com/help",
              page='<p><a href="https://em.example.com/confirm?id=1&amp;t=2">Yes, I am <b>affiliated</b></a></p>'
                   '<p>See https://example.com/help</p>'),
    "3": _msg("Editor <editor@example.org>", "稿件状态更新", "Thu, 15 Oct 2026 09:00:00 +0800", plain="外审中。"),
}


class FakeIMAP:
    commands, selected = [], []
    reject_charset = False

    def __init__(self, host, port, timeout=None):
        self.literal = None

    def login(self, user, pw):
        pass

    def select(self, mailbox="INBOX", readonly=False):
        FakeIMAP.selected.append((mailbox, readonly))
        return "OK", [b"3"]

    def logout(self):
        pass

    @staticmethod
    def _match(raw, key, val):
        m = message_from_bytes(raw)
        if key == "SINCE":
            return parsedate_to_datetime(m["Date"]).date() >= __import__("datetime").datetime.strptime(val, "%d-%b-%Y").date()
        text = {"SUBJECT": mailboxes.dh(m["Subject"]), "FROM": mailboxes.dh(m["From"]),
                "BODY": mailboxes.extract_body(m)}[key]
        return val.lower() in text.lower()

    def uid(self, cmd, *args):
        lit, self.literal = self.literal, None
        FakeIMAP.commands.append((cmd.lower(), args, lit))
        if cmd.lower() == "search":
            if "CHARSET" in args and FakeIMAP.reject_charset:
                return "NO", [b"[BADCHARSET] (US-ASCII)"]
            crit = [x for x in args if x not in (None, "CHARSET", "UTF-8")]
            if crit == ["ALL"]:
                return "OK", [" ".join(MESSAGES).encode()]
            pairs, i = [], 0
            while i < len(crit):
                if i + 1 < len(crit):
                    pairs.append((crit[i], crit[i + 1].strip('"')))
                    i += 2
                else:                       # 最后一个关键词的值在字面量里
                    pairs.append((crit[i], lit.decode("utf-8")))
                    i += 1
            hits = [u for u, raw in MESSAGES.items() if all(self._match(raw, k, v) for k, v in pairs)]
            return "OK", [" ".join(hits).encode()]
        uid = args[0].decode() if isinstance(args[0], bytes) else args[0]
        return ("OK", [(b"x", MESSAGES[uid])]) if uid in MESSAGES else ("OK", [None])


class FakeSMTP:
    sent = []

    def __init__(self, host, port, context=None, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pw):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mailboxes.main(argv)
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    BOXES = {
        "_comment": "注释键保留",
        "alice@example.com": {"imap": "imap.example.com", "smtp": "smtp.example.com", "password_env": "T_MAIL_PW",
                              "readable": True, "owner": "张三", "purpose": "本人专用",
                              "author_links": [{"person": "张三", "role": "投稿人/通讯", "papers": ["P01", "P03"]}]},
        "spare@example.org": {"imap": "imap.example.org", "readable": True, "owner": "课题组", "purpose": "临时合作者备用",
                              "author_links": [{"person": "李四", "role": "作者", "papers": ["P03"]}]},
        "fixed@example.com": {"imap": "imap.example.com", "readable": False, "owner": "王五", "purpose": "固定合作者专用",
                              "author_links": [{"person": "王五", "role": "通讯", "papers": ["P05"]},
                                               {"person": "赵六", "role": "作者", "papers": ["P05", "P06"]}],
                              "exceptions": [{"person": "赵六", "papers": ["P06"], "scope": "仅 P06"}]},
        "conf@example.edu": {"imap": "imap.example.edu", "readable": True, "owner": "张三", "purpose": "会议专用",
                             "author_links": [{"person": "张三", "role": "作者", "papers": ["P07"]}]},
    }
    SUBMIT = [
        {"system": "Editorial Manager", "login_url": "https://www.editorialmanager.com/abcd/", "person": "张三",
         "email": "alice@example.com", "paper": "P01 P03"},
        {"system": "Editorial Manager", "login_url": "https://www.editorialmanager.com/abcd/", "person": "李四",
         "email": "ALICE@example.com", "paper": "P09"},
        {"system": "Editorial Manager", "login_url": "https://www.editorialmanager.com/wxyz/", "person": "李四",
         "email": "spare@example.org", "paper": "P03"},
        {"system": "Elsevier new submission", "login_url": "https://submit.elsevier.com/", "login": "elsevier-sso",
         "person": "王五", "email": "fixed@example.com", "paper": "P05"},
        {"system": "Editorial Manager", "login_url": "https://www.editorialmanager.com/efgh/", "login": "elsevier-sso",
         "person": "赵六", "email": "fixed@example.com", "paper": "P06"},
        {"system": "Springer Nature", "login_url": "https://submission.springernature.com/", "person": "赵六",
         "email": "other@example.org", "paper": "P08"},
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.cfg = d / "mailboxes.json"
        self.cfg.write_text(json.dumps({"_comment": "x", "mailboxes": self.BOXES}, ensure_ascii=False), encoding="utf-8")
        os.chmod(self.cfg, 0o600)
        (d / "accounts.json").write_text(json.dumps(self.SUBMIT, ensure_ascii=False), encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"PAPER_MAILBOXES": str(self.cfg), "PAPER_SUBMIT_HOME": str(d),
                                                "T_MAIL_PW": "s3cret"})
        self.env.start()
        FakeIMAP.commands.clear()
        FakeIMAP.selected.clear()
        FakeIMAP.reject_charset = False
        FakeSMTP.sent.clear()
        self.imap = mock.patch.object(imaplib, "IMAP4_SSL", FakeIMAP)
        self.imap.start()

    def tearDown(self):
        self.imap.stop()
        self.env.stop()
        self.tmp.cleanup()

    def saved(self):
        return json.loads(self.cfg.read_text(encoding="utf-8"))

    def backups(self):
        return sorted(Path(self.tmp.name).glob("mailboxes.json.bak-*"))


class ReadTest(Base):
    def test_inbox_newest_first_readonly(self):
        rows = mailboxes.inbox("alice@example.com", limit=2)
        self.assertEqual([r["uid"] for r in rows], ["3", "2"])
        self.assertEqual(rows[0]["subject"], "稿件状态更新")
        self.assertEqual(FakeIMAP.selected, [('"INBOX"', True)])

    def test_search_ascii_single_run_without_charset(self):
        rows = mailboxes.search("alice@example.com", sender="editor@example.org", since="2026-10-12")
        self.assertEqual([r["uid"] for r in rows], ["3"])
        (cmd, args, lit), = [c for c in FakeIMAP.commands if c[0] == "search"]
        self.assertEqual(args, (None, "FROM", '"editor@example.org"', "SINCE", "12-Oct-2026"))
        self.assertIsNone(lit)

    def test_search_chinese_uses_utf8_literal_last(self):
        rows = mailboxes.search("alice@example.com", subject="确认", sender="editor@example.org")
        self.assertEqual([r["uid"] for r in rows], ["2"])
        (_, args, lit), = [c for c in FakeIMAP.commands if c[0] == "search"]
        self.assertEqual(args[:2], ("CHARSET", "UTF-8"))
        self.assertEqual(args[-1], "SUBJECT")
        self.assertEqual(lit, "确认".encode("utf-8"))

    def test_search_two_chinese_terms_intersect(self):
        rows = mailboxes.search("alice@example.com", subject="稿件", body="外审")
        self.assertEqual([r["uid"] for r in rows], ["3"])
        self.assertEqual(len([c for c in FakeIMAP.commands if c[0] == "search"]), 2)
        self.assertEqual(mailboxes.search("alice@example.com", subject="稿件", body="Thanks"), [])

    def test_search_errors_are_clear(self):
        FakeIMAP.reject_charset = True
        with self.assertRaisesRegex(mailboxes.MailboxError, "UTF-8"):
            mailboxes.search("alice@example.com", subject="确认")
        with self.assertRaisesRegex(mailboxes.MailboxError, "至少"):
            mailboxes.search("alice@example.com")
        code, _, err = run(["search", "alice@example.com", "--subject", "确认"])
        self.assertEqual(code, 1)
        self.assertIn("英文关键词", err)

    def test_links_unescaped_deduped_and_hinted(self):
        rows = mailboxes.message_links(message_from_bytes(MESSAGES["2"]))
        self.assertEqual([r["url"] for r in rows], ["https://em.example.com/confirm?id=1&t=2", "https://example.com/help"])
        self.assertTrue(rows[0]["hint"])
        self.assertFalse(rows[1]["hint"])
        code, out, _ = run(["links", "alice@example.com", "2"])
        self.assertEqual(code, 0)
        self.assertIn("★ https://em.example.com/confirm?id=1&t=2", out)
        self.assertIn("Yes, I am affiliated", out)
        self.assertEqual({c[0] for c in FakeIMAP.commands}, {"fetch"})   # 只读信，不做别的
        code, _, err = run(["links", "alice@example.com", "99"])
        self.assertEqual(code, 1)

    def test_inbox_and_search_json(self):
        code, out, _ = run(["inbox", "alice@example.com", "--limit", "1", "--json"])
        self.assertEqual((code, [r["uid"] for r in json.loads(out)]), (0, ["3"]))
        code, out, _ = run(["search", "alice@example.com", "--from", "journal@example.com", "--json"])
        self.assertEqual([r["uid"] for r in json.loads(out)], ["1"])


class SendTest(Base):
    def test_preview_by_default_confirm_sends_with_cc(self):
        with mock.patch.object(mailboxes.smtplib, "SMTP_SSL", FakeSMTP):
            code, out, _ = run(["send", "alice@example.com", "--to", "x@example.com", "--cc", "y@example.com",
                                "--subject", "提醒", "--body", "正文"])
            self.assertEqual(code, 0)
            self.assertIn("预览（未发送）", out)
            self.assertIn("Cc: y@example.com", out)
            self.assertEqual(FakeSMTP.sent, [])
            code, out, _ = run(["send", "alice@example.com", "--to", "x@example.com", "--cc", "y@example.com",
                                "--subject", "提醒", "--body", "正文", "--confirm"])
        self.assertEqual(code, 0)
        (msg,) = FakeSMTP.sent
        self.assertEqual((msg["To"], msg["Cc"]), ("x@example.com", "y@example.com"))


class RegistryTest(Base):
    def test_usage_joins_registry_and_submit_accounts(self):
        u = mailboxes.usage("alice@example.com")
        self.assertEqual(u["owner"], "张三")
        self.assertEqual([s["person"] for s in u["systems"]], ["张三", "李四"])   # 地址大小写不敏感
        self.assertEqual(u["systems"][0]["system"], "Editorial Manager www.editorialmanager.com/abcd")
        o = mailboxes.usage("other@example.org")
        self.assertFalse(o["registered"])
        with self.assertRaises(mailboxes.MailboxError):
            mailboxes.usage("nobody@example.com")
        code, out, _ = run(["usage", "fixed@example.com"])
        self.assertIn("赵六", out)
        self.assertIn("Elsevier ID", out)

    def test_audit_findings(self):
        found = mailboxes.audit()
        msgs = {(f["level"], f["kind"]): [] for f in found}
        for f in found:
            msgs[(f["level"], f["kind"])].append(f["message"])
        one = msgs[("error", "one-mailbox-one-person")]
        self.assertEqual(len(one), 2)
        self.assertTrue(any("abcd" in m and "张三、李四" in m for m in one))
        self.assertTrue(any(m.startswith("Elsevier ID") and "王五、赵六" in m for m in one))
        self.assertFalse(any("wxyz" in m for m in one))                     # 不同 EM 站点各算一个系统
        unread = msgs[("error", "key-mailbox-unreadable")]
        self.assertTrue(any("fixed@example.com" in m and "王五" in m for m in unread))
        self.assertTrue(any("other@example.org" in m for m in msgs[("warn", "submitter-unregistered")]))
        self.assertTrue(any("P05" in m for m in msgs[("error", "shared-in-paper")]))
        purpose = msgs[("warn", "purpose-mismatch")]
        self.assertTrue(any("conf@example.edu" in m for m in purpose))
        self.assertTrue(any("fixed@example.com" in m and "P05" in m and "P06" not in m for m in purpose))  # P06 有例外
        self.assertFalse(any("spare@example.org" in m for m in purpose))   # 备用箱给谁都行
        code, out, _ = run(["audit"])
        self.assertEqual(code, 3)
        self.assertIn("[必须处理]", out)

    def test_audit_clean_registry_exits_zero(self):
        self.cfg.write_text(json.dumps({"a@example.com": {"imap": "h", "readable": True, "owner": "张三",
                                                          "purpose": "本人专用",
                                                          "author_links": [{"person": "张三", "role": "通讯", "papers": ["P01"]}]}}),
                            encoding="utf-8")
        Path(self.tmp.name, "accounts.json").write_text("[]", encoding="utf-8")
        self.assertEqual(run(["audit"])[:2], (0, "没有发现登记冲突。\n"))

    def test_link_appends_backs_up_and_keeps_mode(self):
        bak, msg, notes = mailboxes.link("spare@example.org", "P04", "李四", "作者")
        self.assertTrue(bak.exists())
        links = self.saved()["mailboxes"]["spare@example.org"]["author_links"]
        self.assertEqual(links, [{"person": "李四", "role": "作者", "papers": ["P03", "P04"]}])
        self.assertEqual(self.saved()["_comment"], "x")
        self.assertEqual(stat.S_IMODE(self.cfg.stat().st_mode), 0o600)
        self.assertNotIn("P04", json.loads(bak.read_text(encoding="utf-8"))["mailboxes"]["spare@example.org"]["author_links"][0]["papers"])
        bak2, msg2, _ = mailboxes.link("spare@example.org", "P04", "李四", "作者")   # 已有：不改、不备份
        self.assertIsNone(bak2)
        self.assertEqual(len(self.backups()), 1)
        mailboxes.link("spare@example.org", "P10", "王五", "通讯")
        self.assertEqual(self.saved()["mailboxes"]["spare@example.org"]["author_links"][-1],
                         {"person": "王五", "role": "通讯", "papers": ["P10"]})
        self.assertEqual(len(self.backups()), 2)

    def test_link_refuses_shared_mailbox_and_role_change(self):
        code, _, err = run(["link", "spare@example.org", "--paper", "P03", "--person", "王五"])
        self.assertEqual(code, 3)
        self.assertIn("李四", err)
        with self.assertRaises(mailboxes.RuleViolation):
            mailboxes.link("spare@example.org", "P03", "李四", "通讯")
        with self.assertRaises(mailboxes.MailboxError):
            mailboxes.link("nobody@example.com", "P01", "张三")
        self.assertEqual(self.backups(), [])

    def test_link_warns_unreadable_key_role(self):
        _, _, notes = mailboxes.link("fixed@example.com", "P11", "王五", "通讯")
        self.assertTrue(any("readable" in n for n in notes))

    def test_unlink_removes_and_drops_empty(self):
        code, out, _ = run(["unlink", "spare@example.org", "--paper", "P03"])
        self.assertEqual(code, 0)
        self.assertEqual(self.saved()["mailboxes"]["spare@example.org"]["author_links"], [])
        mailboxes.unlink("fixed@example.com", "P05", person="赵六")
        links = self.saved()["mailboxes"]["fixed@example.com"]["author_links"]
        self.assertEqual(links, [{"person": "王五", "role": "通讯", "papers": ["P05"]},
                                 {"person": "赵六", "role": "作者", "papers": ["P06"]}])
        code, _, err = run(["unlink", "fixed@example.com", "--paper", "P99"])
        self.assertEqual(code, 1)
        self.assertEqual(len(self.backups()), 2)


if __name__ == "__main__":
    unittest.main()
