"""Read-only adapter for the current SeoulTech Mailplug webmail UI."""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .mail import MAX_SEARCH_RESULTS, MailError, SEOUL, _HTMLText, settings


BASE = "https://mail.seoultech.ac.kr"
PAGE_SIZE = 100


def _address(recipient: Any) -> str:
    if not isinstance(recipient, dict):
        return ""
    name = str(recipient.get("displayName") or "").strip()
    email = str(recipient.get("emailAddress") or "").strip()
    return f"{name} <{email}>" if name and email else name or email


def _received(row: dict[str, Any]) -> datetime:
    raw = row.get("receivedDateTime")
    if not isinstance(raw, str):
        raise MailError("웹메일 응답에 수신 시각이 없습니다.")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MailError("웹메일 수신 시각을 해석할 수 없습니다.") from exc
    if parsed.tzinfo is None:
        raise MailError("웹메일 수신 시각에 시간대가 없습니다.")
    return parsed.astimezone(SEOUL)


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    identifier = row.get("messageId")
    if not isinstance(identifier, int):
        raise MailError("웹메일 응답에 메일 ID가 없습니다.")
    recipients = row.get("toRecipients")
    to = ", ".join(_address(item) for item in recipients) if isinstance(recipients, list) else _address(row.get("toRecipient"))
    return {
        "uid": identifier,  # Public tool field retained for compatibility; this is a webmail message ID.
        "subject": str(row.get("subject") or ""),
        "sender": _address(row.get("fromRecipient")),
        "to": to,
        "received_at": _received(row).isoformat(),
        "header_date": str(row.get("receivedDateTime") or ""),
        "message_id": "",
        "unread": row.get("messageFlag") == "N",
        "size_bytes": int(row.get("mailSize") or 0),
    }


def _body_text(value: Any) -> str:
    body = str(value or "")
    if not re.search(r"<(?:html|body|div|p|br|span|table|a|style|script)\b", body, re.I):
        return body.strip()
    parser = _HTMLText()
    parser.feed(body)
    return parser.text()


class WebmailClient:
    backend = "webmail"

    def __enter__(self) -> WebmailClient:
        self.username, password = settings()
        self._playwright = None
        self._browser = None
        self._context = None
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                channel=os.environ.get("SEOULTECH_BROWSER_CHANNEL", "chrome"), headless=True
            )
            page = self._browser.new_page()
            self._context = page.context
            page.goto(f"{BASE}/member/login", wait_until="domcontentloaded", timeout=30_000)
            page.get_by_role("textbox", name="아이디 입력").fill(self.username.split("@")[0])
            page.get_by_role("textbox", name="비밀번호 입력").fill(password)
            page.get_by_role("button", name="로그인").click()
            page.get_by_role("link", name=re.compile("받은 메일함")).first.wait_for(timeout=30_000)
            mailboxes = self._get_json("/api/v2/mail/mailboxes?mailStats=false&limit=0")
            inbox = next((item for item in mailboxes.get("value", []) if item.get("type") == 2), None)
            if inbox is None or not isinstance(inbox.get("mailboxId"), int):
                raise MailError("웹메일에서 받은편지함 ID를 찾지 못했습니다.")
            self._mailbox_id = inbox["mailboxId"]
            return self
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            self.__exit__()
            raise MailError("웹메일 브라우저 연결 또는 로그인에 실패했습니다. Chrome 설치와 계정 정보를 확인하세요.") from exc
        except Exception:
            self.__exit__()
            raise

    def __exit__(self, *_: object) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def _get_json(self, path: str) -> dict[str, Any]:
        try:
            response = self._context.request.get(BASE + path, timeout=20_000)
        except PlaywrightError as exc:
            raise MailError("웹메일 조회 요청에 실패했습니다.") from exc
        if not response.ok:
            raise MailError(f"웹메일 조회가 거부되었습니다 (HTTP {response.status}). 다시 로그인하거나 학교 메일 서비스 상태를 확인하세요.")
        try:
            data = response.json()
        except ValueError as exc:
            raise MailError("웹메일 응답이 JSON 형식이 아닙니다.") from exc
        if not isinstance(data, dict):
            raise MailError("웹메일 응답 형식이 바뀌었습니다.")
        return data

    def list_messages(self, day: date, limit: int = 100, unread_only: bool = False) -> dict[str, Any]:
        if not 1 <= limit <= 500:
            raise MailError("limit은 1~500 사이여야 합니다.")
        messages: list[dict[str, Any]] = []
        offset = 0
        while offset < MAX_SEARCH_RESULTS:
            path = f"/api/v2/mail/mailboxes/{self._mailbox_id}/messages?limit={PAGE_SIZE}&offset={offset}"
            data = self._get_json(path)
            rows = data.get("value")
            if not isinstance(rows, list):
                raise MailError("웹메일 목록 응답 형식이 바뀌었습니다.")
            if not rows:
                break
            for row in rows:
                received_day = _received(row).date()
                if received_day == day and (not unread_only or row.get("messageFlag") == "N"):
                    messages.append(_metadata(row))
            offset += len(rows)
            # The inbox API returns newest first; a page older than the target day completes the search.
            if _received(rows[-1]).date() < day or offset >= int(data.get("total") or 0):
                break
        if offset >= MAX_SEARCH_RESULTS and rows and _received(rows[-1]).date() >= day:
            raise MailError(f"검색 결과가 {MAX_SEARCH_RESULTS}건을 넘습니다. 조회 한도를 늘려야 합니다.")
        messages.sort(key=lambda item: (item["received_at"], item["uid"]), reverse=True)
        return {
            "date": day.isoformat(),
            "timezone": "Asia/Seoul",
            "backend": self.backend,
            "total": len(messages),
            "unread": sum(message["unread"] for message in messages),
            "truncated": len(messages) > limit,
            "messages": messages[:limit],
        }

    def get_message(self, uid: int, max_chars: int = 12_000) -> dict[str, Any]:
        if uid < 1:
            raise MailError("메일 ID는 양의 정수여야 합니다.")
        if not 500 <= max_chars <= 50_000:
            raise MailError("max_chars는 500~50000 사이여야 합니다.")
        data = self._get_json(f"/api/v2/mail/mailboxes/{self._mailbox_id}/messages/{uid}")
        if data.get("messageId") != uid:
            raise MailError("웹메일이 다른 메일 ID를 반환했습니다.")
        body = _body_text(data.get("body") or data.get("mailPreview"))
        return {
            **_metadata(data),
            "body": body[:max_chars],
            "body_truncated": len(body) > max_chars,
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
