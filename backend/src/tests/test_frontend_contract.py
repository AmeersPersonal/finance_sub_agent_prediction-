"""The API shapes the dashboard depends on (frontend/src/features/market-dashboard,
frontend/src/lib/auth.js). Changing a field here breaks the frontend: update both together.

Reads go through the real repository against an isolated PostgreSQL schema (skipped
without TEST_DATABASE_URL, like test_database.py), so field names, types and ordering
come from the actual SQL. Jobs and errors use fakes and always run.
"""

import asyncio
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai.main import predict
from api import main
from database.repository import DatabaseRepository
from database.service import normalize_ticker
from test_database import db  # noqa: F401  (isolated PostgreSQL schema fixture)

FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "src"
DIRECTIONS = {"up", "down", "flat", "unclear"}
STRATEGIES = {"long_term", "day_trader", "index_options"}


@pytest.fixture(autouse=True)
def fresh_api_state(monkeypatch):
    monkeypatch.setenv("API_REQUIRE_SIGN_IN", "false")
    for state in (main.prediction_limiter, main.jobs, main.score_cache):
        state.clear()
    yield
    for state in (main.prediction_limiter, main.jobs, main.score_cache):
        state.clear()
    main.app.dependency_overrides = {}


@pytest.fixture
def api(db, monkeypatch, fake_llm):  # noqa: F811
    """The API reading the test schema through the real repository."""
    monkeypatch.setattr(main, "_read", lambda method, *a, **kw: getattr(DatabaseRepository(db), method)(*a, **kw))
    main.app.dependency_overrides = {main.get_llm: lambda: fake_llm}
    with TestClient(main.app) as client:
        yield client, DatabaseRepository(db)


def _bars(days: int, interval: str = "1d"):
    start = datetime(2026, 9, 1, 4, tzinfo=timezone.utc)
    step = timedelta(days=1) if interval == "1d" else timedelta(minutes=5)
    return [{"bar_at": start + i * step, "open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100.5 + i,
             "volume": 1000 + i, "fetched_at": datetime(2026, 10, 10, tzinfo=timezone.utc)} for i in range(days)]


def _is_iso(value) -> bool:
    return isinstance(value, str) and datetime.fromisoformat(value) is not None


# --- reads the dashboard makes ------------------------------------------------------


def test_history_bars_are_numbers_oldest_first_and_the_most_recent_limit(api):
    client, repo = api
    repo.save_price_bars("TEST", _bars(30), interval="1d", adjustment_basis="total_return")
    repo.save_price_bars("TEST", _bars(5, "5m"), interval="5m", adjustment_basis="total_return")
    body = client.get("/stocks/test/history?interval=1d&limit=22").json()
    bars = body["bars"]
    assert len(bars) == 22
    for bar in bars:
        assert {"bar_at", "open", "high", "low", "close", "volume"} <= bar.keys()
        assert _is_iso(bar["bar_at"])
        assert all(isinstance(bar[k], (int, float)) for k in ("open", "high", "low", "close", "volume"))
    times = [datetime.fromisoformat(b["bar_at"]) for b in bars]
    assert times == sorted(times)  # the dashboard takes .at(-1) as the latest
    assert bars[-1]["close"] == 129.5  # the most recent 22, not the first 22
    assert len(client.get("/stocks/TEST/history?interval=5m&limit=100").json()["bars"]) == 5


def test_news_documents_have_what_the_news_panel_reads(api):
    client, repo = api
    seen = datetime(2026, 10, 10, tzinfo=timezone.utc)
    repo.store_document(source_url="https://news.example/1", title="Dated", content_text="Body text", document_type="news",
                        content_kind="excerpt", source_name="Example", published_at=seen - timedelta(hours=5),
                        first_seen_at=seen, symbols=["TEST"], classification={"role": "company_info"})
    repo.store_document(source_url="https://news.example/2", title="Undated", content_text="Other", document_type="news",
                        source_name="Example", first_seen_at=seen, symbols=["TEST"], classification={"role": "public_opinion"})
    repo.store_document(source_url="https://news.example/3", title="Other ticker", content_text="x", document_type="news",
                        first_seen_at=seen, symbols=["PEER"])
    documents = client.get("/stocks/TEST/news?limit=40").json()["documents"]
    assert sorted(d["title"] for d in documents) == ["Dated", "Undated"]
    for d in documents:
        assert {"id", "title", "source_url", "source_name", "excerpt", "published_at", "first_seen_at",
                "classification", "document_type"} <= d.keys()
        assert isinstance(d["id"], int) and _is_iso(d["first_seen_at"])
        assert d["published_at"] is None or _is_iso(d["published_at"])
        assert d["classification"]["role"] in {"company_info", "public_opinion", "product_event", "other"}
    assert next(d for d in documents if d["title"] == "Undated")["published_at"] is None


def test_a_ticker_with_nothing_saved_is_empty_lists_not_errors(api):
    client, _ = api
    assert client.get("/stocks/NONE/history?interval=1d&limit=3").json()["bars"] == []
    assert client.get("/stocks/NONE/history?interval=5m&limit=1").json()["bars"] == []
    assert client.get("/stocks/NONE/news?limit=40").json()["documents"] == []
    assert client.get("/predictions?ticker=NONE&limit=1").json() == {"predictions": []}


def assert_forecast_contract(p: dict) -> None:
    """Every field ForecastPanel, PersonasPanel, StoryPanel and the chart read."""
    assert p["direction"] in DIRECTIONS
    assert isinstance(p["horizon_days"], int) and isinstance(p["ticker"], str)
    assert 0 <= p["confidence"] <= 1 and 0 <= p["agreement"] <= 1
    assert p["by_strategy"] and set(p["by_strategy"]) <= STRATEGIES
    assert all(-1 <= v <= 1 for v in p["by_strategy"].values())
    assert isinstance(p["flat_band_pct"], (int, float)) and isinstance(p["last_price"], (int, float))
    assert _is_iso(p["generated_at"])
    assert p["next_earnings_date"] is None or date.fromisoformat(p["next_earnings_date"])
    assert p["earnings_within_horizon"] in (True, False, None)
    assert {"always_up", "momentum"} <= p["baselines"].keys()
    sentiment = p.get("headline_sentiment")
    assert sentiment is None or ({"summary", "overall"} <= sentiment.keys() and -1 <= sentiment["overall"] <= 1)
    assert p["personas"]
    for persona in p["personas"]:
        assert {"persona_id", "strategy", "age_band", "mode", "view", "error"} <= persona.keys()
        assert persona["strategy"] in STRATEGIES
        view = persona["view"]
        if view is None:
            assert isinstance(persona["error"], str)
        else:
            assert view["direction"] in {"up", "down", "flat"}
            assert 0 <= view["conviction"] <= 1 and isinstance(view["rationale"], str)


def test_the_latest_saved_forecast_has_every_field_the_dashboard_reads(api, snapshot, failing_llm):
    client, repo = api
    older = asyncio.run(predict("TEST", snapshot=snapshot, llm=failing_llm))  # some personas fail: view null
    repo.save_prediction(older)
    newer = older.model_copy(update={"id": "f" * 32, "generated_at": older.generated_at + timedelta(hours=1)})
    repo.save_prediction(newer)
    predictions = client.get("/predictions?ticker=test&limit=1").json()["predictions"]
    assert [p["id"] for p in predictions] == [newer.id]  # limit=1 is the newest
    assert_forecast_contract(predictions[0])
    assert any(p["view"] is None for p in predictions[0]["personas"])


# --- forecast jobs ----------------------------------------------------------------------


@pytest.fixture
def jobs_client(monkeypatch, fake_llm, snapshot):
    async def service(method, ticker, **kwargs):
        return await predict(ticker, snapshot=snapshot, llm=fake_llm)
    monkeypatch.setattr(main, "_service", service)
    main.app.dependency_overrides = {main.get_llm: lambda: fake_llm}
    with TestClient(main.app) as client:
        yield client


def _wait(client, path):
    for _ in range(200):
        view = client.get(path).json()
        if view["status"] in ("succeeded", "failed"):
            return view
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_the_dashboard_job_request_is_accepted_and_polls_to_a_forecast(jobs_client):
    started = jobs_client.post("/prediction-jobs", json={"ticker": "TEST", "horizon_days": 5, "modes": "default"})
    assert started.status_code == 202
    job = started.json()
    assert isinstance(job["job_id"], str) and job["status"] in ("queued", "running", "succeeded")
    finished = _wait(jobs_client, f"/prediction-jobs/{job['job_id']}")
    assert finished["status"] == "succeeded" and finished["error"] is None
    assert_forecast_contract(finished["prediction"])


def test_a_failed_job_reports_a_string_detail(jobs_client, monkeypatch):
    async def failing(*args, **kwargs):
        raise RuntimeError("provider secret detail")
    monkeypatch.setattr(main, "_service", failing)
    job = jobs_client.post("/prediction-jobs", json={"ticker": "TEST", "horizon_days": 5, "modes": "default"}).json()
    finished = _wait(jobs_client, f"/prediction-jobs/{job['job_id']}")
    assert finished["status"] == "failed"
    assert isinstance(finished["error"]["detail"], str) and isinstance(finished["error"]["status_code"], int)


# --- errors the frontend turns into messages ----------------------------------------------


def test_error_bodies_the_frontend_can_read(jobs_client, monkeypatch):
    invalid = jobs_client.get("/stocks/AAPL/history?interval=1d&limit=5000")
    assert invalid.status_code == 422
    assert all({"loc", "msg"} <= item.keys() for item in invalid.json()["detail"])

    monkeypatch.setattr(main.prediction_limiter, "limit", 1)
    body = {"ticker": "TEST", "horizon_days": 5, "modes": "default"}
    assert jobs_client.post("/prediction-jobs", json=body).status_code == 202
    limited = jobs_client.post("/prediction-jobs", json=body)
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0 and isinstance(limited.json()["detail"], str)

    def down(*args, **kwargs):
        raise main.DatabaseError("connection refused")
    monkeypatch.setattr(main, "_read", down)
    unavailable = jobs_client.get("/stocks/AAPL/news?limit=40")
    assert unavailable.status_code == 503 and isinstance(unavailable.json()["detail"], str)

    monkeypatch.setenv("API_REQUIRE_SIGN_IN", "true")
    unauthorized = jobs_client.post("/prediction-jobs", json=body)
    assert unauthorized.status_code == 401 and isinstance(unauthorized.json()["detail"], str)


def test_the_frontend_ticker_rule_matches_the_api():
    """A ticker the dashboard's search accepts must never be a 422 from the API."""
    source = (FRONTEND / "features" / "market-dashboard" / "lib" / "assets.js").read_text()
    pattern = re.search(r"TICKER_PATTERN = /\^(.+)\$/;", source).group(1)
    frontend = re.compile(pattern)
    for ticker in ["AAPL", "BRK.B", "^GSPC", "BTC-USD", "ES=F", "A", "X" * 15, "X" * 16, "", ".A", "A B", "<A>", "a"]:
        try:
            api_ok = normalize_ticker(ticker) == ticker
        except ValueError:
            api_ok = False
        assert bool(frontend.fullmatch(ticker)) == api_ok, ticker
