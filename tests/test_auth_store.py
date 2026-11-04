import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from seoultech_mcp.auth_store import AuthStore


class AuthStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "auth" / "auth.db"
        self.store = AuthStore(self.path, Fernet.generate_key())

    def tearDown(self):
        self.folder.cleanup()

    def test_no_plaintext_secrets_on_disk(self):
        self.store.set_password("me@seoultech.ac.kr", "school-password")
        self.store.put("access", "bearer-token-value", {"subject": "me@seoultech.ac.kr"})
        raw = self.path.read_bytes()
        self.assertNotIn(b"school-password", raw)
        self.assertNotIn(b"bearer-token-value", raw)
        self.assertEqual(self.store.get_password("me@seoultech.ac.kr"), "school-password")
        self.assertEqual(self.store.get("access", "bearer-token-value")["subject"], "me@seoultech.ac.kr")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_expiry_and_single_use(self):
        self.store.put("code", "c1", {"x": 1}, ttl=60)
        self.assertEqual(self.store.pop("code", "c1"), {"x": 1})
        self.assertIsNone(self.store.get("code", "c1"))
        self.store.put("code", "c2", {"x": 2}, ttl=60)
        with patch("seoultech_mcp.auth_store.time.time", return_value=time.time() + 61):
            self.assertIsNone(self.store.get("code", "c2"))

    def test_wrong_key_cannot_decrypt(self):
        self.store.set_password("me@seoultech.ac.kr", "pw")
        other = AuthStore(self.path, Fernet.generate_key())
        self.assertIsNone(other.get_password("me@seoultech.ac.kr"))


if __name__ == "__main__":
    unittest.main()
