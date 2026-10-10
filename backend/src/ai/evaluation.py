"""Prediction log and scorer: is the persona model better than naive baselines?

Every prediction is appended to a JSONL log together with baseline calls made
at the same moment. Once a prediction's horizon has passed, the scorer takes
the close N trading days after its data date, classifies the move with the
flat band logged at prediction time, and scores the persona call and each
baseline on the same three-way up / flat / down outcome.

Score only live-logged predictions: replaying history through the LLM leaks
outcomes it may have seen in training.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import math

import exchange_calendars as xcals
import pandas as pd
from pydantic import ValidationError

from ai.schemas import Direction, Prediction
from finance.indicators import classify_move

DEFAULT_LOG = Path(__file__).resolve().parents[2] / "data" / "predictions.jsonl"
MARKET_TZ = ZoneInfo("America/New_York")
CLOSE_IS_FINAL = time(16, 30)  # daily bars are settled a little after the 16:00 close
CONFIDENCE_BUCKETS = ((0.0, 0.25), (0.25, 0.5), (0.5, 1.01))

log = logging.getLogger(__name__)


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
    with path.open("a", encoding="utf-8") as f:
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
    actual_price: float | None = None
    price_basis: str = "prediction_share_basis"
    reference_price: float | None = None
    split_factor: float = 1.0  # provider close x split_factor = price in the logged share basis


def resolve(prediction: Prediction, closes: pd.Series, now: datetime) -> Outcome | None:
    """Resolve an exact exchange session, preserving the logged entry price.

    Injected plain Series are assumed to already use the prediction share basis.
    Provider Series must declare their basis and complete corporate actions.
    """
    def refuse(reason: str) -> None:
        log.warning("cannot score %s (%s): %s", prediction.ticker, prediction.data_as_of, reason)
        return None

    if now.tzinfo is None:
        return refuse("scoring time must be timezone-aware")
    start = date.fromisoformat(prediction.data_as_of)
    calendar_name = closes.attrs.get("calendar", "XNYS")
    if calendar_name != "XNYS":
        return refuse("unsupported or unverified exchange calendar")
    try:
        calendar = xcals.get_calendar("XNYS")
        session = pd.Timestamp(start)
        if not calendar.is_session(session):
            return refuse("data date is not an exchange session")
        target = calendar.session_offset(session, prediction.horizon_days)
        resolved_on = target.date()
        settled_at = calendar.session_close(target) + pd.Timedelta(minutes=30)
    except (ValueError, KeyError, IndexError) as exc:
        return refuse(f"exchange session unavailable: {exc}")
    if pd.Timestamp(now) < settled_at:
        return None
    if not closes.index.is_unique:
        return refuse("duplicate daily bars")
    required = [s.date() for s in calendar.sessions_in_range(session, target)]
    if any(d not in closes.index for d in required):
        return refuse("missing required exchange-session bar")
    if any(not math.isfinite(float(closes.loc[d])) or float(closes.loc[d]) <= 0 for d in required):
        return refuse("invalid daily price")
    if not math.isfinite(prediction.last_price) or prediction.last_price <= 0:
        return refuse("invalid logged reference price")
    price = float(closes.loc[resolved_on])
    basis = closes.attrs.get("price_basis", "prediction_share_basis")
    split_factor = 1.0
    if basis == "yahoo_split_adjusted_close":
        if not closes.attrs.get("actions_verified"):
            return refuse("corporate-action history is unavailable")
        # Yahoo's Close is retrospectively split-adjusted even with auto_adjust=False.
        # Restore ALL splits after entry, including those after the outcome date.
        splits = closes.attrs.get("stock_splits")
        if not isinstance(splits, dict):
            return refuse("corporate-action history is malformed")
        for split_date, ratio in splits.items():
            try:
                action_date = date.fromisoformat(split_date)
                ratio = float(ratio)
            except (TypeError, ValueError):
                return refuse("invalid split action")
            if not math.isfinite(ratio) or ratio <= 0:
                return refuse("invalid split ratio")
            if action_date > start:
                split_factor *= ratio
        price *= split_factor
    elif basis != "prediction_share_basis":
        return refuse("unknown price adjustment basis")
    ret = price / prediction.last_price - 1
    if not math.isfinite(ret):
        return refuse("invalid adjusted return")
    return Outcome(
        prediction=prediction,
        resolved_on=resolved_on,
        return_pct=round(ret * 100, 3),
        actual=classify_move(ret, prediction.flat_band_pct / 100),
        actual_price=price,
        reference_price=prediction.last_price,
        split_factor=split_factor,
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


def score(
    predictions: Sequence[Prediction], closes_by_ticker: dict[str, pd.Series], now: datetime
) -> Report:
    outcomes = []
    for p in predictions:
        closes = closes_by_ticker.get(p.ticker)
        outcome = resolve(p, closes, now) if closes is not None else None
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
    for o in outcomes:
        for r in o.prediction.personas:
            if r.view is not None:
                votes_by_strategy[r.strategy].append(r.view.direction == o.actual)
                votes_by_age[r.age_band].append(r.view.direction == o.actual)

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
    )


def fetch_closes(tickers: Iterable[str], since: date) -> dict[str, pd.Series]:
    """Yahoo split-adjusted closes with explicit action and exchange provenance."""
    import yfinance as yf

    closes = {}
    for ticker in sorted(set(tickers)):
        history = yf.Ticker(ticker).history(start=since.isoformat(), auto_adjust=False, actions=True)
        if history.empty:
            log.warning("no closes for %s; its predictions stay pending", ticker)
            continue
        series = pd.Series(
            history["Close"].to_numpy(), index=[ts.date() for ts in history.index]
        )
        metadata = yf.Ticker(ticker).get_history_metadata()
        # Only supported US equity venues share the XNYS session calendar here.
        exchange = metadata.get("exchangeName") if isinstance(metadata, dict) else None
        series.attrs.update(
            price_basis="yahoo_split_adjusted_close",
            actions_verified="Stock Splits" in history.columns,
            calendar="XNYS" if exchange in {"NYQ", "NMS", "NGM", "NCM", "ASE", "PCX", "BTS"} else None,
            stock_splits={ts.date().isoformat(): float(v) for ts, v in history.get("Stock Splits", pd.Series(dtype=float)).items() if v != 0},
        )
        closes[ticker] = series
    return closes


def score_log(path: Path = DEFAULT_LOG, now: datetime | None = None) -> Report:
    predictions, unreadable = load_log(path)
    now = now or datetime.now(MARKET_TZ)
    if not predictions:
        report = score([], {}, now)
    else:
        since = min(date.fromisoformat(p.data_as_of) for p in predictions)
        report = score(predictions, fetch_closes((p.ticker for p in predictions), since), now)
    report.unreadable = unreadable
    return report
