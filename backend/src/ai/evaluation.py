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
its 10:1 split). The logged price is in the share units of its data date, so
`resolve` multiplies the provider close by every split after that date.
Outcome dates come from the NYSE calendar (holidays are not sessions); a
missing bar, unsettled session or unverified basis leaves a prediction pending,
and `assess` says why in plain words (`Pending.detail`), e.g. which holiday the
horizon skips or which session has no price yet.

The scorer also suggests strategy weights from each strategy's scored votes;
`python main.py AAPL --weights auto` feeds them back into `predict()`.

Relative outcome: when SPY closes are supplied, each outcome also records the
stock's return relative to SPY over the same sessions, classified with the
prediction's own flat band (`Report.relative`). Always-up can't ride a rising
market there, so it shows whether a call carries stock-specific information.

The log rotates by year once it passes `ROTATE_BYTES` (`predictions-2026.jsonl`);
`load_log` reads the live file and every archive, so no scored history is lost.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
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
STABILITY_BUCKETS = ((0.0, 0.5), (0.5, 0.75), (0.75, 1.01))
BENCHMARK = "SPY"  # the relative outcome's reference, as in ml's relative target
ROTATE_BYTES = 100 * 1024 * 1024
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


def log_files(path: Path = DEFAULT_LOG) -> list[Path]:
    """The yearly archives (`predictions-2026.jsonl`), oldest first, then the live log."""
    archives = sorted(path.parent.glob(f"{path.stem}-[0-9][0-9][0-9][0-9]{path.suffix}"))
    return [*archives, path]


def _line_year(line: str, fallback: int) -> int:
    try:
        year = str(json.loads(line).get("generated_at", ""))[:4]
    except (ValueError, AttributeError):
        return fallback
    return int(year) if year.isdigit() else fallback


def rotate_log(path: Path = DEFAULT_LOG, max_bytes: int = ROTATE_BYTES) -> list[Path]:
    """Move the live log into yearly archives once it passes `max_bytes`.

    Each line goes to `<stem>-<year of generated_at>.jsonl` (appended, so a busy
    year can rotate more than once); unreadable lines go to this year's archive
    rather than being dropped. Archives are written before the live log is
    emptied, so a crash in between duplicates lines, which `load_log` skips by
    prediction id, instead of losing them. Returns the archives written to.
    """
    if not path.exists() or path.stat().st_size <= max_bytes:
        return []
    this_year = datetime.now(MARKET_TZ).year
    by_year: dict[int, list[str]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            by_year[_line_year(line, this_year)].append(line)
    written = []
    for year, lines in sorted(by_year.items()):
        archive = path.with_name(f"{path.stem}-{year}{path.suffix}")
        with archive.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        written.append(archive)
    path.write_text("", encoding="utf-8")
    log.info("rotated %s into %s", path.name, ", ".join(a.name for a in written))
    return written


def log_prediction(prediction: Prediction, path: Path = DEFAULT_LOG,
                   max_bytes: int = ROTATE_BYTES) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _log_lock:
        rotate_log(path, max_bytes)
        with path.open("a", encoding="utf-8") as f:
            f.write(prediction.model_dump_json() + "\n")


def load_log(path: Path = DEFAULT_LOG) -> tuple[list[Prediction], int]:
    """Logged predictions from the live log and its yearly archives, plus a count of
    lines that no longer parse. A prediction id seen twice is kept once."""
    predictions, unreadable, seen = [], 0, set()
    for file in log_files(path):
        if not file.exists():
            continue
        for line in file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                prediction = Prediction.model_validate_json(line)
            except ValidationError:
                unreadable += 1
                continue
            if prediction.id not in seen:
                seen.add(prediction.id)
                predictions.append(prediction)
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
    # Relative to BENCHMARK over the same sessions; None without benchmark closes.
    benchmark_return_pct: float | None = None
    relative_return_pct: float | None = None
    relative_actual: Direction | None = None  # classified with the prediction's flat band


@dataclass(frozen=True)
class Pending:
    """Why a prediction can't be scored yet. `retry_after` is when it next could be."""

    prediction: Prediction
    reason: str  # short code: horizon_open, missing_bar, no_price_data, not_a_session, ...
    detail: str  # one plain sentence for people
    retry_after: datetime | None = None


def _holiday_names(calendar, start: pd.Timestamp, end: pd.Timestamp) -> dict[date, str]:
    names: dict[date, str] = {}
    for rule in calendar.regular_holidays.rules:
        for day in rule.dates(start, end):
            names[day.date()] = rule.name
    for day in calendar.adhoc_holidays:
        if start <= day <= end:
            names.setdefault(day.date(), "unscheduled closure")
    return names


def _closures(calendar, session: pd.Timestamp, target: pd.Timestamp) -> str:
    """Weekday closures and early closes between the data date and the outcome session."""
    names = _holiday_names(calendar, session, target)
    notes = [f"{day.date()} {names.get(day.date(), 'market closed')}"
             for day in pd.bdate_range(session, target)
             if not calendar.is_session(day)]
    notes += [f"{day.date()} early close at {calendar.session_close(day).tz_convert(MARKET_TZ):%H:%M} ET"
              for day in calendar.sessions_in_range(session, target)
              if calendar.session_close(day).tz_convert(MARKET_TZ).time() < time(16)]
    return f" The NYSE calendar accounts for: {'; '.join(notes)}." if notes else ""


def _benchmark_return(benchmark: pd.Series | None, start: date, end: date) -> float | None:
    """Return between two closes of one series. Both share its split adjustment, so
    the ratio is right without restating anything."""
    if benchmark is None or not benchmark.index.is_unique:
        return None
    if start not in benchmark.index or end not in benchmark.index:
        return None
    first, last = float(benchmark.loc[start]), float(benchmark.loc[end])
    if not (math.isfinite(first) and math.isfinite(last)) or first <= 0 or last <= 0:
        return None
    return last / first - 1


def assess(prediction: Prediction, closes: pd.Series | None, now: datetime,
           benchmark: pd.Series | None = None) -> Outcome | Pending:
    """Score one prediction on its exact exchange session, or say why it can't be yet.

    Injected plain Series are assumed to already use the prediction share basis.
    Provider Series must declare their basis and complete corporate actions.
    `benchmark` (BENCHMARK closes) adds the relative outcome when it has both the
    data date and the outcome date; it never makes a prediction pending.
    """
    def pending(reason: str, detail: str, retry_after: datetime | None = None) -> Pending:
        if reason != "horizon_open":
            log.warning("cannot score %s (%s): %s", prediction.ticker, prediction.data_as_of, detail)
        return Pending(prediction, reason, detail, retry_after)

    if now.tzinfo is None:
        return pending("clock", "The scoring clock has no timezone, so the closing time can't be checked.")
    start = date.fromisoformat(prediction.data_as_of)
    if closes is None:
        return pending("no_price_data", f"The price provider returned no history for {prediction.ticker} yet.")
    if closes.attrs.get("calendar", "XNYS") != "XNYS":
        return pending("unsupported_calendar",
                       f"{prediction.ticker} isn't listed on a venue verified to follow the NYSE calendar, "
                       "so its trading days can't be counted reliably.")
    try:
        calendar = xcals.get_calendar("XNYS")
        session = pd.Timestamp(start)
        if not calendar.is_session(session):
            name = _holiday_names(calendar, session, session).get(start)
            why = f"a market holiday ({name})" if name else "a weekend or market holiday"
            return pending("not_a_session", f"The data date {start} was {why}, so the horizon can't be counted from it.")
        target = calendar.session_offset(session, prediction.horizon_days)
        resolved_on = target.date()
        settled_at = calendar.session_close(target) + pd.Timedelta(minutes=30)
    except (ValueError, KeyError, IndexError) as exc:
        return pending("calendar_unavailable",
                       f"The NYSE calendar doesn't cover these dates yet ({type(exc).__name__}).")
    if pd.Timestamp(now) < settled_at:
        settled_local = settled_at.tz_convert(MARKET_TZ)
        return pending(
            "horizon_open",
            f"The {prediction.horizon_days}-trading-day horizon ends on {resolved_on} ({resolved_on:%A}); "
            f"it is scored after {settled_local:%H:%M} ET that day, once the close has settled."
            + _closures(calendar, session, target),
            settled_at.tz_convert(MARKET_TZ).to_pydatetime(),
        )
    if not closes.index.is_unique:
        return pending("duplicate_bars", "The provider returned two prices for the same day.")
    required = [s.date() for s in calendar.sessions_in_range(session, target)]
    missing = [d for d in required if d not in closes.index]
    if missing:
        return pending(
            "missing_bar",
            f"No closing price for {', '.join(map(str, missing))}, although the NYSE was scheduled to trade: "
            "either a gap in the provider's data or an unscheduled closure. It stays pending rather than "
            "scoring against a different day; rerun later.",
        )
    if any(not math.isfinite(float(closes.loc[d])) or float(closes.loc[d]) <= 0 for d in required):
        return pending("invalid_price", "A required closing price is missing or not positive (not finalised yet?).")
    if not math.isfinite(prediction.last_price) or prediction.last_price <= 0:
        return pending("invalid_reference", "The logged entry price is missing or not positive.")
    price = float(closes.loc[resolved_on])
    basis = closes.attrs.get("price_basis", "prediction_share_basis")
    split_factor = 1.0
    if basis == "yahoo_split_adjusted_close":
        if not closes.attrs.get("actions_verified"):
            return pending("corporate_actions",
                           "The provider didn't return split history, so prices can't be put on the logged share basis.")
        # Yahoo's Close is retrospectively split-adjusted even with auto_adjust=False.
        # Restore ALL splits after entry, including those after the outcome date.
        splits = closes.attrs.get("stock_splits")
        if not isinstance(splits, dict):
            return pending("corporate_actions", "The provider's split history is malformed.")
        for split_date, ratio in splits.items():
            try:
                action_date = date.fromisoformat(split_date)
                ratio = float(ratio)
            except (TypeError, ValueError):
                return pending("corporate_actions", "The provider's split history has an unreadable entry.")
            if not math.isfinite(ratio) or ratio <= 0:
                return pending("corporate_actions", "The provider's split history has an invalid ratio.")
            if action_date > start:
                split_factor *= ratio
        price *= split_factor
    elif basis != "prediction_share_basis":
        return pending("unknown_basis", "The price series doesn't say how it is adjusted.")
    ret = price / prediction.last_price - 1
    if not math.isfinite(ret):
        return pending("invalid_price", "The adjusted return isn't a finite number.")
    band = prediction.flat_band_pct / 100
    relative = {}
    # The benchmark relative to itself is always zero: no information.
    bench = None if prediction.ticker == BENCHMARK else _benchmark_return(benchmark, start, resolved_on)
    if bench is not None:
        excess = (1 + ret) / (1 + bench) - 1  # the return of price / benchmark, as in ml's relative target
        relative = dict(benchmark_return_pct=round(bench * 100, 3),
                        relative_return_pct=round(excess * 100, 3),
                        relative_actual=classify_move(excess, band))
    return Outcome(
        prediction=prediction,
        resolved_on=resolved_on,
        return_pct=round(ret * 100, 3),
        actual=classify_move(ret, band),
        actual_price=price,
        reference_price=prediction.last_price,
        split_factor=split_factor,
        **relative,
    )


def resolve(prediction: Prediction, closes: pd.Series, now: datetime) -> Outcome | None:
    """`assess` without the reason: the Outcome, or None while it can't be scored."""
    result = assess(prediction, closes, now)
    return result if isinstance(result, Outcome) else None


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
    pending_details: list[Pending] = field(default_factory=list)  # why each pending one waits
    # Up/down calls by Prediction.stability (share of persona-mode samples matching the
    # call): evidence for whether stability should feed confidence (ai/spec.md).
    by_stability: dict[str, tuple[int, float | None]] = field(default_factory=dict)
    # 3-way accuracy against the outcome relative to BENCHMARK: {"benchmark", "scored", "accuracy"}.
    relative: dict = field(default_factory=dict)


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
) -> Report:
    outcomes, waiting = [], []
    benchmark = closes_by_ticker.get(BENCHMARK)
    for p in predictions:
        result = assess(p, closes_by_ticker.get(p.ticker), now, benchmark)
        (outcomes if isinstance(result, Outcome) else waiting).append(result)

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
    by_stability = {}
    rated = [o for o in directional if o.prediction.stability is not None]
    for low, high in STABILITY_BUCKETS:
        bucket = [o for o in rated if low <= o.prediction.stability < high]
        by_stability[f"{low:.2f}-{min(high, 1):.2f}"] = (
            len(bucket),
            _rate(o.prediction.direction == o.actual for o in bucket),
        )

    relative_outcomes = [o for o in outcomes if o.relative_actual is not None]
    relative = {}
    if relative_outcomes:
        relative_accuracy = {
            "personas": _rate(o.prediction.direction == o.relative_actual for o in relative_outcomes)
        }
        for name in baseline_names:
            relative_accuracy[name] = _rate(
                o.prediction.baselines[name] == o.relative_actual
                for o in relative_outcomes
                if name in o.prediction.baselines
            )
        relative = {"benchmark": BENCHMARK, "scored": len(relative_outcomes),
                    "accuracy": relative_accuracy}

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
        pending_details=waiting,
        by_stability=by_stability,
        relative=relative,
    )


def scoring_tickers(predictions: Iterable[Prediction]) -> set[str]:
    """Every ticker whose closes scoring needs: the predicted ones plus BENCHMARK."""
    return {p.ticker for p in predictions} | {BENCHMARK}


def fetch_closes(tickers: Iterable[str], since: date) -> dict[str, pd.Series]:
    """Yahoo split-adjusted closes with explicit action and exchange provenance."""
    import yfinance as yf

    closes = {}
    for ticker in sorted(set(tickers)):
        handle = yf.Ticker(ticker)
        history = handle.history(start=since.isoformat(), auto_adjust=False, actions=True)
        if history.empty:
            log.warning("no closes for %s; its predictions stay pending", ticker)
            continue
        series = pd.Series(
            history["Close"].to_numpy(), index=[ts.date() for ts in history.index]
        )
        metadata = handle.get_history_metadata()
        # Only supported US equity venues share the XNYS session calendar here.
        # yfinance returns a HistoryMetadata Mapping, not a dict.
        exchange = metadata.get("exchangeName") if isinstance(metadata, Mapping) else None
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
        report = score(predictions, fetch_closes(scoring_tickers(predictions), since), now)
    report.unreadable = unreadable
    return report
