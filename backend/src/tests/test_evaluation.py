from datetime import date, datetime

import pandas as pd
import pytest

from ai.evaluation import MARKET_TZ, baselines, load_log, log_prediction, resolve, score
from ai.schemas import PersonaResult, PersonaView, Prediction


def make_prediction(direction="up", confidence=0.4, votes=(), **overrides) -> Prediction:
    fields = dict(
        ticker="TEST", horizon_days=5, direction=direction, confidence=confidence,
        net_score=0.4, agreement=1.0, by_strategy={}, flat_band_pct=1.0, last_price=100.0,
        data_as_of="2026-10-09", next_earnings_date=None, earnings_within_horizon=None,
        baselines={"always_up": "up", "momentum": "down"}, linear_regression=None,
        generated_at=datetime(2026, 10, 9, 21, 0, tzinfo=MARKET_TZ), model="fake",
        prompt_version="2", data_warnings=[],
        personas=[
            PersonaResult(
                persona_id=f"{s}:{a}", strategy=s, age_band=a,
                view=PersonaView(direction=d, conviction=0.5, rationale="", key_factors=[]),
            )
            for s, a, d in votes
        ],
    )
    return Prediction(**{**fields, **overrides})


def closes(final_close: float) -> pd.Series:
    days = [d.date() for d in pd.bdate_range("2026-10-05", "2026-10-20")]
    values = [100.0] * len(days)
    values[days.index(date(2026, 10, 16))] = final_close  # 5 trading days after 10-09
    return pd.Series(values, index=days)


def at(day: str, hour: int) -> datetime:
    return datetime.fromisoformat(f"{day}T{hour:02d}:00").replace(tzinfo=MARKET_TZ)


def test_resolve_uses_the_close_n_trading_days_later():
    outcome = resolve(make_prediction(), closes(103.0), at("2026-10-20", 12))
    assert outcome.resolved_on == date(2026, 10, 16)
    assert outcome.return_pct == 3.0
    assert outcome.actual == "up"
    assert resolve(make_prediction(), closes(100.5), at("2026-10-20", 12)).actual == "flat"


def test_resolve_waits_for_the_closing_bar_to_settle():
    assert resolve(make_prediction(), closes(103.0), at("2026-10-16", 10)) is None
    assert resolve(make_prediction(), closes(103.0), at("2026-10-16", 17)) is not None


def test_score_compares_personas_against_baselines():
    right = make_prediction("up", 0.6, votes=[("long_term", "18-24", "up"), ("day_trader", "18-24", "down")])
    abstained = make_prediction("unclear", 0.0, ticker="OTHER")
    report = score(
        [right, abstained, make_prediction(ticker="NODATA")],
        {"TEST": closes(105.0), "OTHER": closes(95.0)},
        at("2026-10-20", 12),
    )
    assert (report.scored, report.pending) == (2, 1)
    assert report.accuracy == {"personas": 0.5, "always_up": 0.5, "momentum": 0.5}
    assert report.coverage == 0.5 and report.accuracy_when_called == 1.0
    assert report.by_confidence["0.50-1.00"] == (1, 1.0)
    assert report.by_strategy == {"day_trader": 0.0, "long_term": 1.0}


def test_log_round_trip_skips_unreadable_lines(tmp_path):
    path = tmp_path / "log.jsonl"
    prediction = make_prediction()
    log_prediction(prediction, path)
    with path.open("a") as f:
        f.write('{"not": "a prediction"}\n')
    loaded, unreadable = load_log(path)
    assert loaded == [prediction] and unreadable == 1
    assert load_log(tmp_path / "missing.jsonl") == ([], 0)


def test_baselines():
    rising = pd.Series([1.0, 2, 3, 4, 5, 6, 7])
    assert baselines(rising, 5, None) == {"always_up": "up", "momentum": "up"}
    assert baselines(rising[::-1].reset_index(drop=True), 5, -0.2)["momentum"] == "down"
    assert baselines(rising, 5, -0.2)["linear_regression"] == "down"


@pytest.mark.parametrize("ret,expected", [(0.02, "up"), (-0.02, "down"), (0.005, "flat")])
def test_classification_matches_flat_band(ret, expected):
    from finance.indicators import classify_move

    assert classify_move(ret, 0.01) == expected
