import asyncio
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from mcp.server.auth.provider import AuthorizationParams, AuthorizeError, TokenError
from mcp.shared.auth import OAuthClientInformationFull

from seoultech_mcp.auth_store import AuthStore
from seoultech_mcp.oauth import SeoulTechOAuthProvider


def run(coro):
    return asyncio.run(coro)


class OAuthProviderTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        store = AuthStore(Path(self.folder.name) / "auth.db", Fernet.generate_key())
        self.provider = SeoulTechOAuthProvider(store, "https://mail-mcp.example.com/")
        self.client = OAuthClientInformationFull(client_id="c1", redirect_uris=["https://claude.ai/api/mcp/auth_callback"])
        run(self.provider.register_client(self.client))

    def tearDown(self):
        self.folder.cleanup()

    def login(self, state="s1"):
        params = AuthorizationParams(
            state=state, scopes=["mail.read"], code_challenge="x" * 43,
            redirect_uri="https://claude.ai/api/mcp/auth_callback", redirect_uri_provided_explicitly=True,
            resource="https://mail-mcp.example.com/mcp",
        )
        login_url = run(self.provider.authorize(self.client, params))
        self.assertTrue(login_url.startswith("https://mail-mcp.example.com/login?request="))
        request_id = parse_qs(urlparse(login_url).query)["request"][0]
        redirect = self.provider.complete_login(request_id, "me@seoultech.ac.kr")
        query = parse_qs(urlparse(redirect).query)
        self.assertEqual(query["state"], [state])
        return request_id, query["code"][0]

    def test_full_flow(self):
        self.assertEqual(run(self.provider.get_client("c1")).client_id, "c1")
        request_id, code = self.login()
        with self.assertRaises(AuthorizeError):
            self.provider.complete_login(request_id, "me@seoultech.ac.kr")  # Pending request is single-use.

        loaded = run(self.provider.load_authorization_code(self.client, code))
        self.assertEqual(loaded.subject, "me@seoultech.ac.kr")
        token = run(self.provider.exchange_authorization_code(self.client, loaded))
        with self.assertRaises(TokenError):
            run(self.provider.exchange_authorization_code(self.client, loaded))  # Code replay.

        access = run(self.provider.load_access_token(token.access_token))
        self.assertEqual((access.subject, access.resource), ("me@seoultech.ac.kr", "https://mail-mcp.example.com/mcp"))

        refresh = run(self.provider.load_refresh_token(self.client, token.refresh_token))
        rotated = run(self.provider.exchange_refresh_token(self.client, refresh, []))
        self.assertIsNone(run(self.provider.load_access_token(token.access_token)))
        self.assertIsNone(run(self.provider.load_refresh_token(self.client, token.refresh_token)))

        new_access = run(self.provider.load_access_token(rotated.access_token))
        self.assertEqual(new_access.subject, "me@seoultech.ac.kr")
        run(self.provider.revoke_token(new_access))
        self.assertIsNone(run(self.provider.load_access_token(rotated.access_token)))
        self.assertIsNone(run(self.provider.load_refresh_token(self.client, rotated.refresh_token)))

    def test_code_bound_to_client(self):
        _, code = self.login()
        other = OAuthClientInformationFull(client_id="c2", redirect_uris=["https://evil.example.com/cb"])
        self.assertIsNone(run(self.provider.load_authorization_code(other, code)))


if __name__ == "__main__":
    unittest.main()
