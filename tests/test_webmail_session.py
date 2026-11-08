import unittest
from unittest.mock import patch

from seoultech_mcp import webmail
from seoultech_mcp.mail import MailError
from seoultech_mcp.webmail import WebmailClient, forget_sessions

MAILBOXES = {"value": [{"type": 2, "mailboxId": 7}]}


class SessionReuseTests(unittest.TestCase):
    def setUp(self):
        webmail._sessions.clear()
        self.logins = []
        self.valid_cookies = set()

        def browser_login(client, password):
            self.logins.append((client.username, password))
            cookie = f"s={len(self.logins)}"
            self.valid_cookies.add(cookie)
            return cookie

        def get_json(client, path):
            if client._cookie not in self.valid_cookies:
                raise MailError("expired")
            return MAILBOXES

        patches = [patch.object(WebmailClient, "_browser_login", browser_login), patch.object(WebmailClient, "_get_json", get_json)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def enter(self, email="me@seoultech.ac.kr", password="pw"):
        with WebmailClient((email, password)) as client:
            return client._mailbox_id

    def test_second_call_reuses_session(self):
        self.assertEqual(self.enter(), 7)
        self.assertEqual(self.enter(), 7)
        self.assertEqual(len(self.logins), 1)

    def test_different_password_does_not_reuse(self):
        self.enter()
        self.enter(password="other")
        self.assertEqual(len(self.logins), 2)

    def test_server_side_expiry_and_ttl_trigger_relogin(self):
        self.enter()
        self.valid_cookies.clear()
        self.enter()
        self.assertEqual(len(self.logins), 2)
        with patch("seoultech_mcp.webmail.time.time", return_value=webmail.time.time() + webmail.SESSION_TTL + 1):
            self.enter()
        self.assertEqual(len(self.logins), 3)

    def test_forget_sessions(self):
        self.enter()
        forget_sessions("ME@seoultech.ac.kr")
        self.enter()
        self.assertEqual(len(self.logins), 2)


if __name__ == "__main__":
    unittest.main()
