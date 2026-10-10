"""OAuth settings and the two HTTP calls the login flow makes.

Provider: Google, as an OpenID Connect sign-in using the Authorization Code
flow with PKCE. Scopes: `openid email profile`, identity only. The API never
calls Google for the user, so it asks for nothing more.

Every endpoint is an environment variable, so another OIDC provider (Microsoft,
Auth0, Okta) is a config change. Secrets come from the environment only.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
DEFAULT_SCOPES = "openid email profile"
DEFAULT_REDIRECT_URI = "http://localhost:8000/oauth/callback"
TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class OAuthSettings:
    client_id: str | None
    client_secret: str | None
    redirect_uri: str = DEFAULT_REDIRECT_URI
    authorize_url: str = GOOGLE_AUTHORIZE_URL
    token_url: str = GOOGLE_TOKEN_URL
    userinfo_url: str = GOOGLE_USERINFO_URL
    scopes: str = DEFAULT_SCOPES
    cookie_secure: bool = True  # set OAUTH_COOKIE_SECURE=false only for plain-http local testing
    post_login_redirect: str | None = None  # where the browser goes after signing in

    @classmethod
    def from_env(cls) -> OAuthSettings:
        return cls(
            client_id=os.getenv("OAUTH_CLIENT_ID") or None,
            client_secret=os.getenv("OAUTH_CLIENT_SECRET") or None,
            redirect_uri=os.getenv("OAUTH_REDIRECT_URI") or DEFAULT_REDIRECT_URI,
            authorize_url=os.getenv("OAUTH_AUTHORIZE_URL") or GOOGLE_AUTHORIZE_URL,
            token_url=os.getenv("OAUTH_TOKEN_URL") or GOOGLE_TOKEN_URL,
            userinfo_url=os.getenv("OAUTH_USERINFO_URL") or GOOGLE_USERINFO_URL,
            scopes=os.getenv("OAUTH_SCOPES") or DEFAULT_SCOPES,
            cookie_secure=(os.getenv("OAUTH_COOKIE_SECURE") or "true").lower() != "false",
            post_login_redirect=os.getenv("OAUTH_POST_LOGIN_REDIRECT") or None,
        )

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


def pkce_challenge(verifier: str) -> str:
    """S256 code challenge: base64url(sha256(verifier)) without padding (RFC 7636)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class Provider(Protocol):
    async def exchange_code(self, code: str, verifier: str) -> dict[str, Any]:
        """Token response for an authorization code; must include `access_token`."""
        ...

    async def userinfo(self, access_token: str) -> dict[str, Any]:
        """The OIDC profile; must include `sub`."""
        ...


class HttpProvider:
    def __init__(self, settings: OAuthSettings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport  # tests pass an httpx.MockTransport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=self._transport)

    async def exchange_code(self, code: str, verifier: str) -> dict[str, Any]:
        s = self._settings
        async with self._client() as client:
            response = await client.post(
                s.token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": s.redirect_uri,
                    "client_id": s.client_id,
                    "client_secret": s.client_secret,
                    "code_verifier": verifier,
                },
            )
        response.raise_for_status()
        return response.json()

    async def userinfo(self, access_token: str) -> dict[str, Any]:
        async with self._client() as client:
            response = await client.get(
                self._settings.userinfo_url, headers={"Authorization": f"Bearer {access_token}"}
            )
        response.raise_for_status()
        return response.json()
