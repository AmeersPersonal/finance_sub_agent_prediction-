"""Who may spend forecasts, how often, background jobs, the score cache and account
preferences. Fake service, fake LLM and an in-memory session store: no network."""

import time
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import main
from api.state import JobStore, RateLimiter, ScoreCache
from oauth.provider import OAuthSettings
from oauth.routes import SESSION_COOKIE, get_settings, get_store
from oauth.sessions import MemoryStore

SETTINGS = OAuthSettings(client_id="id", client_secret="secret",
                         userinfo_url="https://idp.example/userinfo", cookie_secure=False)
USER = {"sub": "user-1", "email": "user@example.com", "name": "User One"}


@pytest.fixture(autouse=True)
def fresh_api_state(monkeypatch):
    for state in (main.prediction_limiter, main.jobs, main.score_cache):
        state.clear()
    # backend/.env is loaded when api.main is imported; pin the settings these tests rely on.
    monkeypatch.setenv("API_REQUIRE_SIGN_IN", "true")
    monkeypatch.delenv("LIVE_FEED", raising=False)
    yield
    for state in (main.prediction_limiter, main.jobs, main.score_cache):
        state.clear()
    main.app.dependency_overrides = {}


@pytest.fixture
def env(monkeypatch, fake_llm):
    """(client, store, service calls). The service records calls and returns a forecast."""
    store, calls = MemoryStore(), []

    async def service(method, *args, **kwargs):
        calls.append((method, args, kwargs))
        return {"id": "p-1", "ticker": args[0], "direction": "up"}

    monkeypatch.setattr(main, "_service", service)
    main.app.dependency_overrides = {
        main.get_llm: lambda: fake_llm, get_store: lambda: store, get_settings: lambda: SETTINGS,
    }
    with TestClient(main.app) as client:
        yield client, store, calls


def sign_in(client, store, user=USER) -> None:
    client.cookies.set(SESSION_COOKIE, store.create_session(user))


# --- sign-in on forecasts --------------------------------------------------------


def test_forecasts_need_a_signed_in_user_by_default(env):
    client, store, calls = env
    assert client.post("/predictions", json={"ticker": "AAPL"}).status_code == 401
    assert client.post("/prediction-jobs", json={"ticker": "AAPL"}).status_code == 401
    assert calls == []
    sign_in(client, store)
    assert client.post("/predictions", json={"ticker": "AAPL"}).status_code == 201
    assert calls[0][0] == "predict_and_store"


def test_sign_in_can_be_turned_off_for_local_development(env, monkeypatch):
    client, _, calls = env
    monkeypatch.setenv("API_REQUIRE_SIGN_IN", "false")
    assert client.post("/predictions", json={"ticker": "AAPL"}).status_code == 201
    assert len(calls) == 1


def test_reads_stay_open(env, monkeypatch):
    client, *_ = env
    monkeypatch.setattr(main, "_read", lambda *a, **k: [])
    assert client.get("/predictions").status_code == 200
    assert client.get("/stocks/AAPL/history").status_code == 200


# --- rate limit -------------------------------------------------------------------


def test_forecasts_are_rate_limited_per_user(env, monkeypatch):
    client, store, calls = env
    monkeypatch.setattr(main, "prediction_limiter", RateLimiter(2))
    sign_in(client, store)
    assert [client.post("/predictions", json={"ticker": "AAPL"}).status_code for _ in range(2)] == [201, 201]
    limited = client.post("/predictions", json={"ticker": "AAPL"})
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
    assert "2 an hour" in limited.json()["detail"]
    assert client.post("/prediction-jobs", json={"ticker": "AAPL"}).status_code == 429  # one shared quota
    sign_in(client, store, {**USER, "sub": "user-2"})  # someone else has their own quota
    assert client.post("/predictions", json={"ticker": "AAPL"}).status_code == 201
    assert len(calls) == 3


def test_rejected_requests_do_not_spend_quota(env, monkeypatch):
    client, store, _ = env
    monkeypatch.setattr(main, "prediction_limiter", RateLimiter(1))
    sign_in(client, store)
    assert client.post("/predictions", json={"ticker": "AAPL", "horizon_days": 0}).status_code == 422
    monkeypatch.setenv("LIVE_FEED", "finnhub")
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    misconfigured = client.post("/predictions", json={"ticker": "AAPL", "live": True})
    assert misconfigured.status_code == 503 and "LIVE_FEED" in misconfigured.json()["detail"]
    assert client.post("/predictions", json={"ticker": "AAPL"}).status_code == 201


def test_rate_limiter_window_slides():
    now = [0.0]
    limiter = RateLimiter(2, window=60, clock=lambda: now[0])
    assert limiter.acquire("a") is None and limiter.acquire("a") is None
    assert limiter.acquire("a") == pytest.approx(60)
    now[0] = 30
    assert limiter.acquire("a") == pytest.approx(30)
    now[0] = 61
    assert limiter.acquire("a") is None
    assert RateLimiter(0).acquire("a") is None  # 0 turns it off


# --- background jobs --------------------------------------------------------------


def wait_for(client, url, done=("succeeded", "failed")):
    for _ in range(100):
        body = client.get(url).json()
        if body["status"] in done:
            return body
        time.sleep(0.01)
    pytest.fail(f"job never finished: {body}")


def test_prediction_job_runs_in_the_background(env):
    client, store, calls = env
    sign_in(client, store)
    started = client.post("/prediction-jobs", json={"ticker": "nvda", "horizon_days": 3})
    assert started.status_code == 202
    job = started.json()
    assert job["status"] in ("queued", "running", "succeeded") and job["poll"] == f"/prediction-jobs/{job['job_id']}"
    finished = wait_for(client, job["poll"])
    assert finished["status"] == "succeeded" and finished["prediction_id"] == "p-1"
    assert finished["prediction"]["ticker"] == "NVDA" and finished["error"] is None
    assert calls[0][2]["horizon_days"] == 3
    # Another user can't see it, and unknown ids are 404 too.
    sign_in(client, store, {**USER, "sub": "user-2"})
    assert client.get(job["poll"]).status_code == 404
    assert client.get("/prediction-jobs/unknown").status_code == 404


@pytest.mark.parametrize("error, status, words", [
    (HTTPException(422, "No eligible personas for those strategies and age bands."), 422, "No eligible"),
    (RuntimeError("provider secret detail"), 500, "Try again later"),
])
def test_failed_jobs_report_a_safe_error(env, monkeypatch, error, status, words):
    client, store, _ = env

    async def failing(*args, **kwargs):
        raise error

    monkeypatch.setattr(main, "_service", failing)
    sign_in(client, store)
    job = client.post("/prediction-jobs", json={"ticker": "AAPL"}).json()
    finished = wait_for(client, job["poll"])
    assert finished["status"] == "failed" and finished["error"]["status_code"] == status
    assert words in finished["error"]["detail"] and "secret" not in str(finished)


def test_job_store_caps_running_jobs():
    import asyncio

    async def scenario():
        store = JobStore(max_active=1)
        gate = asyncio.Event()
        store.submit("a", gate.wait)
        with pytest.raises(HTTPException) as busy:
            store.submit("a", gate.wait)
        gate.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return busy.value.status_code, store.submit("a", gate.wait).status

    assert asyncio.run(scenario()) == (503, "queued")


# --- score cache ------------------------------------------------------------------


def test_score_report_is_cached_until_refreshed(env, monkeypatch):
    from ai.evaluation import Report
    from database import service

    client, *_ = env
    computed = []

    def score_database():
        computed.append(1)
        return Report(scored=0, pending=0, unreadable=0, accuracy={"personas": None}, coverage=None,
                      accuracy_when_called=None, by_confidence={}, by_strategy={}, by_age_band={})

    monkeypatch.setattr(service, "score_database", score_database)
    first = client.get("/score").json()
    client.get("/score/charts")
    assert len(computed) == 1 and "computed_at" in first
    client.get("/score?refresh=true")
    assert len(computed) == 2
    monkeypatch.setattr(main, "_read", lambda *a, **k: {"id": "x"})
    client.post("/predictions/0123456789abcdef0123456789abcdef/evaluate")  # a new outcome clears it
    client.get("/score")
    assert len(computed) == 3


def test_score_cache_expires():
    now = [0.0]
    cache, values = ScoreCache(ttl=10, clock=lambda: now[0]), iter([1, 2, 3])
    assert cache.get(lambda: next(values))[0] == 1
    now[0] = 9
    assert cache.get(lambda: next(values))[0] == 1
    now[0] = 11
    assert cache.get(lambda: next(values))[0] == 2
    assert ScoreCache(ttl=0).get(lambda: 5)[0] == 5


# --- account preferences ----------------------------------------------------------


def test_preferences_need_sign_in_even_when_forecasts_do_not(env, monkeypatch):
    client, *_ = env
    monkeypatch.setenv("API_REQUIRE_SIGN_IN", "false")
    assert client.get("/me/preferences").status_code == 401
    assert client.put("/me/preferences", json={}).status_code == 401
    assert client.delete("/me/preferences").status_code == 401


def test_preferences_are_stored_per_account(env, monkeypatch):
    client, store, _ = env
    rows, calls = {}, []

    def read(method, account, **kwargs):
        calls.append((method, account))
        if method == "get_user_preferences":
            return rows.get(account)
        if method == "save_user_preferences":
            rows[account] = {**kwargs, "updated_at": datetime(2026, 10, 10, tzinfo=timezone.utc)}
            return rows[account]
        return rows.pop(account, None) is not None

    monkeypatch.setattr(main, "_read", read)
    sign_in(client, store)
    assert client.get("/me/preferences").json() == {"preferences": None}
    saved = client.put("/me/preferences", json={
        "age_band": "25-39", "strategy": "day_trader", "experience_level": "beginner",
        "preferences": {"theme": "dark", "tickers": ["AAPL"]},
    }).json()["preferences"]
    assert saved["strategy"] == "day_trader" and saved["preferences"]["theme"] == "dark"
    # Keyed by the provider's subject id, never the email.
    assert calls[-1] == ("save_user_preferences", "idp.example:user-1")
    assert client.get("/me/preferences").json()["preferences"]["age_band"] == "25-39"
    assert client.delete("/me/preferences").json() == {"deleted": True}
    assert client.delete("/me/preferences").json() == {"deleted": False}


@pytest.mark.parametrize("body", [
    {"age_band": "16-17"},
    {"strategy": "options_only"},
    {"experience_level": "expert"},
    {"preferences": {"notes": "x" * 5000}},
])
def test_invalid_preferences_are_422(env, monkeypatch, body):
    client, store, _ = env
    monkeypatch.setattr(main, "_read", lambda *a, **k: pytest.fail("must not reach the database"))
    sign_in(client, store)
    assert client.put("/me/preferences", json=body).status_code == 422


def test_cors_allows_the_preference_methods(env):
    client, *_ = env
    response = client.options("/me/preferences", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "PUT"})
    assert response.status_code == 200
    assert "PUT" in response.headers["access-control-allow-methods"]
