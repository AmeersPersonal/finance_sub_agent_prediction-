import asyncio
import json
import math

from ai.agents import build_context, horizon_info
from ai.features import extract_features
from ai.main import predict
from ai.personas import Strategy
from ai.schemas import Prediction


def test_flatten_is_numeric_prefixed_and_drops_text():
    contexts = {
        "long_term": {
            "ticker": "AAPL",
            "last_price": 100.0,
            "horizon": {"trading_days": 5, "earnings_within_horizon": True, "ends_about": "x"},
            "valuation": {"trailing_pe": 25.0, "forward_pe": None, "market_cap": float("nan")},
            "headlines": ["a", "b"],
        },
        "day_trader": {"last_5_daily_returns_pct": [1.0, None, -2.0], "rsi_14_daily": 55.0},
    }
    row = extract_features(contexts, {"predicted_return_pct": 0.4}, {"overall": 0.2})

    assert row["last_price"] == 100.0  # shared keys are not prefixed or duplicated
    assert row["horizon.trading_days"] == 5.0
    assert row["horizon.earnings_within_horizon"] == 1.0
    assert row["long_term.valuation.trailing_pe"] == 25.0
    assert row["long_term.valuation.forward_pe"] is None  # kept so columns stay stable
    assert row["long_term.valuation.market_cap"] is None  # non-finite -> None
    assert row["day_trader.last_5_daily_returns_pct.2"] == -2.0
    assert row["regression.predicted_return_pct"] == 0.4
    assert row["sentiment.overall"] == 0.2
    assert not any("headlines" in k or "ticker" in k or "ends_about" in k for k in row)
    assert all(v is None or (isinstance(v, float) and math.isfinite(v)) for v in row.values())


def test_prediction_logs_features_and_old_lines_still_load(snapshot, fake_llm):
    result = asyncio.run(predict("AAPL", 5, llm=fake_llm, snapshot=snapshot))
    assert result.features
    assert "long_term.valuation.trailing_pe" in result.features
    assert "index_options.options.put_call_volume_ratio" in result.features
    json.dumps(result.features)  # serialisable for the jsonl log

    old = result.model_dump(mode="json")
    del old["features"]
    assert Prediction.model_validate(old).features is None


def test_features_use_only_the_packets_the_personas_saw(snapshot):
    horizon = horizon_info(snapshot, 5, 0.01)
    context = build_context(Strategy.LONG_TERM, snapshot, horizon)
    row = extract_features({"long_term": context})
    assert row["long_term.cagr_pct"] == context["cagr_pct"]
