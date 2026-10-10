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


def yahoo_closes(values: dict[str, float], splits: dict[str, float], verified=True) -> pd.Series:
    series = pd.Series({date.fromisoformat(d): v for d, v in values.items()})
    series.attrs.update(price_basis="yahoo_split_adjusted_close", actions_verified=verified,
                        calendar="XNYS", stock_splits=splits)
    return series


def _session_closes(close: float, final: float, start="2026-10-05", end="2026-10-20"):
    days = [d.date().isoformat() for d in pd.bdate_range(start, end)]
    return {d: (final if d == "2026-10-16" else close) for d in days}


def test_split_inside_horizon_is_not_a_false_loss():
    # 4:1 split on 10-13; Yahoo restates every earlier close to the new share basis.
    values = _session_closes(25.0, 26.0)
    outcome = resolve(make_prediction(), yahoo_closes(values, {"2026-10-13": 4.0}), at("2026-10-20", 12))
    assert outcome.return_pct == 4.0 and outcome.actual == "up"
    assert outcome.split_factor == 4.0 and outcome.actual_price == 104.0


def test_split_after_outcome_date_is_also_undone():
    # A later 2:1 split halves the already-restated outcome close again.
    values = _session_closes(12.5, 13.0)
    outcome = resolve(make_prediction(), yahoo_closes(values, {"2026-10-13": 4.0, "2026-10-20": 2.0}),
                      at("2026-10-20", 12))
    assert outcome.return_pct == 4.0 and outcome.split_factor == 8.0


def test_split_before_entry_is_ignored():
    values = _session_closes(100.0, 103.0)
    outcome = resolve(make_prediction(), yahoo_closes(values, {"2026-10-01": 2.0}), at("2026-10-20", 12))
    assert outcome.return_pct == 3.0 and outcome.split_factor == 1.0


def test_unverified_corporate_actions_or_unknown_basis_stay_unscored():
    values = _session_closes(100.0, 103.0)
    assert resolve(make_prediction(), yahoo_closes(values, {}, verified=False), at("2026-10-20", 12)) is None
    unknown = closes(103.0)
    unknown.attrs["price_basis"] = "dividend_adjusted"
    assert resolve(make_prediction(), unknown, at("2026-10-20", 12)) is None


def test_missing_session_bar_does_not_shift_the_outcome_date():
    series = closes(103.0).drop(date(2026, 10, 14))
    assert resolve(make_prediction(), series, at("2026-10-20", 12)) is None


def test_exchange_holidays_are_not_counted_as_sessions():
    # Thanksgiving 2026-11-26 is closed: two sessions after 11-24 is the 11-27 half day.
    prediction = make_prediction(data_as_of="2026-11-24", horizon_days=2)
    days = [d.date() for d in pd.bdate_range("2026-11-20", "2026-12-01") if d.date() != date(2026, 11, 26)]
    series = pd.Series([100.0] * len(days), index=days)
    series[date(2026, 11, 27)] = 97.0
    assert resolve(prediction, series, at("2026-11-27", 13)) is None  # 13:00 early close not settled
    outcome = resolve(prediction, series, at("2026-11-27", 14))
    assert outcome.resolved_on == date(2026, 11, 27) and outcome.actual == "down"


def test_scoring_requires_an_exchange_session_and_aware_clock():
    assert resolve(make_prediction(data_as_of="2026-10-10"), closes(103.0), at("2026-10-20", 12)) is None
    assert resolve(make_prediction(), closes(103.0), datetime(2026, 10, 20, 12)) is None


def test_fetch_closes_reads_exchange_from_mapping_metadata(monkeypatch):
    """yfinance returns a HistoryMetadata Mapping, not a dict; it must still set the calendar."""
    import sys
    import types
    from collections.abc import Mapping

    from ai.evaluation import fetch_closes

    class Metadata(Mapping):
        def __init__(self, data): self._data = data
        def __getitem__(self, key): return self._data[key]
        def __iter__(self): return iter(self._data)
        def __len__(self): return len(self._data)

    index = pd.DatetimeIndex(pd.bdate_range("2026-10-05", "2026-10-09"), tz=MARKET_TZ)
    history = pd.DataFrame({"Close": [100.0] * 5, "Stock Splits": [0.0] * 5}, index=index)

    class FakeTicker:
        def __init__(self, symbol): pass
        def history(self, **_): return history
        def get_history_metadata(self): return Metadata({"exchangeName": "NMS"})

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=FakeTicker))
    series = fetch_closes(["TEST"], date(2026, 10, 5))["TEST"]
    assert series.attrs["calendar"] == "XNYS"
    assert series.attrs["actions_verified"] is True
