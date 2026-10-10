"""Chart builders and routes: plain data in, JSON-safe chart dicts out."""

import asyncio
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ai.main import predict
from api import main
from charts import backtest_charts, prediction_charts, price_charts, score_charts

NY = ZoneInfo("America/New_York")


def _bars(n=120):
    # Daily bars are stored at midnight New York time, as the database does.
    return [{
        "bar_at": datetime(2026, 1, 1, tzinfo=NY) + timedelta(days=i),
        "open": Decimal("100") + i, "high": Decimal("102") + i, "low": Decimal("99") + i,
        "close": Decimal("101") + i + (i % 3), "volume": 1_000_000 + i,
    } for i in range(n)]


def _random_walk_bars(n=500, seed=7):
    close = 100 * np.exp(np.cumsum(np.random.default_rng(seed).normal(0.0003, 0.012, n)))
    start = datetime(2024, 1, 1, tzinfo=NY)
    return [{"bar_at": start + timedelta(days=i), "open": c, "high": c * 1.01, "low": c * 0.99,
             "close": c, "volume": 1_000_000.0 + 1000 * (i % 17)} for i, c in enumerate(close)]


def _by_id(charts):
    return {c["id"]: c for c in charts}


def test_price_charts_align_series_with_x_and_are_json_safe():
    charts = _by_id(price_charts(_bars(), "TEST"))
    assert set(charts) == {"price", "volume", "rsi", "macd", "drawdown"}
    for c in charts.values():
        assert all(len(s["data"]) == len(c["x"]) for s in c["series"])
    json.dumps(charts, allow_nan=False)  # NaN warm-up values must be null
    sma50 = charts["price"]["series"][2]["data"]
    assert sma50[48] is None and sma50[49] is not None
    assert charts["price"]["x"][0] == "2026-01-01"
    assert charts["rsi"]["reference_lines"][0]["value"] == 70
    assert min(charts["drawdown"]["series"][0]["data"]) <= 0


def test_price_charts_need_two_bars():
    assert price_charts([], "TEST") == []
    assert price_charts(_bars(1), "TEST") == []


def test_prediction_charts(snapshot, fake_llm):
    result = asyncio.run(predict("TEST", llm=fake_llm, snapshot=snapshot))
    charts = _by_id(prediction_charts(result))
    votes = charts["direction_votes"]["series"][0]["data"]
    assert charts["direction_votes"]["x"] == ["up", "flat", "down"]
    assert sum(votes) == len([r for r in result.personas if r.view])
    conviction = charts["persona_conviction"]["series"][0]
    assert len(conviction["data"]) == len(conviction["group"]) == len(charts["persona_conviction"]["x"])
    assert set(charts["strategy_scores"]["x"]) == set(result.by_strategy)
    low, last, high = charts["price_band"]["series"][0]["data"][:3]
    assert low < last < high
    assert "Personas" in charts["baselines"]["x"]
    assert "mode_scores" not in charts  # one mode only
    json.dumps(charts, allow_nan=False)


def test_score_charts():
    report = {
        "scored": 4, "accuracy": {"personas": 0.5, "always_up": 0.45},
        "by_strategy": {"long_term": 0.6, "day_trader": None}, "by_age_band": {}, "by_mode": {},
        "by_model": {}, "strategy_weights": {"long_term": 1.1},
        "by_confidence": {"0.00-0.25": {"n": 2, "accuracy": 0.5}, "0.25-0.50": {"n": 0, "accuracy": None}},
    }
    charts = _by_id(score_charts(report))
    assert set(charts) == {"accuracy_vs_baselines", "accuracy_by_strategy",
                           "accuracy_by_strength", "strategy_weights"}
    assert charts["accuracy_by_strategy"]["series"][0]["data"] == [None, 0.6]
    assert charts["accuracy_by_strength"]["series"][1]["data"] == [2, 0]
    assert score_charts({"scored": 0, "accuracy": {"personas": None}}) == []


@pytest.fixture
def client(monkeypatch, fake_llm):
    main.score_cache.clear()  # a report cached by another test file must not leak in
    main.app.dependency_overrides = {main.get_llm: lambda: fake_llm}
    try:
        with TestClient(main.app) as client:
            yield client
    finally:
        main.app.dependency_overrides = {}


def test_chart_routes(client, monkeypatch, snapshot, fake_llm):
    result = asyncio.run(predict("TEST", llm=fake_llm, snapshot=snapshot))
    calls = []

    def read(method, *args, **kwargs):
        calls.append((method, args, kwargs))
        return _bars() if method == "get_price_history" else result
    monkeypatch.setattr(main, "_read", read)

    body = client.get("/stocks/aapl/charts?limit=120").json()
    assert body["ticker"] == "AAPL" and {c["id"] for c in body["charts"]} >= {"price", "rsi"}
    assert calls[0] == ("get_price_history", ("AAPL",), {"interval": "1d", "limit": 120})

    body = client.get(f"/predictions/{result.id}/charts").json()
    assert body["prediction_id"] == result.id
    assert "direction_votes" in {c["id"] for c in body["charts"]}


def test_score_chart_route(client, monkeypatch):
    from ai.evaluation import Report
    from database import service
    report = Report(scored=3, pending=0, unreadable=0, accuracy={"personas": 0.5, "always_up": 0.4},
                    coverage=1.0, accuracy_when_called=0.5, by_confidence={"0.00-0.25": (3, 0.5)},
                    by_strategy={"long_term": 0.5}, by_age_band={})
    monkeypatch.setattr(service, "score_database", lambda: report)
    ids = {c["id"] for c in client.get("/score/charts").json()["charts"]}
    assert {"accuracy_vs_baselines", "accuracy_by_strategy", "accuracy_by_strength"} <= ids


@pytest.mark.parametrize("url", ["/stocks/AAPL/charts?limit=1", "/stocks/bad%20ticker/charts",
                                 "/predictions/not-an-id/charts"])
def test_chart_routes_validate_input(client, url):
    assert client.get(url).status_code == 422


def test_intraday_bars_add_vwap_and_volume_profile(snapshot):
    bars = [{"bar_at": ts.to_pydatetime(), "open": r.Open, "high": r.High, "low": r.Low,
             "close": r.Close, "volume": r.Volume} for ts, r in snapshot.intraday.iterrows()]
    charts = _by_id(price_charts(bars, "TEST", "5m"))
    vwap = charts["price"]["series"][-1]
    assert vwap["name"] == "VWAP" and len(vwap["data"]) == len(charts["price"]["x"])
    assert "T09:30:00-04:00" in charts["price"]["x"][0]  # intraday keeps New York timestamps
    lows = [b["low"] for b in bars]
    assert min(lows) <= min(v for v in vwap["data"] if v is not None)
    profile = charts["volume_profile"]
    assert len(profile["x"]) == len(profile["series"][0]["data"]) == 24
    assert {r["label"] for r in profile["reference_lines"]} >= {"Point of control"}
    json.dumps(charts, allow_nan=False)
    assert "volume_profile" not in _by_id(price_charts(_bars(), "TEST", "1d"))


def test_vwap_restarts_each_session(snapshot):
    from finance.indicators import vwap_series
    intraday = snapshot.intraday
    series = vwap_series(intraday)
    first_open = intraday.index.date == intraday.index[0].date()
    second_start = np.flatnonzero(~first_open)[0]
    typical = (intraday["High"] + intraday["Low"] + intraday["Close"]) / 3
    assert series.iloc[second_start] == pytest.approx(typical.iloc[second_start])


def test_backtest_charts_match_the_regression_summary():
    from finance.linear_regression import run_regression
    from charts.price import _frame
    bars = _random_walk_bars()
    charts = _by_id(backtest_charts(bars, "TEST", 5))
    curve = charts["equity_curve"]
    assert curve["series"][0]["data"][0] == curve["series"][1]["data"][0] == 100.0
    assert all(len(s["data"]) == len(curve["x"]) for s in curve["series"])
    assert len(charts["period_returns"]["x"]) == len(curve["x"]) - 1

    daily = _frame(bars).rename(columns={"open": "Open", "high": "High", "low": "Low",
                                         "close": "Close", "volume": "Volume"})
    summary = run_regression(daily, 5)
    final = curve["series"][0]["data"][-1] / 100 - 1
    assert final * 100 == pytest.approx(summary.strategy["total_return_pct"], abs=0.05)
    held = curve["series"][1]["data"][-1] / 100 - 1
    assert held * 100 == pytest.approx(summary.buy_and_hold["total_return_pct"], abs=0.05)
    json.dumps(charts, allow_nan=False)


def test_backtest_charts_need_enough_history():
    assert backtest_charts(_bars(60), "TEST", 5) == []
    assert backtest_charts([], "TEST", 5) == []


def _outcome(day, hit, always_up_hit):
    return SimpleNamespace(
        resolved_on=date(2026, 3, 1) + timedelta(days=day), actual="up",
        prediction=SimpleNamespace(direction="up" if hit else "down", generated_at=datetime(2026, 2, 1),
                                   baselines={"always_up": "up" if always_up_hit else "down"}))


def test_accuracy_over_time():
    outcomes = [_outcome(d, hit=d % 2 == 0, always_up_hit=True) for d in range(12)]
    report = {"scored": 12, "accuracy": {"personas": 0.5, "always_up": 1.0}}
    over_time = _by_id(score_charts(report, outcomes))["accuracy_over_time"]
    assert len(over_time["x"]) == 12 and over_time["x"][0] == "2026-03-01"
    personas, always_up = (s["data"] for s in over_time["series"])
    assert personas[:4] == [None] * 4 and personas[5] == pytest.approx(0.5, abs=0.1)
    assert set(v for v in always_up if v is not None) == {1.0}
    json.dumps(over_time, allow_nan=False)
    assert "accuracy_over_time" not in _by_id(score_charts(report, outcomes[:5]))
    assert "accuracy_over_time" not in _by_id(score_charts(report))


def test_backtest_route(client, monkeypatch):
    monkeypatch.setattr(main, "_read", lambda method, *a, **k: _random_walk_bars())
    body = client.get("/stocks/spy/charts/backtest?horizon_days=5").json()
    assert body["ticker"] == "SPY" and body["horizon_days"] == 5
    assert {c["id"] for c in body["charts"]} == {"equity_curve", "period_returns"}
    assert client.get("/stocks/SPY/charts/backtest?horizon_days=0").status_code == 422
    monkeypatch.setattr(main, "_read", lambda method, *a, **k: [])
    assert client.get("/stocks/SPY/charts/backtest").json()["charts"] == []
