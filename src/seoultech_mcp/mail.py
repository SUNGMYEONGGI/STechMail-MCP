"""Small, read-only IMAP adapter for SeoulTech's Mailplug service."""

from __future__ import annotations

import imaplib
import json
import os
import re
import ssl
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from email import policy
from email.header import decode_header
from email.parser import BytesParser
from email.utils import getaddresses
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo
from pathlib import Path


SEOUL = ZoneInfo("Asia/Seoul")
HOST = "zmimap.mailplug.com"
PORT = 993
MAX_BODY_BYTES = 262_144
MAX_SEARCH_RESULTS = 2_000
_UID = re.compile(rb"\bUID (\d+)\b")
_SIZE = re.compile(rb"\bRFC822\.SIZE (\d+)\b")
_FLAGS = re.compile(rb"\bFLAGS \(([^)]*)\)")
_INTERNAL_DATE = re.compile(rb'\bINTERNALDATE "([^"]+)"')


class MailError(RuntimeError):
    """User-facing mail connection or parsing error."""


@dataclass
class Message:
    uid: int
    subject: str
    sender: str
    to: str
    received_at: str
    header_date: str
    message_id: str
    unread: bool
    size_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _decoded(value: str | None) -> str:
    if not value:
        return ""
    pieces = []
    for part, charset in decode_header(value):
        if isinstance(part, bytes):
            pieces.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            pieces.append(part)
    return "".join(pieces).strip()


def _addresses(value: str | None) -> str:
    return ", ".join(
        f"{_decoded(name)} <{address}>" if name else address
        for name, address in getaddresses([value or ""])
    )


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"br", "p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        elif tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self.parts)).strip()


def _body(raw: bytes) -> str:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    candidates: dict[str, str] = {}
    for part in message.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        kind = part.get_content_type()
        if kind not in {"text/plain", "text/html"} or kind in candidates:
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeError, ValueError):
            payload = part.get_payload(decode=True) or b""
            content = payload.decode("utf-8", errors="replace")
        if kind == "text/html":
            parser = _HTMLText()
            parser.feed(str(content))
            content = parser.text()
        candidates[kind] = str(content).strip()
    return candidates.get("text/plain") or candidates.get("text/html") or ""


def _parse_metadata(prefix: bytes, header: bytes) -> Message:
    uid_match = _UID.search(prefix)
    date_match = _INTERNAL_DATE.search(prefix)
    if not uid_match or not date_match:
        raise MailError("메일 서버 응답에서 UID 또는 수신 시각을 읽을 수 없습니다.")
    received = datetime.strptime(date_match.group(1).decode("ascii"), "%d-%b-%Y %H:%M:%S %z")
    parsed = BytesParser(policy=policy.default).parsebytes(header, headersonly=True)
    flags_match = _FLAGS.search(prefix)
    flags = (flags_match.group(1).split() if flags_match else [])
    size_match = _SIZE.search(prefix)
    return Message(
        uid=int(uid_match.group(1)),
        subject=_decoded(str(parsed["Subject"]) if parsed["Subject"] else None),
        sender=_addresses(str(parsed["From"]) if parsed["From"] else None),
        to=_addresses(str(parsed["To"]) if parsed["To"] else None),
        received_at=received.astimezone(SEOUL).isoformat(),
        header_date=str(parsed["Date"] or ""),
        message_id=str(parsed["Message-ID"] or ""),
        unread=b"\\Seen" not in flags,
        size_bytes=int(size_match.group(1)) if size_match else 0,
    )


def parse_day(value: str | None) -> date:
    if not value:
        return datetime.now(SEOUL).date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise MailError("날짜는 YYYY-MM-DD 형식이어야 합니다.") from exc


def settings() -> tuple[str, str]:
    username = os.environ.get("SEOULTECH_EMAIL", "").strip()
    password = os.environ.get("SEOULTECH_PASSWORD", "")
    if not username or not password:
        path = Path(os.environ.get("SEOULTECH_CREDENTIALS_FILE", "~/.config/seoultech-mcp/credentials.json")).expanduser()
        if path.exists():
            if path.stat().st_mode & 0o077:
                raise MailError(f"자격 증명 파일 권한이 너무 넓습니다: {path}. chmod 600으로 제한하세요.")
            try:
                stored = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise MailError("자격 증명 파일을 읽을 수 없습니다.") from exc
            if not isinstance(stored, dict):
                raise MailError("자격 증명 파일 형식이 올바르지 않습니다.")
            username = username or stored.get("email", "")
            password = password or stored.get("password", "")
    if not isinstance(username, str) or not isinstance(password, str):
        raise MailError("자격 증명 파일 형식이 올바르지 않습니다.")
    if not username or not password:
        raise MailError("계정 정보가 없습니다. `seoultech-mail configure`를 실행하세요.")
    if "@" not in username:
        username += "@seoultech.ac.kr"
    return username, password


class ImapMailClient:
    backend = "imap"

    def __enter__(self) -> ImapMailClient:
        username, password = settings()
        try:
            self.connection = imaplib.IMAP4_SSL(HOST, PORT, ssl_context=ssl.create_default_context(), timeout=20)
            self.connection.login(username, password)
            status, _ = self.connection.select("INBOX", readonly=True)
            if status != "OK":
                raise MailError("받은편지함을 열 수 없습니다.")
        except (imaplib.IMAP4.error, OSError, ssl.SSLError) as exc:
            raise MailError("IMAP 연결 또는 로그인에 실패했습니다. 계정 정보와 웹메일의 IMAP/SMTP 사용 설정을 확인하세요.") from exc
        self.username = username
        return self

    def __exit__(self, *_: object) -> None:
        try:
            self.connection.logout()
        except (imaplib.IMAP4.error, OSError):
            pass

    def _uid(self, command: str, *args: str | None) -> list[Any]:
        try:
            status, data = self.connection.uid(command, *args)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailError("IMAP 요청에 실패했습니다.") from exc
        if status != "OK":
            raise MailError("메일 서버가 요청을 거부했습니다.")
        return data or []

    def list_messages(self, day: date, limit: int = 100, unread_only: bool = False) -> dict[str, Any]:
        if not 1 <= limit <= 500:
            raise MailError("limit은 1~500 사이여야 합니다.")
        # Search one day on either side: IMAP day boundaries depend on the server's time zone.
        since = (day - timedelta(days=1)).strftime("%d-%b-%Y")
        before = (day + timedelta(days=2)).strftime("%d-%b-%Y")
        found = self._uid("search", None, "SINCE", since, "BEFORE", before)
        uids = [int(uid) for uid in (found[0] or b"").split()]
        if len(uids) > MAX_SEARCH_RESULTS:
            raise MailError(f"검색 결과가 {MAX_SEARCH_RESULTS}건을 넘습니다. 더 좁은 날짜 범위를 사용하세요.")
        messages: list[Message] = []
        header_fields = "(UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])"
        for start in range(0, len(uids), 50):
            batch = ",".join(str(uid) for uid in uids[start:start + 50])
            for item in self._uid("fetch", batch, header_fields):
                if not isinstance(item, tuple) or len(item) != 2:
                    continue
                message = _parse_metadata(item[0], item[1])
                if date.fromisoformat(message.received_at[:10]) == day and (not unread_only or message.unread):
                    messages.append(message)
        messages.sort(key=lambda mail: (mail.received_at, mail.uid), reverse=True)
        return {
            "date": day.isoformat(),
            "timezone": "Asia/Seoul",
            "total": len(messages),
            "unread": sum(mail.unread for mail in messages),
            "truncated": len(messages) > limit,
            "messages": [mail.as_dict() for mail in messages[:limit]],
        }

    def get_message(self, uid: int, max_chars: int = 12_000) -> dict[str, Any]:
        if uid < 1:
            raise MailError("UID는 양의 정수여야 합니다.")
        if not 500 <= max_chars <= 50_000:
            raise MailError("max_chars는 500~50000 사이여야 합니다.")
        data = self._uid("fetch", str(uid), f"(UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[]<0.{MAX_BODY_BYTES}>)")
        literals = [item for item in data if isinstance(item, tuple) and len(item) == 2]
        if not literals:
            raise MailError("해당 UID의 메일을 찾을 수 없습니다.")
        prefix, raw = literals[0]
        message = _parse_metadata(prefix, raw)
        if message.uid != uid:
            raise MailError("메일 서버가 다른 UID를 반환했습니다.")
        body = _body(raw)
        return {
            **message.as_dict(),
            "body": body[:max_chars],
            "body_truncated": len(body) > max_chars or message.size_bytes > len(raw),
            "attachment_content_included": False,
        }

    def daily_digest(self, day: date, limit: int = 100, preview_chars: int = 500) -> dict[str, Any]:
        if not 50 <= preview_chars <= 2_000:
            raise MailError("preview_chars는 50~2000 사이여야 합니다.")
        listing = self.list_messages(day, limit=limit)
        for message in listing["messages"]:
            try:
                detail = self.get_message(message["uid"], max_chars=max(500, preview_chars))
                message["preview"] = detail["body"][:preview_chars]
                message["preview_truncated"] = detail["body_truncated"] or len(detail["body"]) > preview_chars
            except MailError as exc:
                message["preview"] = ""
                message["preview_error"] = str(exc)
        return listing


class MailClient:
    """Use the supported webmail session by default; allow IMAP when a school account permits it."""

    def __enter__(self):
        if os.environ.get("SEOULTECH_BACKEND", "webmail").lower() == "imap":
            self._client = ImapMailClient()
        else:
            from .webmail import WebmailClient

            self._client = WebmailClient()
        return self._client.__enter__()

    def __exit__(self, *args: object) -> None:
        self._client.__exit__(*args)
