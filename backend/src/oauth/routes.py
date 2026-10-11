"""OAuth sign-in routes: /oauth/login, /oauth/callback, /oauth/me, /oauth/logout.

CSRF: /login stores a random `state` server-side and in an HttpOnly cookie on
the browser. /callback accepts it only if the query's state equals that cookie
and is one we issued and haven't used, so a forged callback can't log a victim
into an attacker's account. PKCE (S256) binds the code to this login, so an
intercepted code is useless without the verifier.

`current_user` is the dependency other routes use to require a signed-in user.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from oauth.provider import HttpProvider, OAuthSettings, Provider, pkce_challenge
from oauth.sessions import LOGIN_TTL, SESSION_TTL, SessionStore, store_from_env

STATE_COOKIE = "oauth_state"
SESSION_COOKIE = "session"

log = logging.getLogger(__name__)
router = APIRouter(prefix="/oauth", tags=["oauth"])
_store: SessionStore | None = None


def get_settings() -> OAuthSettings:
    return OAuthSettings.from_env()


def get_store() -> SessionStore:
    """Created on first use, after the API has loaded backend/.env (`OAUTH_SESSION_STORE`)."""
    global _store
    if _store is None:
        _store = store_from_env()
    return _store


def get_provider(settings: OAuthSettings = Depends(get_settings)) -> Provider:
    return HttpProvider(settings)


def current_user(request: Request, store: SessionStore = Depends(get_store)) -> dict[str, Any]:
    session_id = request.cookies.get(SESSION_COOKIE)
    user = store.get_session(session_id) if session_id else None
    if user is None:
        raise HTTPException(401, "Not signed in")
    return user


def _same(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode(), b.encode())


@router.get("/login")
def login(
    settings: OAuthSettings = Depends(get_settings), store: SessionStore = Depends(get_store)
) -> RedirectResponse:
    if not settings.configured:
        raise HTTPException(503, "OAuth is not configured: set OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET")
    state, verifier = store.begin_login()
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.client_id,
            "redirect_uri": settings.redirect_uri,
            "scope": settings.scopes,
            "state": state,
            "code_challenge": pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    response = RedirectResponse(f"{settings.authorize_url}?{query}", status_code=302)
    response.set_cookie(
        STATE_COOKIE, state, max_age=int(LOGIN_TTL.total_seconds()), path="/oauth",
        httponly=True, secure=settings.cookie_secure, samesite="lax",
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    settings: OAuthSettings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
    provider: Provider = Depends(get_provider),
) -> Response:
    if error:
        raise HTTPException(400, f"Sign-in was not completed: {error}")
    cookie_state = request.cookies.get(STATE_COOKIE)
    if not state or not cookie_state or not _same(state, cookie_state):
        raise HTTPException(400, "Invalid OAuth state")
    verifier = store.finish_login(state)
    if verifier is None:
        raise HTTPException(400, "Login expired or already used; start again at /oauth/login")
    if not code:
        raise HTTPException(400, "Missing authorization code")
    try:
        tokens = await provider.exchange_code(code, verifier)
        profile = await provider.userinfo(tokens["access_token"])
        user = {"sub": profile["sub"], "email": profile.get("email"), "name": profile.get("name")}
    except (httpx.HTTPError, KeyError, TypeError) as exc:
        log.warning("OAuth callback failed: %s", type(exc).__name__)  # never log tokens
        raise HTTPException(502, "Could not complete sign-in with the provider") from None
    # The provider's tokens go out of scope here; only the session id is kept.

    session_id = store.create_session(user)
    response: Response = (
        RedirectResponse(settings.post_login_redirect, status_code=303)
        if settings.post_login_redirect
        else JSONResponse({"user": user})
    )
    response.set_cookie(
        SESSION_COOKIE, session_id, max_age=int(SESSION_TTL.total_seconds()), path="/",
        httponly=True, secure=settings.cookie_secure, samesite="lax",
    )
    response.delete_cookie(STATE_COOKIE, path="/oauth")
    return response


@router.get("/me")
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"user": user}


@router.post("/logout")
def logout(request: Request, store: SessionStore = Depends(get_store)) -> JSONResponse:
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        store.end_session(session_id)
    response = JSONResponse({"signed_out": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
