"""SeoulTech webmail sign-in page that completes the OAuth /authorize step."""

from __future__ import annotations

from collections.abc import Callable
from html import escape

import math
import time

import anyio.to_thread
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from .mail import MailClient, MailError, normalize_email
from .oauth import SeoulTechOAuthProvider

MAX_ATTEMPTS = 5
# Failed sign-ins across all login requests, so new /authorize requests cannot reset the count.
RATE_WINDOW = 15 * 60
MAX_FAILURES_PER_IP = 10
MAX_FAILURES_PER_ACCOUNT = 5


def _retry_after(store, key: str, limit: int) -> int:
    """Seconds until `key` may try again; 0 when under the limit."""
    entry = store.get("ratelimit", key)
    if entry is None or entry["count"] < limit:
        return 0
    return max(1, math.ceil(entry["reset_at"] - time.time()))


def _record_failure(store, key: str) -> None:
    entry = store.get("ratelimit", key) or {"count": 0, "reset_at": time.time() + RATE_WINDOW}
    entry["count"] += 1
    store.put("ratelimit", key, entry, ttl=max(1, entry["reset_at"] - time.time()))


def verify_webmail_login(email: str, password: str) -> bool:
    try:
        with MailClient((email, password)):
            return True
    except MailError:
        return False


def _page(request_id: str, error: str = "", status: int = 200, headers: dict | None = None) -> HTMLResponse:
    message = f'<p class="error" role="alert">{escape(error)}</p>' if error else ""
    return HTMLResponse(
        f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SeoulTech Mail 연결</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:360px;margin:12vh auto;padding:0 16px;color:#1d1d1f}}
label{{display:block;margin-top:12px;font-size:14px}}
input{{width:100%;box-sizing:border-box;padding:10px;margin-top:4px;font-size:16px}}
button{{width:100%;margin-top:20px;padding:12px;font-size:16px;cursor:pointer}}
.error{{color:#b00020}} small{{color:#666}}
</style></head><body>
<h1>SeoulTech Mail 연결</h1>
<p>서울과학기술대학교 웹메일 계정으로 로그인하면 AI 앱이 받은편지함을 <strong>읽기 전용</strong>으로 조회합니다.</p>
{message}
<form method="post" action="/login">
<input type="hidden" name="request" value="{escape(request_id)}">
<label for="username">아이디 또는 학교 이메일</label>
<input id="username" name="username" autocomplete="username" required>
<label for="password">비밀번호</label>
<input id="password" name="password" type="password" autocomplete="current-password" required>
<button type="submit">로그인하고 연결</button>
</form>
<p><small>비밀번호는 메일 조회를 위해 서버에 암호화되어 저장됩니다.</small></p>
</body></html>""",
        status_code=status,
        headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", **(headers or {})},
    )


def _expired() -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'><p>로그인 요청이 만료되었습니다. AI 앱에서 다시 연결하세요.</p>",
        status_code=400,
        headers={"Cache-Control": "no-store"},
    )


def make_login_handler(
    provider: SeoulTechOAuthProvider, verify: Callable[[str, str], bool] = verify_webmail_login
) -> Callable[[Request], object]:
    async def login(request: Request) -> Response:
        if request.method == "GET":
            request_id = request.query_params.get("request", "")
            return _page(request_id) if provider.pending(request_id) else _expired()

        form = await request.form()
        request_id = str(form.get("request", ""))
        username, password = str(form.get("username", "")).strip(), str(form.get("password", ""))
        pending = provider.pending(request_id)
        if pending is None:
            return _expired()
        if not username or not password:
            return _page(request_id, "아이디와 비밀번호를 입력하세요.", 400)

        email = normalize_email(username)
        store = provider.store
        ip_key, account_key = f"ip:{request.client.host if request.client else 'unknown'}", f"account:{email.lower()}"
        wait = max(_retry_after(store, ip_key, MAX_FAILURES_PER_IP), _retry_after(store, account_key, MAX_FAILURES_PER_ACCOUNT))
        if wait:
            minutes = math.ceil(wait / 60)
            return _page(
                request_id, f"로그인 실패가 너무 많습니다. {minutes}분 후 다시 시도하세요.", 429, {"Retry-After": str(wait)}
            )

        # Playwright sync API cannot run inside the event loop.
        if not await anyio.to_thread.run_sync(verify, email, password):
            _record_failure(store, ip_key)
            _record_failure(store, account_key)
            attempts = pending.get("attempts", 0) + 1
            if attempts >= MAX_ATTEMPTS:
                provider.store.delete("pending", request_id)
                return _expired()
            provider.store.put("pending", request_id, {**pending, "attempts": attempts}, ttl=600)
            return _page(request_id, f"로그인에 실패했습니다. ({attempts}/{MAX_ATTEMPTS})", 401)

        store.delete("ratelimit", account_key)
        store.set_password(email, password)
        return RedirectResponse(provider.complete_login(request_id, email), status_code=302)

    return login
