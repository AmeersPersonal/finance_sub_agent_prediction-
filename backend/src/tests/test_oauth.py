"""OAuth routes against a fake provider: no network, no real credentials."""

import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from oauth import routes
from oauth.provider import HttpProvider, OAuthSettings, pkce_challenge
from oauth.sessions import MemoryStore, store_from_env

SETTINGS = OAuthSettings(
    client_id="client-id",
    client_secret="client-secret",
    redirect_uri="http://testserver/oauth/callback",
    authorize_url="https://idp.example/authorize",
    cookie_secure=False,  # TestClient talks plain http
)


class FakeProvider:
    def __init__(self, fail: Exception | None = None):
        self.exchanged: list[tuple[str, str]] = []
        self.fail = fail

    async def exchange_code(self, code, verifier):
        self.exchanged.append((code, verifier))
        if self.fail:
            raise self.fail
        return {"access_token": "access-token", "id_token": "ignored"}

    async def userinfo(self, access_token):
        assert access_token == "access-token"
        return {"sub": "user-1", "email": "user@example.com", "name": "User One"}


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


@pytest.fixture
def env():
    clock, provider = Clock(), FakeProvider()
    store = MemoryStore(clock=clock)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_settings] = lambda: SETTINGS
    app.dependency_overrides[routes.get_store] = lambda: store
    app.dependency_overrides[routes.get_provider] = lambda: provider
    return TestClient(app, follow_redirects=False), app, provider, clock


def start_login(client) -> dict:
    response = client.get("/oauth/login")
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == SETTINGS.authorize_url
    return {k: v[0] for k, v in parse_qs(location.query).items()}


def test_login_redirects_with_state_pkce_and_scopes(env):
    client, *_ = env
    query = start_login(client)
    assert query["response_type"] == "code" and query["client_id"] == "client-id"
    assert query["scope"] == "openid email profile"
    assert query["code_challenge_method"] == "S256" and len(query["code_challenge"]) == 43
    assert client.cookies["oauth_state"] == query["state"]


def test_full_sign_in_creates_a_session(env):
    client, _, provider, _ = env
    query = start_login(client)
    response = client.get("/oauth/callback", params={"code": "the-code", "state": query["state"]})
    assert response.status_code == 200
    assert response.json() == {"user": {"sub": "user-1", "email": "user@example.com", "name": "User One"}}
    [(code, verifier)] = provider.exchanged
    assert code == "the-code" and pkce_challenge(verifier) == query["code_challenge"]
    assert "access-token" not in response.text and "access-token" not in str(client.cookies)
    assert client.get("/oauth/me").json()["user"]["email"] == "user@example.com"

    assert client.post("/oauth/logout").json() == {"signed_out": True}
    assert client.get("/oauth/me").status_code == 401


def test_callback_rejects_a_state_that_does_not_match_the_cookie(env):
    client, _, provider, _ = env
    start_login(client)
    response = client.get("/oauth/callback", params={"code": "c", "state": "forged"})
    assert response.status_code == 400 and response.json()["detail"] == "Invalid OAuth state"
    assert provider.exchanged == []


def test_callback_rejects_a_browser_that_never_started_the_login(env):
    client, app, provider, _ = env
    query = start_login(client)
    victim = TestClient(app, follow_redirects=False)  # attacker's link opened in another browser
    response = victim.get("/oauth/callback", params={"code": "c", "state": query["state"]})
    assert response.status_code == 400 and provider.exchanged == []


def test_state_works_once(env):
    client, *_ = env
    query = start_login(client)
    client.cookies.set("oauth_state", query["state"], path="/oauth")
    assert client.get("/oauth/callback", params={"code": "c", "state": query["state"]}).status_code == 200
    client.cookies.set("oauth_state", query["state"], path="/oauth")  # replay
    replay = client.get("/oauth/callback", params={"code": "c", "state": query["state"]})
    assert replay.status_code == 400 and "already used" in replay.json()["detail"]


def test_login_expires(env):
    client, _, _, clock = env
    query = start_login(client)
    clock.now += timedelta(minutes=11)
    response = client.get("/oauth/callback", params={"code": "c", "state": query["state"]})
    assert response.status_code == 400


def test_sessions_expire(env):
    client, _, _, clock = env
    query = start_login(client)
    client.get("/oauth/callback", params={"code": "c", "state": query["state"]})
    clock.now += timedelta(hours=9)
    assert client.get("/oauth/me").status_code == 401


def test_provider_errors_are_reported_without_detail(env):
    client, _, provider, _ = env
    provider.fail = httpx.HTTPStatusError(
        "bad", request=httpx.Request("POST", "https://idp.example/token"),
        response=httpx.Response(400),
    )
    query = start_login(client)
    response = client.get("/oauth/callback", params={"code": "c", "state": query["state"]})
    assert response.status_code == 502


def test_denied_consent_and_missing_code(env):
    client, *_ = env
    assert client.get("/oauth/callback", params={"error": "access_denied"}).status_code == 400
    query = start_login(client)
    response = client.get("/oauth/callback", params={"state": query["state"]})
    assert response.status_code == 400 and response.json()["detail"] == "Missing authorization code"


def test_post_login_redirect(env):
    client, app, *_ = env
    app.dependency_overrides[routes.get_settings] = lambda: OAuthSettings(
        **{**SETTINGS.__dict__, "post_login_redirect": "http://localhost:3000/"}
    )
    query = start_login(client)
    response = client.get("/oauth/callback", params={"code": "c", "state": query["state"]})
    assert response.status_code == 303 and response.headers["location"] == "http://localhost:3000/"
    assert "session" in client.cookies


def test_unconfigured_login_says_so(env):
    client, app, *_ = env
    app.dependency_overrides[routes.get_settings] = lambda: OAuthSettings(None, None)
    response = client.get("/oauth/login")
    assert response.status_code == 503 and "OAUTH_CLIENT_ID" in response.json()["detail"]


def test_settings_come_from_the_environment(monkeypatch):
    for name in ("OAUTH_CLIENT_ID", "OAUTH_CLIENT_SECRET", "OAUTH_COOKIE_SECURE", "OAUTH_SCOPES",
                 "OAUTH_AUTHORIZE_URL", "OAUTH_REDIRECT_URI", "OAUTH_POST_LOGIN_REDIRECT"):
        monkeypatch.delenv(name, raising=False)
    defaults = OAuthSettings.from_env()
    assert not defaults.configured and defaults.cookie_secure
    assert defaults.authorize_url.startswith("https://accounts.google.com/")
    monkeypatch.setenv("OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OAUTH_COOKIE_SECURE", "false")
    configured = OAuthSettings.from_env()
    assert configured.configured and not configured.cookie_secure


# --- HttpProvider against recorded responses (MockTransport, no network) ----------


def recorded_provider(responses):
    requests = []

    def handle(request):
        requests.append(request)
        status, body = responses[str(request.url).split("?")[0]]
        return httpx.Response(status, json=body)

    settings = OAuthSettings(client_id="client-id", client_secret="client-secret",
                             token_url="https://idp.example/token", userinfo_url="https://idp.example/userinfo")
    return HttpProvider(settings, transport=httpx.MockTransport(handle)), requests


def test_http_provider_exchanges_the_code_with_the_pkce_verifier():
    provider, requests = recorded_provider({
        "https://idp.example/token": (200, {"access_token": "access-token", "token_type": "Bearer"}),
        "https://idp.example/userinfo": (200, {"sub": "user-1", "email": "user@example.com"}),
    })
    tokens = asyncio.run(provider.exchange_code("the-code", "the-verifier"))
    profile = asyncio.run(provider.userinfo(tokens["access_token"]))
    assert profile["sub"] == "user-1"
    form = {k: v[0] for k, v in parse_qs(requests[0].content.decode()).items()}
    assert requests[0].method == "POST" and form == {
        "grant_type": "authorization_code", "code": "the-code", "code_verifier": "the-verifier",
        "redirect_uri": "http://localhost:8000/oauth/callback",
        "client_id": "client-id", "client_secret": "client-secret",
    }
    assert requests[1].headers["authorization"] == "Bearer access-token"


def test_http_provider_raises_on_provider_errors():
    provider, _ = recorded_provider({"https://idp.example/token": (400, {"error": "invalid_grant"})})
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(provider.exchange_code("expired-code", "verifier"))


def test_session_store_is_chosen_by_environment(monkeypatch):
    monkeypatch.delenv("OAUTH_SESSION_STORE", raising=False)
    assert isinstance(store_from_env(), MemoryStore)
    monkeypatch.setenv("OAUTH_SESSION_STORE", "database")
    assert type(store_from_env()).__name__ == "DatabaseStore"  # connects lazily, on first use
    monkeypatch.setenv("OAUTH_SESSION_STORE", "files")
    with pytest.raises(RuntimeError, match="OAUTH_SESSION_STORE"):
        store_from_env()
