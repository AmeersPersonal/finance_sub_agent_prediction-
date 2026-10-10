"""Prediction log and scorer: is the persona model better than naive baselines?

Every prediction is appended to a JSONL log together with baseline calls made
at the same moment. Once a prediction's horizon has passed, the scorer takes
the close N trading days after its data date, classifies the move with the
flat band logged at prediction time, and scores the persona call and each
baseline on the same three-way up / flat / down outcome.

Score only live-logged predictions: replaying history through the LLM leaks
outcomes it may have seen in training.

Stock splits: Yahoo's "unadjusted" closes are still split-adjusted after the
fact (NVDA's 2024-06-07 close reads 120.89, not the ~1209 it traded at before
its 10:1 split). The logged live price is in pre-split units, so `resolve`
divides it by every split that took effect after the prediction's data date.

The scorer also suggests strategy weights from each strategy's scored votes;
`python main.py AAPL --weights auto` feeds them back into `predict()`.
"""

from __future__ import annotations

import logging
import threading
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import ValidationError

from ai.schemas import Direction, Prediction
from finance.indicators import classify_move

DEFAULT_LOG = Path(__file__).resolve().parents[2] / "data" / "predictions.jsonl"
MARKET_TZ = ZoneInfo("America/New_York")
CLOSE_IS_FINAL = time(16, 30)  # daily bars are settled a little after the 16:00 close
CONFIDENCE_BUCKETS = ((0.0, 0.25), (0.25, 0.5), (0.5, 1.01))
# Pseudo-votes at the pooled hit rate added to each strategy before weighting it,
# so a strategy needs a few dozen scored votes before its weight moves far from 1.
PRIOR_VOTES = 30

log = logging.getLogger(__name__)
_log_lock = threading.Lock()  # the API can log from several requests at once


def baselines(
    close: pd.Series, horizon_days: int, regression_return_pct: float | None
) -> dict[str, Direction]:
    """Naive calls the persona model has to beat. None of them ever says flat."""
    calls: dict[str, Direction] = {
        "always_up": "up",
        "momentum": "up" if close.iloc[-1] >= close.iloc[-1 - horizon_days] else "down",
    }
    if regression_return_pct is not None:
        calls["linear_regression"] = "up" if regression_return_pct > 0 else "down"
    return calls


def log_prediction(prediction: Prediction, path: Path = DEFAULT_LOG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _log_lock, path.open("a", encoding="utf-8") as f:
        f.write(prediction.model_dump_json() + "\n")


def load_log(path: Path = DEFAULT_LOG) -> tuple[list[Prediction], int]:
    """Logged predictions, plus a count of lines that no longer parse."""
    if not path.exists():
        return [], 0
    predictions, unreadable = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            predictions.append(Prediction.model_validate_json(line))
        except ValidationError:
            unreadable += 1
    return predictions, unreadable


@dataclass(frozen=True)
class Outcome:
    prediction: Prediction
    resolved_on: date
    return_pct: float
    actual: Direction


def split_factor(splits: pd.Series | None, after: date) -> float:
    """Combined ratio of the splits that took effect after `after` (4.0 for a 4:1 split,
    0.1 for a 1:10 reverse split). `splits` is indexed by date; zero means no split."""
    if splits is None:
        return 1.0
    factor = 1.0
    for day, ratio in splits.items():
        if day > after and ratio > 0:
            factor *= float(ratio)
    return factor


def resolve(
    prediction: Prediction, closes: pd.Series, now: datetime, splits: pd.Series | None = None
) -> Outcome | None:
    """`closes` and `splits` are indexed by date, ascending. None while the horizon is
    still open."""
    as_of = date.fromisoformat(prediction.data_as_of)
    dates = list(closes.index)
    target = bisect_left(dates, as_of) + prediction.horizon_days
    if target >= len(dates):
        return None
    resolved_on = dates[target]
    local_now = now.astimezone(MARKET_TZ)
    if resolved_on > local_now.date() or (
        resolved_on == local_now.date() and local_now.time() < CLOSE_IS_FINAL
    ):
        return None
    if pd.isna(closes.iloc[target]):  # Yahoo hasn't finalised that bar yet: still pending
        return None
    base_price = prediction.last_price / split_factor(splits, as_of)  # into today's share units
    ret = float(closes.iloc[target]) / base_price - 1
    return Outcome(
        prediction=prediction,
        resolved_on=resolved_on,
        return_pct=round(ret * 100, 3),
        actual=classify_move(ret, prediction.flat_band_pct / 100),
    )


def _rate(hits: Iterable[bool]) -> float | None:
    hits = list(hits)
    return round(sum(hits) / len(hits), 4) if hits else None


@dataclass
class Report:
    scored: int
    pending: int
    unreadable: int
    accuracy: dict[str, float | None]  # "personas" plus each baseline, 3-way up/flat/down
    coverage: float | None  # share of persona calls that weren't "unclear"
    accuracy_when_called: float | None
    by_confidence: dict[str, tuple[int, float | None]]  # up/down calls only
    by_strategy: dict[str, float | None]  # individual persona votes
    by_age_band: dict[str, float | None]
    outcomes: list[Outcome] = field(default_factory=list)
    by_mode: dict[str, float | None] = field(default_factory=dict)  # persona votes per reasoning mode
    by_model: dict[str, float | None] = field(default_factory=dict)
    strategy_weights: dict[str, float] = field(default_factory=dict)  # for --weights auto


def derive_strategy_weights(
    votes: Mapping[str, Sequence[bool]], prior_votes: int = PRIOR_VOTES
) -> dict[str, float]:
    """`predict(strategy_weights=...)` from each strategy's scored persona votes.

    Each strategy's hit rate is shrunk toward the pooled hit rate by `prior_votes`
    pseudo-votes and divided by the pooled rate: about 1.0 for an average strategy
    or one with few votes, above 1 for one that's right more often. Never zero.
    """
    total = sum(len(v) for v in votes.values())
    hits = sum(sum(v) for v in votes.values())
    if not total or not hits:
        return {}
    pooled = hits / total
    return {
        s: round((sum(v) + prior_votes * pooled) / (len(v) + prior_votes) / pooled, 3)
        for s, v in sorted(votes.items())
    }


def score(
    predictions: Sequence[Prediction],
    closes_by_ticker: dict[str, pd.Series],
    now: datetime,
    splits_by_ticker: Mapping[str, pd.Series] | None = None,
) -> Report:
    splits_by_ticker = splits_by_ticker or {}
    outcomes = []
    for p in predictions:
        closes = closes_by_ticker.get(p.ticker)
        outcome = (
            resolve(p, closes, now, splits_by_ticker.get(p.ticker)) if closes is not None else None
        )
        if outcome is not None:
            outcomes.append(outcome)

    baseline_names = sorted({name for o in outcomes for name in o.prediction.baselines})
    accuracy = {"personas": _rate(o.prediction.direction == o.actual for o in outcomes)}
    for name in baseline_names:
        accuracy[name] = _rate(
            o.prediction.baselines[name] == o.actual
            for o in outcomes
            if name in o.prediction.baselines
        )

    called = [o for o in outcomes if o.prediction.direction != "unclear"]
    directional = [o for o in outcomes if o.prediction.direction in ("up", "down")]
    by_confidence = {}
    for low, high in CONFIDENCE_BUCKETS:
        bucket = [o for o in directional if low <= o.prediction.confidence < high]
        by_confidence[f"{low:.2f}-{min(high, 1):.2f}"] = (
            len(bucket),
            _rate(o.prediction.direction == o.actual for o in bucket),
        )

    votes_by_strategy: dict[str, list[bool]] = defaultdict(list)
    votes_by_age: dict[str, list[bool]] = defaultdict(list)
    votes_by_mode: dict[str, list[bool]] = defaultdict(list)
    votes_by_model: dict[str, list[bool]] = defaultdict(list)
    for o in outcomes:
        for r in o.prediction.personas:
            if r.view is not None:
                votes_by_strategy[r.strategy].append(r.view.direction == o.actual)
                votes_by_age[r.age_band].append(r.view.direction == o.actual)
                votes_by_mode[r.mode].append(r.view.direction == o.actual)
                votes_by_model[r.model or o.prediction.model].append(r.view.direction == o.actual)

    return Report(
        scored=len(outcomes),
        pending=len(predictions) - len(outcomes),
        unreadable=0,
        accuracy=accuracy,
        coverage=round(len(called) / len(outcomes), 4) if outcomes else None,
        accuracy_when_called=_rate(o.prediction.direction == o.actual for o in called),
        by_confidence=by_confidence,
        by_strategy={s: _rate(v) for s, v in sorted(votes_by_strategy.items())},
        by_age_band={a: _rate(v) for a, v in sorted(votes_by_age.items())},
        outcomes=outcomes,
        by_mode={m: _rate(v) for m, v in sorted(votes_by_mode.items())},
        by_model={m: _rate(v) for m, v in sorted(votes_by_model.items())},
        strategy_weights=derive_strategy_weights(votes_by_strategy),
    )


def fetch_history(
    tickers: Iterable[str], since: date
) -> tuple[dict[str, pd.Series], dict[str, pd.Series]]:
    """Daily closes (not dividend-adjusted, to match logged live prices) and split
    ratios, both indexed by plain dates."""
    import yfinance as yf

    closes, splits = {}, {}
    for ticker in sorted(set(tickers)):
        history = yf.Ticker(ticker).history(
            start=since.isoformat(), auto_adjust=False, actions=True
        )
        if history.empty:
            log.warning("no closes for %s; its predictions stay pending", ticker)
            continue
        days = [ts.date() for ts in history.index]
        closes[ticker] = pd.Series(history["Close"].to_numpy(), index=days)
        if "Stock Splits" in history.columns:
            splits[ticker] = pd.Series(history["Stock Splits"].to_numpy(), index=days)
    return closes, splits


def score_log(path: Path = DEFAULT_LOG, now: datetime | None = None) -> Report:
    predictions, unreadable = load_log(path)
    now = now or datetime.now(MARKET_TZ)
    if not predictions:
        report = score([], {}, now)
    else:
        since = min(date.fromisoformat(p.data_as_of) for p in predictions)
        closes, splits = fetch_history((p.ticker for p in predictions), since)
        report = score(predictions, closes, now, splits)
    report.unreadable = unreadable
    return report
