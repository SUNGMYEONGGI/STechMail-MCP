"""SQLite store for OAuth state and encrypted SeoulTech passwords."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

# Bearer secrets are stored only as SHA-256 hashes so a leaked DB cannot be replayed.
HASHED_KINDS = {"pending", "code", "access", "refresh"}


class AuthStore:
    def __init__(self, path: str | Path, key: str | bytes) -> None:
        self.path = Path(path).expanduser()
        self._fernet = Fernet(key)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.close(os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600))
        os.chmod(self.path, 0o600)
        with closing(self._connect()) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS items ("
                "kind TEXT NOT NULL, id TEXT NOT NULL, value TEXT NOT NULL, expires_at REAL, "
                "PRIMARY KEY (kind, id))"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    @staticmethod
    def _id(kind: str, key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest() if kind in HASHED_KINDS else key

    def put(self, kind: str, key: str, value: dict[str, Any], ttl: float | None = None) -> None:
        expires = time.time() + ttl if ttl is not None else None
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT OR REPLACE INTO items VALUES (?, ?, ?, ?)",
                (kind, self._id(kind, key), json.dumps(value), expires),
            )

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        with closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT value, expires_at FROM items WHERE kind = ? AND id = ?", (kind, self._id(kind, key))
            ).fetchone()
            if row is None:
                return None
            if row[1] is not None and row[1] < time.time():
                db.execute("DELETE FROM items WHERE kind = ? AND id = ?", (kind, self._id(kind, key)))
                return None
            return json.loads(row[0])

    def pop(self, kind: str, key: str) -> dict[str, Any] | None:
        """Get and delete: single-use secrets (codes, pending logins, rotated refresh tokens)."""
        value = self.get(kind, key)
        self.delete(kind, key)
        return value

    def delete(self, kind: str, key: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM items WHERE kind = ? AND id = ?", (kind, self._id(kind, key)))

    def delete_grant(self, grant: str) -> None:
        """Delete every token issued under one grant (access + refresh pair)."""
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM items WHERE json_extract(value, '$.grant') = ?", (grant,))

    def purge_expired(self) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM items WHERE expires_at IS NOT NULL AND expires_at < ?", (time.time(),))

    def set_password(self, email: str, password: str) -> None:
        self.put("user", email, {"password": self._fernet.encrypt(password.encode()).decode()})

    def get_password(self, email: str) -> str | None:
        user = self.get("user", email)
        if user is None:
            return None
        try:
            return self._fernet.decrypt(user["password"].encode()).decode()
        except InvalidToken:
            return None  # Key rotated: the user must sign in again.
