import asyncio
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from seoultech_mcp.auth_store import AuthStore
from seoultech_mcp.login import MAX_ATTEMPTS, make_login_handler
from seoultech_mcp.oauth import SeoulTechOAuthProvider


class LoginPageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = AuthStore(Path(self.folder.name) / "auth.db", Fernet.generate_key())
        self.provider = SeoulTechOAuthProvider(self.store, "https://mail-mcp.example.com")
        verify = lambda email, password: (email, password) == ("me@seoultech.ac.kr", "right")
        app = Starlette(routes=[Route("/login", make_login_handler(self.provider, verify), methods=["GET", "POST"])])
        self.http = TestClient(app, follow_redirects=False)
        client = OAuthClientInformationFull(client_id="c1", redirect_uris=["https://claude.ai/cb"])
        params = AuthorizationParams(
            state="s1", scopes=["mail.read"], code_challenge="x" * 43,
            redirect_uri="https://claude.ai/cb", redirect_uri_provided_explicitly=True,
        )
        url = asyncio.run(self.provider.authorize(client, params))
        self.request_id = parse_qs(urlparse(url).query)["request"][0]

    def tearDown(self):
        self.folder.cleanup()

    def post(self, username, password):
        return self.http.post("/login", data={"request": self.request_id, "username": username, "password": password})

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

    def test_unknown_request(self):
        self.assertEqual(self.http.get("/login?request=nope").status_code, 400)
        self.assertEqual(
            self.http.post("/login", data={"request": "nope", "username": "me", "password": "right"}).status_code, 400
        )


if __name__ == "__main__":
    unittest.main()
