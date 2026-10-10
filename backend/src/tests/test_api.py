"""HTTP API with a fake LLM and the synthetic snapshot: no network, no API key."""

import json

import pytest
from fastapi.testclient import TestClient

from api import app as api


@pytest.fixture
def client(snapshot, fake_llm, tmp_path):
    log = tmp_path / "predictions.jsonl"

    def fetch(ticker):
        if ticker == "NOPE":
            raise ValueError("No price history for 'NOPE'")
        return snapshot

    api.app.dependency_overrides = {
        api.get_llm: lambda: fake_llm,
        api.get_fetcher: lambda: fetch,
        api.get_log_path: lambda: log,
    }
    yield TestClient(api.app), log
    api.app.dependency_overrides = {}


def test_health(client):
    test_client, _ = client
    assert test_client.get("/health").json() == {"status": "ok"}


def test_predict_returns_and_logs_the_prediction(client):
    test_client, log = client
    response = test_client.post("/predict", json={"ticker": "test"})
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "TEST" and body["direction"] == "up" and len(body["personas"]) == 13
    assert body["audit"] is None
    assert json.loads(log.read_text().splitlines()[0])["id"] == body["id"]


def test_predict_options_pass_through(client):
    test_client, log = client
    response = test_client.post("/predict", json={
        "ticker": "TEST", "horizon_days": 1, "strategies": ["day_trader"], "age_bands": ["18-24"],
        "audit": True, "log": False,
    })
    body = response.json()
    assert response.status_code == 200 and body["horizon_days"] == 1
    assert [p["persona_id"] for p in body["personas"]] == ["day_trader:18-24"]
    assert body["audit"]["risk"]["level"] in ("low", "medium", "high")
    assert not log.exists()


def test_predict_weights(client):
    test_client, _ = client
    heavy_day = test_client.post(
        "/predict", json={"ticker": "TEST", "strategy_weights": {"day_trader": 10}, "log": False}
    )
    assert heavy_day.json()["direction"] == "down"
    auto = test_client.post("/predict", json={"ticker": "TEST", "strategy_weights": "auto", "log": False})
    assert auto.json()["direction"] == "up"  # empty log: equal weights


@pytest.mark.parametrize(
    "payload",
    [
        {"ticker": "AAPL; rm -rf /"},
        {"ticker": ""},
        {"ticker": "TEST", "horizon_days": 0},
        {"ticker": "TEST", "strategies": ["scalper"]},
        {"ticker": "TEST", "age_bands": ["70-80"]},
        {"ticker": "TEST", "strategy_weights": {"long_term": -1}},
        {"ticker": "TEST", "strategy_weights": {"long_term": 0}},
        {"ticker": "TEST", "strategy_weights": "sometimes"},
        {"ticker": "TEST", "modes": "nonsense"},
        {"ticker": "TEST", "strategies": ["index_options"], "age_bands": ["16-17"]},
        {"ticker": "NOPE"},
    ],
)
def test_bad_requests_are_422(client, payload):
    test_client, log = client
    assert test_client.post("/predict", json=payload).status_code == 422
    assert not log.exists()


def test_all_personas_failing_is_a_502(client, fake_llm):
    test_client, _ = client
    fake_llm.fail_for = "year-old"  # every persona's system prompt
    response = test_client.post("/predict", json={"ticker": "TEST", "log": False})
    assert response.status_code == 502 and "personas failed" in response.json()["detail"]


def test_missing_api_key_is_a_503(snapshot, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    api._gemini.cache_clear()
    api.app.dependency_overrides = {api.get_fetcher: lambda: (lambda ticker: snapshot)}
    try:
        response = TestClient(api.app).post("/predict", json={"ticker": "TEST", "log": False})
    finally:
        api.app.dependency_overrides = {}
    assert response.status_code == 503 and "GEMINI_API_KEY" in response.json()["detail"]


def test_score_with_an_empty_log(client):
    test_client, _ = client
    body = test_client.get("/score").json()
    assert body["scored"] == 0 and "outcomes" not in body and body["strategy_weights"] == {}


def test_oauth_routes_are_mounted(client):
    test_client, _ = client
    assert test_client.get("/oauth/me").status_code == 401
