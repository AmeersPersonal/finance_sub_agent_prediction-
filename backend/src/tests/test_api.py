"""Dashboard requests exercise local fakes, never network services."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api import main
from database.connection import DatabaseError


@pytest.fixture
def client(monkeypatch, fake_llm):
    monkeypatch.setattr(main, "_read", lambda method, *args, **kwargs: [])
    # Never build a real Gemini client, whether or not a backend/.env key exists.
    main.app.dependency_overrides = {main.get_llm: lambda: fake_llm}
    try:
        with TestClient(main.app) as client:
            yield client
    finally:
        main.app.dependency_overrides = {}


def test_history_and_news_normalize_ticker(client, monkeypatch):
    calls = []
    def read(method, *args, **kwargs):
        calls.append((method, args, kwargs))
        return [{"close": 123}] if method == "get_price_history" else [{"title": "Announcement"}]
    monkeypatch.setattr(main, "_read", read)
    assert client.get("/stocks/aapl/history?interval=5m&limit=3").json()["bars"] == [{"close": 123}]
    assert client.get("/stocks/aapl/news").json()["documents"][0]["title"] == "Announcement"
    assert calls[0] == ("get_price_history", ("AAPL",), {"interval": "5m", "limit": 3})


@pytest.mark.parametrize("url", ["/stocks/AAPL/history?limit=0", "/stocks/AAPL/history?interval=invalid", "/stocks/AAPL/news?limit=101", "/stocks/bad%20ticker/history", "/predictions?limit=101", "/predictions/not-an-id"])
def test_invalid_query(client, url):
    assert client.get(url).status_code == 422


def test_prediction_request_filters_adults_and_passes_choices(client, monkeypatch):
    captured = {}
    async def service(method, *args, **kwargs):
        captured.update(method=method, args=args, kwargs=kwargs)
        return {"ticker": args[0], "direction": "up"}
    monkeypatch.setattr(main, "_service", service)
    response = client.post("/predictions", json={"ticker": " nvda ", "strategies": ["day_trader"]})
    assert response.status_code == 201
    assert response.json()["ticker"] == "NVDA"
    assert captured["kwargs"]["age_bands"] == ["18-24", "25-39", "40-54", "55-65"]
    assert captured["kwargs"]["horizon_days"] == 5


@pytest.mark.parametrize("extra", [{"horizon_days": 0}, {"horizon_days": 253}, {"age_bands": ["16-17"]}, {"age_bands": []}, {"strategies": ["invalid"]}, {"strategies": ["long_term", "long_term"]}])
def test_invalid_prediction_input(client, extra):
    assert client.post("/predictions", json={"ticker": "AAPL", **extra}).status_code == 422


def test_missing_prediction_and_pending_evaluation(client, monkeypatch):
    identifier = uuid4().hex
    monkeypatch.setattr(main, "_read", lambda method, *args, **kwargs: None)
    assert client.get(f"/predictions/{identifier}").status_code == 404
    assert client.post(f"/predictions/{identifier}/evaluate").status_code == 404
    monkeypatch.setattr(main, "_read", lambda method, *args, **kwargs: {"id": identifier} if method == "get_prediction" else [])
    response = client.get(f"/predictions/{identifier}/evaluation")
    assert response.json()["status"] == "pending"


def test_prediction_listing_and_evaluation(client, monkeypatch):
    identifier = uuid4().hex
    def read(method, *args, **kwargs):
        if method == "get_prediction":
            return {"id": identifier}
        if method == "get_evaluations":
            return [{"actual_direction": "up"}]
        assert kwargs == {"ticker": "AAPL", "limit": 3}
        return [{"id": identifier}]
    monkeypatch.setattr(main, "_read", read)
    assert client.get("/predictions?ticker=aapl&limit=3").json()["predictions"] == [{"id": identifier}]
    assert client.get(f"/predictions/{identifier}/evaluation").json()["status"] == "evaluated"


def test_database_error_is_sanitized(client, monkeypatch):
    def read(*args, **kwargs):
        raise DatabaseError("private credential details")
    monkeypatch.setattr(main, "_read", read)
    response = client.get("/stocks/AAPL/history")
    assert response.status_code == 503
    assert "private" not in response.text


def test_upstream_failure_is_sanitized(client, monkeypatch):
    import sys
    from types import ModuleType
    import database
    fake_service = ModuleType("database.service")
    async def refresh_market(ticker):
        raise RuntimeError("provider credential detail")
    fake_service.refresh_market = refresh_market
    monkeypatch.setitem(sys.modules, "database.service", fake_service)
    monkeypatch.setattr(database, "service", fake_service, raising=False)
    response = client.post("/stocks/AAPL/refresh")
    assert response.status_code == 502
    assert "credential" not in response.text


def test_health_checks_connection(client, monkeypatch):
    from contextlib import contextmanager
    commands = []
    @contextmanager
    def connection():
        class Connection:
            def execute(self, sql):
                commands.append(sql)
        yield Connection()
    monkeypatch.setattr(main, "connect", connection)
    assert client.get("/health").json() == {"status": "ok", "database": "connected"}
    assert commands == ["SELECT 1"]


def test_mutation_endpoints_use_services(client, monkeypatch):
    identifier = uuid4().hex
    monkeypatch.setattr(main, "_read", lambda *args, **kwargs: {"id": identifier})
    calls = []
    async def service(method, *args, **kwargs):
        calls.append((method, args))
        return {"status": "ok"}
    monkeypatch.setattr(main, "_service", service)
    assert client.post("/stocks/nvda/refresh").status_code == 200
    assert client.post(f"/predictions/{identifier}/evaluate").status_code == 200
    assert calls == [("refresh_market", ("NVDA",)), ("evaluate_prediction", (identifier,))]


def test_cors_limits_browser_origins(client):
    response = client.options("/predictions", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    response = client.options("/predictions", headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in response.headers


# Merged from the backend branch's api/app.py tests: one app now serves both.

@pytest.fixture
def predict_client(monkeypatch, fake_llm):
    captured = {}
    async def service(method, *args, **kwargs):
        captured.update(method=method, args=args, kwargs=kwargs)
        return {"ticker": args[0], "direction": "up"}
    monkeypatch.setattr(main, "_service", service)
    main.app.dependency_overrides = {main.get_llm: lambda: fake_llm}
    try:
        with TestClient(main.app) as client:
            yield client, captured
    finally:
        main.app.dependency_overrides = {}


def test_prediction_options_pass_through(predict_client, fake_llm):
    client, captured = predict_client
    response = client.post("/predictions", json={
        "ticker": "TEST", "horizon_days": 1, "strategies": ["day_trader"], "age_bands": ["18-24"],
        "strategy_weights": {"day_trader": 2, "long_term": 0.5}, "modes": "temps",
        "live": True, "audit": True,
    })
    assert response.status_code == 201
    kwargs = captured["kwargs"]
    assert captured["method"] == "predict_and_store" and kwargs["llm"] is fake_llm
    assert kwargs["strategy_weights"] == {"day_trader": 2, "long_term": 0.5}
    assert [m.name for m in kwargs["modes"]] == ["t0.2", "t0.7", "t1.0"]
    assert kwargs["live"] is True and kwargs["audit"] is True


def test_prediction_defaults_and_auto_weights(predict_client):
    client, captured = predict_client
    client.post("/predictions", json={"ticker": "TEST"})
    kwargs = captured["kwargs"]
    assert [m.name for m in kwargs["modes"]] == ["default"]
    assert kwargs["strategy_weights"] is None and not kwargs["live"] and not kwargs["audit"]
    client.post("/predictions", json={"ticker": "TEST", "strategy_weights": "auto"})
    assert captured["kwargs"]["strategy_weights"] == "auto"


@pytest.mark.parametrize("payload", [
    {"ticker": "AAPL; rm -rf /"},
    {"ticker": ""},
    {"ticker": "TEST", "age_bands": ["70-80"]},
    {"ticker": "TEST", "strategy_weights": {"long_term": -1}},
    {"ticker": "TEST", "strategy_weights": {"long_term": 0}},
    {"ticker": "TEST", "strategy_weights": "sometimes"},
    {"ticker": "TEST", "modes": "nonsense"},
])
def test_bad_prediction_options_are_422(predict_client, payload):
    client, captured = predict_client
    assert client.post("/predictions", json=payload).status_code == 422
    assert not captured  # rejected before any market or model call


def test_service_errors_map_to_safe_statuses(monkeypatch, fake_llm):
    from database import service

    async def no_personas(*args, **kwargs):
        raise ValueError("No eligible personas for those strategies and age bands.")
    async def outage(*args, **kwargs):
        raise RuntimeError("All 13 personas failed; first error: secret provider detail")

    main.app.dependency_overrides = {main.get_llm: lambda: fake_llm}
    try:
        with TestClient(main.app) as client:
            monkeypatch.setattr(service, "predict_and_store", no_personas)
            response = client.post("/predictions", json={"ticker": "TEST"})
            assert response.status_code == 422 and "No eligible personas" in response.json()["detail"]
            monkeypatch.setattr(service, "predict_and_store", outage)
            response = client.post("/predictions", json={"ticker": "TEST"})
            assert response.status_code == 502 and "secret" not in response.text
    finally:
        main.app.dependency_overrides = {}


def test_missing_api_key_is_a_503(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(main, "_service", lambda *a, **k: pytest.fail("no forecast without a model"))
    main._gemini.cache_clear()
    with TestClient(main.app) as client:
        response = client.post("/predictions", json={"ticker": "TEST"})
    main._gemini.cache_clear()
    assert response.status_code == 503 and "GEMINI_API_KEY" in response.json()["detail"]


def test_score_reports_accuracy_and_pending_reasons(client, monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from ai.evaluation import Report
    from database import service

    waiting = SimpleNamespace(
        prediction=SimpleNamespace(id="abc", ticker="AAPL", data_as_of="2026-11-25", horizon_days=2),
        reason="horizon_open", detail="The horizon ends on 2026-11-30 (Monday).",
        retry_after=datetime(2026, 11, 30, 21, 30, tzinfo=timezone.utc),
    )
    report = Report(scored=0, pending=1, unreadable=0, accuracy={"personas": None}, coverage=None,
                    accuracy_when_called=None, by_confidence={"0.00-0.25": (0, None)},
                    by_strategy={}, by_age_band={}, pending_details=[waiting])
    monkeypatch.setattr(service, "score_database", lambda: report)
    body = client.get("/score").json()
    assert body["scored"] == 0 and "outcomes" not in body and body["strategy_weights"] == {}
    assert body["by_confidence"] == {"0.00-0.25": {"n": 0, "accuracy": None}}
    assert body["pending_details"] == [{
        "prediction_id": "abc", "ticker": "AAPL", "data_as_of": "2026-11-25", "horizon_days": 2,
        "reason": "horizon_open", "detail": "The horizon ends on 2026-11-30 (Monday).",
        "retry_after": "2026-11-30T21:30:00+00:00",
    }]


def test_oauth_routes_are_mounted(client):
    assert client.get("/oauth/me").status_code == 401


def test_cors_allows_the_dev_frontend_with_credentials(client):
    response = client.options("/predictions", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"
    blocked = client.options("/predictions", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in blocked.headers
