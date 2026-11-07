"""OAuth 2.1 authorization server whose login step is a SeoulTech webmail sign-in."""

from __future__ import annotations

import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .auth_store import AuthStore

SCOPE = "mail.read"
PENDING_TTL = 600
CODE_TTL = 300
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 24 * 3600


class SeoulTechOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self, store: AuthStore, public_url: str) -> None:
        self.store = store
        self.public_url = public_url.rstrip("/")

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = self.store.get("client", client_id)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        # ponytail: confidential client secrets stored as-is (SDK compares raw); hash if non-public clients matter.
        self.store.put("client", client_info.client_id, client_info.model_dump(mode="json", exclude_none=True))

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        self.store.purge_expired()  # ponytail: cleanup rides on sign-in traffic; add a timer if traffic is too sparse.
        request_id = secrets.token_urlsafe(32)
        self.store.put(
            "pending", request_id, {"client_id": client.client_id, "params": params.model_dump(mode="json")}, ttl=PENDING_TTL
        )
        return f"{self.public_url}/login?request={request_id}"

    def pending(self, request_id: str) -> dict | None:
        return self.store.get("pending", request_id)

    def complete_login(self, request_id: str, email: str) -> str:
        """Called after the webmail sign-in succeeds; returns the client redirect carrying the code."""
        pending = self.store.pop("pending", request_id)
        if pending is None:
            raise AuthorizeError("access_denied", "로그인 요청이 만료되었습니다. 다시 연결하세요.")
        params = AuthorizationParams.model_validate(pending["params"])
        code = secrets.token_urlsafe(32)
        self.store.put(
            "code",
            code,
            {
                "client_id": pending["client_id"],
                "scopes": params.scopes or [SCOPE],
                "expires_at": time.time() + CODE_TTL,
                "code_challenge": params.code_challenge,
                "redirect_uri": str(params.redirect_uri),
                "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
                "resource": params.resource or f"{self.public_url}/mcp",
                "subject": email,
            },
            ttl=CODE_TTL,
        )
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> AuthorizationCode | None:
        data = self.store.get("code", authorization_code)
        if data is None or data["client_id"] != client.client_id:
            return None
        return AuthorizationCode(code=authorization_code, **data)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        if self.store.pop("code", authorization_code.code) is None:
            raise TokenError("invalid_grant", "인가 정보가 이미 사용되었거나 만료되었습니다.")
        return self._issue(client.client_id, authorization_code.scopes, authorization_code.subject, authorization_code.resource)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        data = self.store.get("refresh", refresh_token)
        if data is None or data["client_id"] != client.client_id:
            return None
        return RefreshToken(token=refresh_token, **_token_fields(data))

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        data = self.store.get("refresh", refresh_token.token)
        if data is None:
            raise TokenError("invalid_grant", "인가 정보가 이미 사용되었거나 만료되었습니다.")
        self.store.delete_grant(data["grant"])  # Rotate: old access and refresh tokens stop working.
        return self._issue(client.client_id, scopes or refresh_token.scopes, refresh_token.subject, refresh_token.resource)

    async def load_access_token(self, token: str) -> AccessToken | None:
        data = self.store.get("access", token)
        return AccessToken(token=token, **_token_fields(data)) if data else None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        kind = "refresh" if isinstance(token, RefreshToken) else "access"
        data = self.store.get(kind, token.token)
        if data is not None:
            self.store.delete_grant(data["grant"])
            self.store.purge_expired()  # Last grant revoked: the stored password goes too.

    def _issue(self, client_id: str, scopes: list[str], subject: str | None, resource: str | None) -> OAuthToken:
        grant = secrets.token_urlsafe(16)
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = int(time.time())
        common = {"grant": grant, "client_id": client_id, "scopes": scopes, "subject": subject, "resource": resource}
        self.store.put("access", access, {**common, "expires_at": now + ACCESS_TTL}, ttl=ACCESS_TTL)
        self.store.put("refresh", refresh, {**common, "expires_at": now + REFRESH_TTL}, ttl=REFRESH_TTL)
        return OAuthToken(access_token=access, expires_in=ACCESS_TTL, scope=" ".join(scopes), refresh_token=refresh)


def _token_fields(data: dict) -> dict:
    return {key: data[key] for key in ("client_id", "scopes", "expires_at", "resource", "subject")}

