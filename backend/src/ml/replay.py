"""Backdated forecasts through the real pipeline, scored against the closes that followed.

The only offline estimate of the application's accuracy. It is a floor and not
live accuracy, for three reasons:

- Only prices can be cut back to a past date, so the replayed app sees prices,
  the S&P 500, Nasdaq-100, VIX, the sector ETF and Treasury yields, and nothing
  else. Fundamentals, analysts, insiders, options, earnings dates, headlines and
  documents are today's values, so they are withheld and listed as unavailable
  (`BLIND_SOURCES`). The live app has them.
- The LLM may have seen the period. Replay only dates after its training cutoff
  (`--after`), which this module can't know.
- Tickers on one day are strongly correlated, so a replay holds far fewer
  independent samples than rows. `cluster_ci` resamples whole dates.

Prices are raw closes (split-adjusted by Yahoo, not dividend-adjusted), because
that is what the scorer compares against. A dividend-adjusted history would put
the entry price below the traded one and push returns up.

Replays go to their own JSONL file, never the live log or the database
(`ml/spec.md`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from ai.agents import PROMPT_VERSION
from ai.evaluation import Outcome, load_log, log_prediction
from ai.llm import JsonLLM
from ai.main import predict
from ai.schemas import Prediction
from ai.tool import NASDAQ_PROXY, SECTOR_ETFS, SP500_PROXY, VIX, MarketSnapshot
from finance.macro import YIELD_TICKERS

log = logging.getLogger(__name__)

HISTORY_YEARS = 5
MIN_HISTORY = 300  # sessions: a year of volatility for the band, plus the regression's warm-up
YIELD_SESSIONS = 63  # about the 3 months the live snapshot carries
STATIC_INFO = ("shortName", "longName", "sector", "quoteType")  # classification, not a market value

# Snapshot sources the replay can't supply point-in-time. Named as `fetch_snapshot`
# names them, so personas see the same `unavailable_sources` they would live.
BLIND_SOURCES = (
    "intraday", "income_stmt", "balance_sheet", "cashflow", "quarterly_income",
    "quarterly_balance", "earnings_history", "insiders", "institutions", "eps_trend",
    "eps_revisions", "price_targets", "rating_changes", "options", "news", "calendar", "labor",
)
BLIND_REASON = "not stored point-in-time, so a replay can't supply it"
COLUMNS = ("Open", "High", "Low", "Close", "Volume")
PRICE_COLUMNS = ("Open", "High", "Low", "Close")


@dataclass(frozen=True)
class ReplayTask:
    ticker: str
    as_of: date
    horizon: int


@dataclass
class ReplayRun:
    done: int = 0
    skipped: int = 0  # already in the output file
    failed: list[tuple[ReplayTask, str]] = field(default_factory=list)
    unavailable: list[tuple[ReplayTask, str]] = field(default_factory=list)  # no usable history that day
    aborted: str | None = None


# --- which days -----------------------------------------------------------------


def replay_sessions(
    now: datetime, max_horizon: int, count: int, step: int, after: date | None = None
) -> list[date]:
    """Forecast dates, oldest first: every `step`th NYSE session counting back from the
    newest one whose `max_horizon`-day outcome has settled by `now`. With `step` at
    least the longest horizon the outcome windows don't overlap."""
    if count < 1 or step < 1 or max_horizon < 1:
        raise ValueError("count, step and horizon must each be at least 1")
    calendar = xcals.get_calendar("XNYS")
    session = calendar.date_to_session(pd.Timestamp(now.date()), direction="previous")
    if pd.Timestamp(now) < calendar.session_close(session) + pd.Timedelta(minutes=30):
        session = calendar.previous_session(session)
    newest = calendar.session_offset(session, -max_horizon)
    dates = [calendar.session_offset(newest, -step * k).date() for k in range(count)]
    return sorted(d for d in dates if after is None or d >= after)


# --- the as-of view of prices ---------------------------------------------------


@dataclass
class PriceBook:
    """Raw daily bars per symbol and each symbol's stock splits, fetched once."""

    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    splits: dict[str, dict[date, float]] = field(default_factory=dict)
    sectors: dict[str, str | None] = field(default_factory=dict)  # ticker -> yfinance sector
    names: dict[str, str | None] = field(default_factory=dict)


def as_of_view(frame: pd.DataFrame, as_of: date, splits: Mapping[date, float]) -> pd.DataFrame:
    """The bars up to `as_of`, in the share units traded then.

    Yahoo restates earlier prices for later splits, but the scorer restores every
    split after the forecast date itself, so the logged entry price has to be in
    the units of its own day or the split would be counted twice."""
    cut = frame[frame.index.date <= as_of].copy()
    factor = float(np.prod([r for d, r in splits.items() if d > as_of])) if splits else 1.0
    if factor != 1.0:
        cut[list(PRICE_COLUMNS)] = cut[list(PRICE_COLUMNS)] * factor
        cut["Volume"] = cut["Volume"] / factor
    return cut


def _fetch_raw(symbol: str) -> pd.DataFrame:
    import yfinance as yf

    return yf.Ticker(symbol).history(period=f"{HISTORY_YEARS}y", auto_adjust=False, actions=True)


def _fetch_sector(ticker: str) -> tuple[str | None, str | None]:
    import yfinance as yf

    info = yf.Ticker(ticker).info or {}
    return info.get("sector"), info.get("shortName") or info.get("longName")


def fetch_price_book(
    tickers: Sequence[str],
    fetch: Callable[[str], pd.DataFrame] = _fetch_raw,
    sector_of: Callable[[str], tuple[str | None, str | None]] = _fetch_sector,
) -> tuple[PriceBook, dict[str, str]]:
    """Histories for the tickers, the market proxies, the sector ETFs they need and the
    Treasury yields. Returns the book and why any ticker was left out."""
    book, problems = PriceBook(), {}

    def load(symbol: str) -> bool:
        if symbol in book.frames:
            return True
        try:
            frame = fetch(symbol)
        except Exception as exc:  # one symbol must not stop the run
            problems[symbol] = f"{type(exc).__name__}: {exc}"
            return False
        if frame is None or frame.empty or "Close" not in frame:
            problems[symbol] = "no price history"
            return False
        actions = frame["Stock Splits"] if "Stock Splits" in frame else pd.Series(dtype=float)
        book.splits[symbol] = {ts.date(): float(v) for ts, v in actions.items() if v and v > 0}
        book.frames[symbol] = frame[[c for c in COLUMNS if c in frame]].dropna(subset=["Close"])
        return True

    for symbol in (SP500_PROXY, NASDAQ_PROXY, VIX, *YIELD_TICKERS.values()):
        load(symbol)
    for ticker in tickers:
        if not load(ticker):
            continue
        try:
            book.sectors[ticker], book.names[ticker] = sector_of(ticker)
        except Exception as exc:
            book.sectors[ticker], book.names[ticker] = None, None
            log.warning("no sector for %s: %s", ticker, type(exc).__name__)
        if etf := SECTOR_ETFS.get(book.sectors[ticker]):
            load(etf)
    return book, problems


def blind_snapshot(ticker: str, as_of: date, book: PriceBook) -> MarketSnapshot:
    """A `MarketSnapshot` as of the close of `as_of`: price-derived inputs only.

    Raises ValueError when the ticker has too little history, or didn't trade on
    `as_of`, to forecast from."""
    daily = as_of_view(book.frames[ticker], as_of, book.splits.get(ticker, {}))
    if len(daily) < MIN_HISTORY:
        raise ValueError(f"only {len(daily)} sessions of history, need {MIN_HISTORY}")
    if daily.index[-1].date() != as_of:
        raise ValueError(f"no bar for {as_of} (last is {daily.index[-1].date()})")

    def proxy(symbol: str | None) -> pd.DataFrame | None:
        if symbol is None or symbol not in book.frames:
            return None
        view = as_of_view(book.frames[symbol], as_of, book.splits.get(symbol, {}))
        return view if len(view) else None

    sector_etf = SECTOR_ETFS.get(book.sectors.get(ticker))
    yields = {}
    for tenor, symbol in YIELD_TICKERS.items():
        if symbol in book.frames:
            closes = book.frames[symbol]["Close"]
            closes = closes[closes.index.date <= as_of].dropna().iloc[-YIELD_SESSIONS:]
            if len(closes):
                yields[tenor] = closes
    sector = book.sectors.get(ticker)
    info = {"sector": sector, "shortName": book.names.get(ticker), "quoteType": "EQUITY"}
    return MarketSnapshot(
        ticker=ticker,
        fetched_at=datetime.combine(as_of, datetime.min.time(), timezone.utc),
        daily=daily,
        last_price=float(daily["Close"].iloc[-1]),
        previous_close=float(daily["Close"].iloc[-2]),
        intraday=None,  # bars after the pretend date would leak the outcome
        market_daily=proxy(SP500_PROXY),
        nasdaq_daily=proxy(NASDAQ_PROXY),
        sector_etf=sector_etf if proxy(sector_etf) is not None else None,
        sector_daily=proxy(sector_etf),
        vix_daily=proxy(VIX),
        info={k: v for k, v in info.items() if k in STATIC_INFO and v},
        yields=yields,
        errors={name: BLIND_REASON for name in BLIND_SOURCES},
    )


# --- running --------------------------------------------------------------------


def plan(tickers: Sequence[str], dates: Sequence[date], horizons: Sequence[int]) -> list[ReplayTask]:
    return [ReplayTask(t, d, h) for d in dates for t in tickers for h in horizons]


def done_keys(path: Path) -> set[tuple[str, str, int, str, str]]:
    """(ticker, data date, horizon, prompt version, model) of forecasts already in `path`."""
    predictions, _ = load_log(path)
    return {(p.ticker, p.data_as_of, p.horizon_days, p.prompt_version, p.model) for p in predictions}


async def run_replay(
    tasks: Sequence[ReplayTask],
    book: PriceBook,
    llm: JsonLLM,
    out: Path,
    *,
    age_bands: list[str] | None = None,
    concurrency: int = 2,
    max_failures: int = 5,
    progress: Callable[[str], None] = lambda _: None,
) -> ReplayRun:
    """Forecast every task not already in `out`, appending each as it finishes so an
    interrupted run resumes. Stops after `max_failures` forecasts in a row fail (a
    spent quota would otherwise burn through the whole plan)."""
    run = ReplayRun()
    seen = done_keys(out)
    pending = []
    for task in tasks:
        if (task.ticker, task.as_of.isoformat(), task.horizon, PROMPT_VERSION, llm.model) in seen:
            run.skipped += 1
        else:
            pending.append(task)
    gate = asyncio.Semaphore(max(1, concurrency))
    streak = 0
    total = len(pending)

    async def one(task: ReplayTask) -> None:
        nonlocal streak
        if run.aborted:
            return
        try:
            snapshot = blind_snapshot(task.ticker, task.as_of, book)
        except (KeyError, ValueError) as exc:
            run.unavailable.append((task, str(exc) or "no price history"))
            return
        async with gate:
            if run.aborted:
                return
            try:
                prediction = await predict(
                    task.ticker, horizon_days=task.horizon, age_bands=age_bands, llm=llm,
                    snapshot=snapshot, documents_by_strategy={},
                )
            except (RuntimeError, ValueError) as exc:
                streak += 1
                run.failed.append((task, f"{type(exc).__name__}: {exc}"))
                if streak >= max_failures:
                    run.aborted = f"{streak} forecasts in a row failed; last: {exc}"
                return
        streak = 0
        prediction.data_warnings.append(
            f"replay: backdated to {task.as_of}, prices only; not live accuracy (ml/replay.py)"
        )
        log_prediction(prediction, out)
        run.done += 1
        progress(f"[{run.done}/{total}] {task.ticker} {task.as_of} {task.horizon}d -> "
                 f"{prediction.direction} ({prediction.confidence:.2f})")

    await asyncio.gather(*(one(t) for t in pending))
    return run


# --- how sure the estimate is ---------------------------------------------------


@dataclass(frozen=True)
class Estimate:
    mean: float
    low: float
    high: float
    n: int
    clusters: int


def cluster_ci(
    values: Sequence[float], groups: Sequence, draws: int = 2000, seed: int = 0
) -> Estimate:
    """Mean of `values` and a 95% interval from resampling whole `groups` (forecast
    dates), because tickers on one date move together and aren't independent."""
    values = np.asarray(values, dtype=float)
    if not len(values):
        return Estimate(float("nan"), float("nan"), float("nan"), 0, 0)
    labels, inverse = np.unique(np.asarray(groups).astype(str), return_inverse=True)
    sums = np.bincount(inverse, weights=values)
    counts = np.bincount(inverse).astype(float)
    picks = np.random.default_rng(seed).integers(0, len(labels), size=(draws, len(labels)))
    boot = sums[picks].sum(axis=1) / counts[picks].sum(axis=1)
    low, high = np.percentile(boot, [2.5, 97.5])
    return Estimate(float(values.mean()), float(low), float(high), len(values), len(labels))


@dataclass(frozen=True)
class Comparison:
    horizon_days: int
    target: str  # "absolute" or "relative"
    n: int
    dates: int
    tickers: int
    personas: Estimate
    always_up: Estimate
    momentum: Estimate
    regression: Estimate | None
    edge_vs_always_up: Estimate  # personas minus always-up, paired on the same rows
    edge_vs_regression: Estimate | None
    called_share: float
    accuracy_when_called: float | None


def compare(outcomes: Sequence[Outcome]) -> list[Comparison]:
    """Per horizon and target: each call's 3-way accuracy on the same rows, with
    date-clustered intervals, and the persona edge over always-up and the regression.
    The relative target is the outcome versus SPY, which always-up can't ride."""
    results = []
    for horizon in sorted({o.prediction.horizon_days for o in outcomes}):
        rows = [o for o in outcomes if o.prediction.horizon_days == horizon]
        for target in ("absolute", "relative"):
            truth = [o.actual if target == "absolute" else o.relative_actual for o in rows]
            use = [(o, t) for o, t in zip(rows, truth) if t is not None]
            if not use:
                continue
            def hit(pick: Callable[[Prediction], str | None]) -> np.ndarray:
                return np.array([pick(o.prediction) == t for o, t in use], dtype=float)

            calls = [o.prediction.withheld_call or o.prediction.direction for o, _ in use]
            personas = np.array([c == t for c, (_, t) in zip(calls, use)], dtype=float)
            up = hit(lambda p: p.baselines.get("always_up"))
            momentum = hit(lambda p: p.baselines.get("momentum"))
            groups = [o.prediction.data_as_of for o, _ in use]
            has_regression = np.array(["linear_regression" in o.prediction.baselines for o, _ in use])
            regression = edge_regression = None
            if has_regression.any():
                reg = hit(lambda p: p.baselines.get("linear_regression"))
                keep = has_regression
                g = np.array(groups)[keep]
                regression = cluster_ci(reg[keep], g)
                edge_regression = cluster_ci(personas[keep] - reg[keep], g)
            called = np.array([c != "unclear" for c in calls])
            results.append(Comparison(
                horizon_days=horizon,
                target=target,
                n=len(use),
                dates=len(set(groups)),
                tickers=len({o.prediction.ticker for o, _ in use}),
                personas=cluster_ci(personas, groups),
                always_up=cluster_ci(up, groups),
                momentum=cluster_ci(momentum, groups),
                regression=regression,
                edge_vs_always_up=cluster_ci(personas - up, groups),
                edge_vs_regression=edge_regression,
                called_share=float(called.mean()),
                accuracy_when_called=float(personas[called].mean()) if called.any() else None,
            ))
    return results


@dataclass(frozen=True)
class RunComparison:
    horizon_days: int
    n: int
    dates: int
    this_run: Estimate
    other_run: Estimate
    always_up: Estimate
    change: Estimate  # this run minus the other, paired on the same ticker, date and horizon


def compare_runs(outcomes: Sequence[Outcome], other: Sequence[Outcome]) -> list[RunComparison]:
    """Two replays of the same tickers and dates (say, two prompt versions) on the
    rows both have scored, with intervals that resample whole dates. A change that
    can't be told from zero is the honest answer for a replay this small."""
    def call(o: Outcome) -> str:
        return o.prediction.withheld_call or o.prediction.direction

    def key(o: Outcome) -> tuple[str, str, int]:
        return o.prediction.ticker, o.prediction.data_as_of, o.prediction.horizon_days

    theirs = {key(o): o for o in other}
    results = []
    for horizon in sorted({o.prediction.horizon_days for o in outcomes}):
        pairs = [(o, theirs[key(o)]) for o in outcomes
                 if o.prediction.horizon_days == horizon and key(o) in theirs]
        if not pairs:
            continue
        mine = np.array([call(a) == a.actual for a, _ in pairs], dtype=float)
        base = np.array([call(b) == b.actual for _, b in pairs], dtype=float)
        up = np.array([a.prediction.baselines.get("always_up") == a.actual for a, _ in pairs], dtype=float)
        groups = [a.prediction.data_as_of for a, _ in pairs]
        results.append(RunComparison(
            horizon_days=horizon, n=len(pairs), dates=len(set(groups)),
            this_run=cluster_ci(mine, groups), other_run=cluster_ci(base, groups),
            always_up=cluster_ci(up, groups), change=cluster_ci(mine - base, groups),
        ))
    return results


def verdict(edge: Estimate, margin: float = 0.025) -> str:
    """Plain words for an edge over always-up: the 95% interval against zero and the
    gate's margin (`walkforward.GATE_MARGIN`)."""
    if edge.n == 0:
        return "no rows"
    if edge.low > margin:
        return "clears the gate margin"
    if edge.low > 0:
        return "ahead of always-up, but not by the gate margin"
    if edge.high < 0:
        return "behind always-up"
    return "can't be told apart from always-up"


def default_horizon_note(step: int, horizons: Sequence[int]) -> str | None:
    if step < max(horizons):
        return (f"step {step} is shorter than the {max(horizons)}-day horizon, so outcome windows "
                "overlap and the date-clustered interval is optimistic")
    return None
