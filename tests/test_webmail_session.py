import http.cookiejar
import io
import unittest
from urllib.parse import parse_qs
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

        def fake_login(client, password):
            self.logins.append((client.username, password))
            cookie = f"s={len(self.logins)}"
            self.valid_cookies.add(cookie)
            return cookie

        def get_json(client, path):
            if client._cookie not in self.valid_cookies:
                raise MailError("expired")
            return MAILBOXES

        patches = [patch.object(WebmailClient, "_http_login", fake_login), patch.object(WebmailClient, "_get_json", get_json)]
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


class HttpLoginTests(unittest.TestCase):
    def login(self, success):
        posts = []

        class Opener:
            addheaders = []

            def __init__(self, jar):
                self.jar = jar

            def set_cookie(self, name, value):
                self.jar.set_cookie(http.cookiejar.Cookie(
                    0, name, value, None, False, "mail.seoultech.ac.kr", False, False, "/", True, True, None, False, None, None, {}
                ))

            def open(self, url, data=None, timeout=None):
                url = getattr(url, "full_url", url)
                posts.append((url, data))
                if url.endswith("/member/login"):
                    self.set_cookie("csrf_mailplug_token", "csrf1")
                    body = b'<input type="hidden" name="mailplug_token" value="old"><input type="hidden" name="myvalue" value="mv">'
                elif url.endswith("/member/do_login"):
                    if success:
                        self.set_cookie("MP_AUT", "a")
                    body = b""
                else:
                    body = b"{}"
                return io.BytesIO(body)

        def build_opener(handler):
            return Opener(handler.cookiejar)

        client = WebmailClient(("me@seoultech.ac.kr", "pw"))
        client.username = "me@seoultech.ac.kr"
        with patch("seoultech_mcp.webmail.urllib.request.build_opener", build_opener):
            return client._http_login("p@ss"), posts

    def test_posts_form_with_csrf_token_and_refreshes(self):
        cookie, posts = self.login(success=True)
        form = parse_qs(posts[1][1].decode())
        self.assertEqual((form["cid"], form["cpw"], form["mailplug_token"], form["myvalue"]), (["me"], ["p@ss"], ["csrf1"], ["mv"]))
        self.assertTrue(posts[2][0].endswith("/auth/token/refresh"))
        self.assertIn("MP_AUT=a", cookie)

    def test_wrong_password_raises(self):
        with self.assertRaises(MailError):
            self.login(success=False)


if __name__ == "__main__":
    unittest.main()
