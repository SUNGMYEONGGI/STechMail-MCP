import asyncio
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from seoultech_mcp.auth_store import AuthStore
from seoultech_mcp.login import MAX_ATTEMPTS, MAX_FAILURES_PER_ACCOUNT, MAX_FAILURES_PER_IP, RATE_WINDOW, make_delete_handler, make_login_handler
from seoultech_mcp.oauth import SeoulTechOAuthProvider


class LoginPageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = AuthStore(Path(self.folder.name) / "auth.db", Fernet.generate_key())
        self.provider = SeoulTechOAuthProvider(self.store, "https://mail-mcp.example.com")
        verify = lambda email, password: (email, password) == ("me@seoultech.ac.kr", "right")
        app = Starlette(routes=[
            Route("/login", make_login_handler(self.provider, verify), methods=["GET", "POST"]),
            Route("/account/delete", make_delete_handler(self.store, verify), methods=["GET", "POST"]),
        ])
        self.http = TestClient(app, follow_redirects=False)
        self.request_id = self.new_request()

    def new_request(self):
        client = OAuthClientInformationFull(client_id="c1", redirect_uris=["https://claude.ai/cb"])
        params = AuthorizationParams(
            state="s1", scopes=["mail.read"], code_challenge="x" * 43,
            redirect_uri="https://claude.ai/cb", redirect_uri_provided_explicitly=True,
        )
        url = asyncio.run(self.provider.authorize(client, params))
        return parse_qs(urlparse(url).query)["request"][0]

    def tearDown(self):
        self.folder.cleanup()

    def post(self, username, password, request_id=None):
        data = {"request": request_id or self.request_id, "username": username, "password": password}
        return self.http.post("/login", data=data)

    def test_success_redirects_with_code_and_stores_password(self):
        page = self.http.get(f"/login?request={self.request_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn('name="password"', page.text)

        response = self.post("me", "right")
        self.assertEqual(response.status_code, 302)
        location = urlparse(response.headers["location"])
        self.assertEqual(f"{location.scheme}://{location.netloc}{location.path}", "https://claude.ai/cb")
        self.assertIn("code", parse_qs(location.query))
        self.assertEqual(self.store.get_password("me@seoultech.ac.kr"), "right")
        self.assertEqual(self.post("me", "right").status_code, 400)  # Request already used.

    def test_failures_are_limited(self):
        for attempt in range(1, MAX_ATTEMPTS):
            response = self.post("me", "wrong")
            self.assertEqual(response.status_code, 401)
            self.assertIn(f"{attempt}/{MAX_ATTEMPTS}", response.text)
        self.assertEqual(self.post("me", "wrong").status_code, 400)
        self.assertEqual(self.post("me", "right").status_code, 400)
        self.assertIsNone(self.store.get_password("me@seoultech.ac.kr"))

    def test_account_limit_survives_new_requests(self):
        for _ in range(MAX_FAILURES_PER_ACCOUNT):
            self.assertEqual(self.post("me", "wrong", self.new_request()).status_code, 401)
        blocked = self.post("me", "right", self.new_request())  # Even the right password waits.
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)
        later = time.time() + RATE_WINDOW + 1
        with patch("seoultech_mcp.login.time.time", return_value=later), patch("seoultech_mcp.auth_store.time.time", return_value=later):
            self.assertEqual(self.post("me", "right", self.new_request()).status_code, 302)

    def test_ip_limit_across_accounts(self):
        for n in range(MAX_FAILURES_PER_IP):
            self.assertEqual(self.post(f"user{n}", "wrong", self.new_request()).status_code, 401)
        self.assertEqual(self.post("me", "right", self.new_request()).status_code, 429)

    def test_success_resets_account_counter(self):
        for _ in range(MAX_FAILURES_PER_ACCOUNT - 1):
            self.post("me", "wrong", self.new_request())
        self.assertEqual(self.post("me", "right", self.new_request()).status_code, 302)
        self.assertEqual(self.post("me", "wrong", self.new_request()).status_code, 401)  # Not 429.

    def test_delete_account(self):
        self.assertEqual(self.post("me", "right").status_code, 302)
        self.assertEqual(self.http.get("/account/delete").status_code, 200)
        wrong = self.http.post("/account/delete", data={"username": "me", "password": "nope"})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(self.store.get_password("me@seoultech.ac.kr"), "right")
        done = self.http.post("/account/delete", data={"username": "me", "password": "right"})
        self.assertEqual(done.status_code, 200)
        self.assertIsNone(self.store.get_password("me@seoultech.ac.kr"))

    def test_delete_account_is_rate_limited(self):
        for _ in range(MAX_FAILURES_PER_ACCOUNT):
            self.http.post("/account/delete", data={"username": "me", "password": "nope"})
        self.assertEqual(self.http.post("/account/delete", data={"username": "me", "password": "right"}).status_code, 429)

    def test_unknown_request(self):
        self.assertEqual(self.http.get("/login?request=nope").status_code, 400)
        self.assertEqual(
            self.http.post("/login", data={"request": "nope", "username": "me", "password": "right"}).status_code, 400
        )


if __name__ == "__main__":
    unittest.main()
