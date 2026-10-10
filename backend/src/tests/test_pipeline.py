import asyncio
import json

import pytest

from ai.agents import build_context, horizon_info
from ai.main import predict
from ai.personas import Strategy


def _data_block(prompt: str) -> dict:
    start = prompt.index("{")
    end = prompt.index("\n\nRelevant documents:")
    return json.loads(prompt[start:end])


def test_each_strategy_gets_its_own_data(snapshot):
    horizon = horizon_info(snapshot, 5, 0.01)
    long_term = build_context(Strategy.LONG_TERM, snapshot, horizon)
    day = build_context(Strategy.DAY_TRADER, snapshot, horizon)
    index = build_context(Strategy.INDEX_OPTIONS, snapshot, horizon)

    assert long_term["cagr_pct"] is not None and long_term["revenue"]["revenue_cagr_pct"] > 0
    assert day["latest_session"]["price_vs_vwap_pct"] is not None
    assert index["options"]["put_call_volume_ratio"] == 0.5
    assert index["sp500"]["beta_of_stock_vs_sp500"] is not None
    assert "valuation" not in day and "options" not in long_term
    assert all(c["horizon"] == horizon for c in (long_term, day, index))


def test_new_analysis_layers_reach_the_right_strategies(snapshot):
    horizon = horizon_info(snapshot, 5, 0.01)
    sentiment = {"overall": 0.4}
    long_term = build_context(Strategy.LONG_TERM, snapshot, horizon, sentiment)
    day = build_context(Strategy.DAY_TRADER, snapshot, horizon, sentiment)
    index = build_context(Strategy.INDEX_OPTIONS, snapshot, horizon, sentiment)

    assert long_term["altman_z"]["zone"] == "safe"
    assert long_term["beneish_m"]["above_threshold_possible_manipulation"] is False
    assert long_term["financial_health"]["roic_pct"] == pytest.approx(26.6667, abs=1e-3)
    assert long_term["quarterly_review"]["eps_beats"] == 3
    assert long_term["insiders_last_6m"]["buy_transactions"] == 12
    assert long_term["analysts"]["eps_revisions_up_30d"] == 6
    assert long_term["rates"]["curve_inverted"] is False
    assert "headline_sentiment" not in long_term  # long-term holders ignore daily news

    assert set(day["macd_pct_of_price"]) == {"macd", "histogram", "histogram_prev"}
    assert day["atr_14_pct"] > 0
    assert day["volume_profile_last_5_sessions"]["price_position"] in (
        "above value area", "inside value area", "below value area"
    )
    assert day["bid_ask_spread_pct"] == pytest.approx(0.1 / snapshot.last_price * 100, abs=1e-3)
    assert day["analyst_rating_changes"]["upgrades"] == 1
    assert day["headline_sentiment"] == sentiment

    assert index["macro"]["cpi_yoy_pct"] > 0 and "spread_10y_3m_pct_points" in index["macro"]
    assert index["sector"]["etf"] == "XLK" and index["sector"]["beta_vs_sector"] is not None
    assert index["nasdaq_100"]["beta_vs_qqq"] is not None
    assert index["short_interest"]["change_vs_prior_month_pct"] == 10.0
    assert index["options"]["iv_to_realized_vol"] > 0


def test_spread_is_hidden_outside_the_regular_session(snapshot):
    snapshot.info["marketState"] = "POST"
    horizon = horizon_info(snapshot, 5, 0.01)
    assert build_context(Strategy.DAY_TRADER, snapshot, horizon)["bid_ask_spread_pct"] is None


def test_horizon_flags_earnings_inside_the_window(snapshot):
    horizon = horizon_info(snapshot, 5, 0.0087)
    assert horizon["ends_about"] == "2026-10-16"
    assert horizon["flat_band_pct"] == 0.87
    assert horizon["next_earnings_date"] == "2026-10-14"
    assert horizon["earnings_within_horizon"] is True
    assert horizon_info(snapshot, 1, 0.01)["earnings_within_horizon"] is False


def test_earnings_unknown_when_calendar_failed(snapshot):
    snapshot.earnings_dates = []
    assert horizon_info(snapshot, 5, 0.01)["earnings_within_horizon"] is False
    snapshot.errors = {"calendar": "HTTPError: 429"}
    assert horizon_info(snapshot, 5, 0.01)["earnings_within_horizon"] is None


def test_missing_sources_degrade_instead_of_failing(snapshot):
    snapshot.intraday = snapshot.options = snapshot.market_daily = None
    snapshot.errors = {"intraday": "no data returned"}
    horizon = horizon_info(snapshot, 5, 0.01)
    assert "latest_session" not in build_context(Strategy.DAY_TRADER, snapshot, horizon)
    context = build_context(Strategy.INDEX_OPTIONS, snapshot, horizon)
    assert context["unavailable_sources"] == ["intraday"]


def test_predict_end_to_end(snapshot, fake_llm):
    prediction = asyncio.run(predict("TEST", llm=fake_llm, snapshot=snapshot))

    assert len(prediction.personas) == 13 and len(fake_llm.calls) == 13
    # long_term and index_options vote up at 0.6, day_trader down at 0.6: one vote each.
    assert prediction.direction == "up"
    assert prediction.net_score == pytest.approx(0.2)
    assert prediction.agreement == pytest.approx(2 / 3, abs=1e-3)
    assert prediction.by_strategy["day_trader"] == -0.6
    assert prediction.earnings_within_horizon is True
    assert set(prediction.baselines) == {"always_up", "momentum", "linear_regression"}
    assert prediction.linear_regression["n_test"] > 100
    assert "sharpe" in prediction.linear_regression["strategy"]
    assert fake_llm.sentiment_calls == 1 and prediction.headline_sentiment["overall"] == 0.4
    assert prediction.risk["max_position_pct_of_account_risking_1pct"] > 0
    assert prediction.prompt_version == "4"
    for _, prompt in fake_llm.calls:
        assert _data_block(prompt)["ticker"] == "TEST"  # the data block is valid JSON
        assert f"+/-{prediction.flat_band_pct:g}%" in prompt


def test_one_failed_persona_does_not_sink_the_prediction(snapshot, failing_llm):
    prediction = asyncio.run(predict("TEST", llm=failing_llm, snapshot=snapshot))
    failed = [p for p in prediction.personas if p.error]
    assert len(failed) == 3 and all(p.age_band == "55-65" for p in failed)
    assert prediction.direction == "up"


def test_regression_receives_explicit_database_dataset(snapshot, fake_llm, monkeypatch):
    from finance.linear_regression import run_regression

    stored = snapshot.daily[['Close', 'Volume']].copy()
    received = []
    def regression(data, horizon):
        received.append(data)
        return run_regression(data, horizon)
    monkeypatch.setattr('ai.main.run_regression', regression)
    prediction = asyncio.run(predict('TEST', snapshot=snapshot, llm=fake_llm, regression_daily=stored))
    assert received[0] is stored
    assert prediction.linear_regression is not None
