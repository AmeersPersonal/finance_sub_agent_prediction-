"""Dashboard requests exercise local fakes, never network services."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api import main
from database.connection import DatabaseError


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "_read", lambda method, *args, **kwargs: [])
    with TestClient(main.app) as client:
        yield client


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
