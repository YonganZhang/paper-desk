"""mailboxes.py 的最小单元测试：配置解析、凭证来源、假 IMAP/SMTP 上的登录与发信。不联网。

运行：python3 -I -m unittest discover -s skills/paper-status-check/tests -v
"""
import email
import imaplib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mailboxes  # noqa: E402


class FakeIMAP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.calls = host, port, []
        FakeIMAP.instances.append(self)

    def login(self, user, pw):
        self.calls.append(("login", user, pw))

    def authenticate(self, mech, cb):
        self.calls.append(("authenticate", mech, cb(b"")))

    def select(self, mailbox="INBOX", readonly=False):
        return ("OK", [b"3"]) if mailbox in ("INBOX", '"INBOX"') else ("NO", [b"no such folder"])

    def _simple_command(self, *a):
        self.calls.append(("simple", *a))


class FakeSMTP:
    sent = []

    def __init__(self, host, port, context=None, timeout=None):
        self.host, self.port, self.logged = host, port, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, pw):
        self.logged = (user, pw)

    def send_message(self, msg):
        FakeSMTP.sent.append((self.host, self.port, self.logged, msg))


class MailboxesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / "mailboxes.json"
        self.cfg.write_text(json.dumps({"mailboxes": {
            "_note": {"ignored": True},
            "alice@example.com": {"imap": "imap.example.com", "smtp": "smtp.example.com", "password_env": "T_MAIL_PW"},
            "bob@example.org": {"imap": "imap.example.org:1993", "smtp": "smtp.example.org:587", "smtp_tls": "starttls",
                                "username": "bob", "password_cmd": "printf 'from-cmd\\n'"},
            "carol@example.edu": {"imap": "imap.example.edu", "auth": "xoauth2", "token_cmd": "printf tok123"},
            "none@example.com": {"imap": "imap.example.com"},
        }}), encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"PAPER_MAILBOXES": str(self.cfg), "T_MAIL_PW": "s3cret"})
        self.env.start()
        FakeIMAP.instances.clear()
        FakeSMTP.sent.clear()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_load_skips_comment_keys_and_accepts_flat_mapping(self):
        self.assertEqual(sorted(mailboxes.load_accounts()),
                         ["alice@example.com", "bob@example.org", "carol@example.edu", "none@example.com"])
        self.cfg.write_text(json.dumps({"x@example.com": {"imap": "h"}}), encoding="utf-8")
        self.assertEqual(list(mailboxes.load_accounts()), ["x@example.com"])

    def test_missing_config_and_unknown_address_raise(self):
        with self.assertRaises(mailboxes.MailboxError):
            mailboxes.acct("nobody@example.com")
        os.environ["PAPER_MAILBOXES"] = str(Path(self.tmp.name) / "absent.json")
        with self.assertRaises(mailboxes.MailboxError):
            mailboxes.load_accounts()

    def test_secret_sources(self):
        acc = mailboxes.load_accounts()
        self.assertEqual(mailboxes.secret(acc["alice@example.com"]), "s3cret")
        self.assertEqual(mailboxes.secret(acc["bob@example.org"]), "from-cmd")
        with self.assertRaises(mailboxes.MailboxError):
            mailboxes.secret(acc["none@example.com"])
        os.environ["T_MAIL_PW"] = ""
        with self.assertRaises(mailboxes.MailboxError):
            mailboxes.secret(acc["alice@example.com"])

    def test_imap_login_ports_and_select_failure(self):
        acc = mailboxes.load_accounts()
        with mock.patch.object(imaplib, "IMAP4_SSL", FakeIMAP):
            M = mailboxes.imap_conn(acc["bob@example.org"], "bob@example.org")
            self.assertEqual((M.host, M.port), ("imap.example.org", 1993))
            self.assertIn(("login", "bob", "from-cmd"), M.calls)
            self.assertEqual(M.select("INBOX", readonly=True)[0], "OK")
            with self.assertRaises(mailboxes.MailboxError):
                M.select('"Spam"', readonly=True)
            M2 = mailboxes.imap_conn(acc["alice@example.com"], "alice@example.com")
            self.assertEqual(M2.port, 993)
            self.assertIn(("login", "alice@example.com", "s3cret"), M2.calls)

    def test_xoauth2_uses_token_cmd(self):
        acc = mailboxes.load_accounts()
        with mock.patch.object(imaplib, "IMAP4_SSL", FakeIMAP):
            M = mailboxes.imap_conn(acc["carol@example.edu"], "carol@example.edu")
        self.assertEqual(M.calls[0], ("authenticate", "XOAUTH2", b"user=carol@example.edu\x01auth=Bearer tok123\x01\x01"))

    def test_send_ssl_and_starttls(self):
        with mock.patch.object(mailboxes.smtplib, "SMTP_SSL", FakeSMTP), mock.patch.object(mailboxes.smtplib, "SMTP", FakeSMTP):
            mailboxes.send("alice@example.com", ["x@example.com", "y@example.com"], "主题", "正文")
            mailboxes.send("bob@example.org", "z@example.com", "s", "b")
        (h1, p1, login1, msg1), (h2, p2, login2, _) = FakeSMTP.sent
        self.assertEqual((h1, p1, login1), ("smtp.example.com", 465, ("alice@example.com", "s3cret")))
        self.assertEqual(msg1["To"], "x@example.com, y@example.com")
        self.assertEqual(str(msg1["Subject"]), "主题")
        self.assertEqual((h2, p2, login2), ("smtp.example.org", 587, ("bob", "from-cmd")))

    def test_dh_and_extract_body(self):
        self.assertEqual(mailboxes.dh("=?utf-8?b?5L2g5aW9?="), "你好")
        self.assertEqual(mailboxes.dh(None), "")
        m = email.message_from_string("Content-Type: text/html; charset=utf-8\n\n<p>Hello <b>World</b></p><script>x()</script>")
        self.assertEqual(" ".join(mailboxes.extract_body(m).split()), "Hello World")


if __name__ == "__main__":
    unittest.main()
