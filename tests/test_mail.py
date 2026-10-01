import os
import stat
import tempfile
import unittest
from datetime import date
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from seoultech_mcp.cli import ai_digest
from seoultech_mcp.mail import MailClient, MailError, _body, _parse_metadata, settings
from seoultech_mcp.webmail import WebmailClient, _body_text


HEADER = (
    b"From: =?utf-8?b?7ZWZ6rWQ?= <office@seoultech.ac.kr>\r\n"
    b"To: me@seoultech.ac.kr\r\n"
    b"Subject: =?utf-8?b?7JWM66a8?=\r\n"
    b"Date: Mon, 28 Sep 2026 15:30:00 +0000\r\n"
    b"Message-ID: <test@example.com>\r\n\r\n"
)
PREFIX = b'1 (UID 42 FLAGS () INTERNALDATE "28-Sep-2026 15:30:00 +0000" RFC822.SIZE 400 BODY[HEADER] {180}'


class FakeIMAP:
    def __init__(self, *_args, **_kwargs):
        self.calls = []

    def login(self, username, password):
        self.calls.append(("login", username, password))
        return "OK", [b"logged in"]

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return "OK", [b"1"]

    def uid(self, command, *args):
        self.calls.append((command, *args))
        if command == "search":
            return "OK", [b"42"]
        if "HEADER.FIELDS" in args[-1]:
            return "OK", [(PREFIX, HEADER), b")"]
        return "OK", [(PREFIX + b" BODY[]<0> {300}", HEADER + b"Hello from SeoulTech"), b")"]

    def logout(self):
        self.calls.append(("logout",))
        return "BYE", [b"bye"]


class MailTests(unittest.TestCase):
    def test_korean_date_boundary_and_read_only_fetch(self):
        with patch.dict(os.environ, {"SEOULTECH_EMAIL": "me", "SEOULTECH_PASSWORD": "test", "SEOULTECH_BACKEND": "imap"}), patch(
            "seoultech_mcp.mail.imaplib.IMAP4_SSL", FakeIMAP
        ):
            with MailClient() as client:
                listing = client.list_messages(date(2026, 9, 29))
                detail = client.get_message(42)
                self.assertEqual(listing["total"], 1)
                self.assertEqual(listing["messages"][0]["received_at"], "2026-09-29T00:30:00+09:00")
                self.assertTrue(listing["messages"][0]["unread"])
                self.assertIn("Hello from SeoulTech", detail["body"])
                self.assertIn(("select", "INBOX", True), client.connection.calls)
                self.assertTrue(all("BODY.PEEK" in call[-1] for call in client.connection.calls if call[0] == "fetch"))

    def test_seen_flag_and_html_text(self):
        item = _parse_metadata(PREFIX.replace(b"FLAGS ()", b"FLAGS (\\Seen)"), HEADER)
        self.assertFalse(item.unread)
        raw = b"Content-Type: text/html; charset=utf-8\r\n\r\n<p>Meeting<br>tomorrow</p><script>ignore()</script>"
        self.assertEqual(_body(raw), "Meeting\ntomorrow")

    def test_missing_credentials(self):
        with patch.dict(os.environ, {"SEOULTECH_EMAIL": "", "SEOULTECH_PASSWORD": "", "SEOULTECH_CREDENTIALS_FILE": "/nonexistent/test"}):
            with self.assertRaises(MailError):
                settings()

    def test_ai_digest_writes_private_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "reports" / "2026-09-29.md"

            def fake_codex(command, **kwargs):
                self.assertEqual(command[-1], "-")
                self.assertIn("<mail_data>", kwargs["input"])
                self.assertNotIn("SEOULTECH_PASSWORD", kwargs["env"])
                Path(command[-2]).write_text("# 요약\n메일 0건", encoding="utf-8")
                return CompletedProcess(command, 0)

            digest = {
                "date": "2026-09-29", "total": 1, "unread": 1, "timezone": "Asia/Seoul", "truncated": False,
                "messages": [{"subject": "알림", "sender": "학교", "received_at": "2026-09-29T00:30:00+09:00", "unread": True, "uid": 42, "preview": "시험 일정"}],
            }
            with patch.dict(os.environ, {"SEOULTECH_CODEX_BIN": "/usr/bin/codex", "SEOULTECH_PASSWORD": "secret"}), patch(
                "seoultech_mcp.cli.subprocess.run", side_effect=fake_codex
            ):
                ai_digest(digest, target)
            self.assertIn("메일 0건", target.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o700)

    def test_webmail_date_filter_and_html_body(self):
        row = {
            "messageId": 1105, "subject": "알림", "fromRecipient": {"displayName": "학교", "emailAddress": "office@example.com"},
            "receivedDateTime": "2026-09-28T15:30:00Z", "messageFlag": "N", "mailSize": 300,
        }
        older = {**row, "messageId": 1100, "receivedDateTime": "2026-09-27T12:00:00Z"}
        client = WebmailClient.__new__(WebmailClient)
        client._mailbox_id = 1
        client._get_json = lambda path: {"value": [row, older], "total": 2}
        listing = client.list_messages(date(2026, 9, 29))
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["messages"][0]["uid"], 1105)
        self.assertTrue(listing["messages"][0]["unread"])
        self.assertEqual(_body_text("<p>확인<br>필요</p><script>ignore()</script>"), "확인\n필요")


if __name__ == "__main__":
    unittest.main()
