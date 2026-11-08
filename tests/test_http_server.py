import base64
import hashlib
import json
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from starlette.testclient import TestClient

from seoultech_mcp.auth_store import AuthStore
from seoultech_mcp.server import create_server

PUBLIC = "http://localhost:8000"
REDIRECT = "http://localhost:9999/callback"


class FakeMailClient:
    """Stands in for webmail: accepts one account and records who logged in."""

    logins = []

    def __init__(self, credentials=None):
        self.credentials = credentials

    def __enter__(self):
        from seoultech_mcp.mail import MailError

        if self.credentials != ("me@seoultech.ac.kr", "right"):
            raise MailError("login failed")
        FakeMailClient.logins.append(self.credentials)
        self.username, self.backend = self.credentials[0], "fake"
        return self

    def __exit__(self, *_):
        pass


def rpc(http, token, method, params=None, session=None, id_=1):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    if session:
        headers["mcp-session-id"] = session
    body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if id_ is not None:
        body["id"] = id_
    return http.post("/mcp", json=body, headers=headers)


def payload(response):
    if response.headers["content-type"].startswith("application/json"):
        return response.json()
    lines = [line[5:].strip() for line in response.text.splitlines() if line.startswith("data:")]
    return json.loads(lines[-1])


class HttpServerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = AuthStore(Path(self.folder.name) / "auth.db", Fernet.generate_key())
        FakeMailClient.logins = []

    def tearDown(self):
        self.folder.cleanup()

    def test_oauth_flow_and_per_user_tool_call(self):
        with patch("seoultech_mcp.login.MailClient", FakeMailClient), patch("seoultech_mcp.server.MailClient", FakeMailClient):
            app = create_server(self.store, PUBLIC).streamable_http_app()
            with TestClient(app, base_url=PUBLIC, follow_redirects=False) as http:
                self.assertEqual(http.post("/mcp", json={}).status_code, 401)
                meta = http.get("/.well-known/oauth-authorization-server").json()
                self.assertIn("/register", meta["registration_endpoint"])

                client = http.post("/register", json={"redirect_uris": [REDIRECT], "token_endpoint_auth_method": "none"}).json()
                verifier = secrets.token_urlsafe(48)
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
                authorize = http.get("/authorize", params={
                    "response_type": "code", "client_id": client["client_id"], "redirect_uri": REDIRECT,
                    "code_challenge": challenge, "code_challenge_method": "S256", "state": "st",
                    "resource": f"{PUBLIC}/mcp",
                })
                login_url = urlparse(authorize.headers["location"])
                request_id = parse_qs(login_url.query)["request"][0]
                done = http.post("/login", data={"request": request_id, "username": "me", "password": "right"})
                code = parse_qs(urlparse(done.headers["location"]).query)["code"][0]

                token = http.post("/token", data={
                    "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                    "client_id": client["client_id"], "code_verifier": verifier, "resource": f"{PUBLIC}/mcp",
                }).json()["access_token"]

                init = rpc(http, token, "initialize", {
                    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"},
                })
                self.assertEqual(init.status_code, 200, init.text)
                session = init.headers.get("mcp-session-id")
                rpc(http, token, "notifications/initialized", session=session, id_=None)
                result = payload(rpc(http, token, "tools/call", {"name": "check_mail_connection", "arguments": {}}, session, 2))
                self.assertFalse(result["result"].get("isError"), result)
                self.assertIn("me@seoultech.ac.kr", result["result"]["content"][0]["text"])
                self.assertEqual(FakeMailClient.logins[-1], ("me@seoultech.ac.kr", "right"))

                self.assertEqual(rpc(http, "bogus", "tools/list", session=session).status_code, 401)

                self.assertEqual(http.post("/revoke", data={"token": token, "client_id": client["client_id"], "client_secret": ""}).status_code, 200)
                self.assertIsNone(self.store.get_password("me@seoultech.ac.kr"))
                self.assertEqual(http.get("/account/delete").status_code, 200)


if __name__ == "__main__":
    unittest.main()
