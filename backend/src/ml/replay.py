"""Replay recent sessions through the personas, score them, and train on the result.

`replay` forecasts each ticker as of each of the last N settled sessions, using
only what can honestly be cut back to that date (prices), then scores the
forecasts against the real closes that followed and fits model B on them.
`collect` is the clean counterpart: a live forecast, logged for scoring later.

A replay is a pipeline check and a way to pre-adjust weights, NOT live
accuracy (ml/spec.md, "Notes from the database merge"): fundamentals,
analyst data, insiders, options, headlines and filings are today's values, so
they are removed rather than left to leak the outcome; the LLM may have seen
the period in training; and tickers on the same day are strongly correlated.
Replays go to their own JSONL file and never to the live log or the database.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from ai.evaluation import DEFAULT_LOG, MARKET_TZ, Report, load_log, log_prediction, score_log
from ai.llm import JsonLLM, build_llm
from ai.main import predict
from ai.schemas import Prediction
from ai.tool import MarketSnapshot, fetch_snapshot
from ml.dataset import stacker_rows
from ml.model import make_model
from ml.store import save
from ml.walkforward import StackerReport, evaluate_stacker

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_REPLAY_FILE = DATA_DIR / "replay.jsonl"
DEFAULT_WEIGHTS_FILE = DATA_DIR / "replay-weights.json"
REPLAY_AGE_BAND = "25-39"  # eligible for every strategy: 3 personas, one per strategy
REPLAY_WARNING = "replay"  # prefix of the data_warnings line that marks a backdated forecast
# Identity, not valuation: safe to keep when the rest of `info` is today's.
_KEEP_INFO = ("sector", "industry", "shortName", "longName", "quoteType", "exchange", "currency", "country")


# --- backdating ------------------------------------------------------------------


def backdate_snapshot(snapshot: MarketSnapshot, as_of: date) -> MarketSnapshot:
    """`snapshot` as it could have looked after the close of `as_of`.

    Prices are cut to `as_of`. Everything else a provider only serves as of now
    (fundamentals, analyst data, insiders, institutions, options, headlines,
    earnings calendar, yields, labour data) is dropped, so it can't leak the
    outcome into the persona call or `Prediction.features`.
    """

    def cut(frame: pd.DataFrame | None) -> pd.DataFrame | None:
        return None if frame is None else frame[frame.index.date <= as_of]

    daily = cut(snapshot.daily)
    if daily is None or len(daily) < 2 or daily.index[-1].date() != as_of:
        raise ValueError(f"{snapshot.ticker}: no daily bar on {as_of}")
    close = daily["Close"]
    errors = dict(snapshot.errors)
    errors[REPLAY_WARNING] = (
        f"backdated to {as_of}: prices cut back; fundamentals, analyst data, insiders, options "
        "and headlines removed (only today's values exist). Not live accuracy."
    )
    return dataclasses.replace(
        snapshot,
        fetched_at=datetime.combine(as_of, time.min, timezone.utc),
        daily=daily,
        last_price=float(close.iloc[-1]),
        previous_close=float(close.iloc[-2]),
        intraday=None,
        market_daily=cut(snapshot.market_daily),
        nasdaq_daily=cut(snapshot.nasdaq_daily),
        sector_daily=cut(snapshot.sector_daily),
        vix_daily=cut(snapshot.vix_daily),
        info={k: v for k, v in snapshot.info.items() if k in _KEEP_INFO},
        income_stmt=None,
        balance_sheet=None,
        cashflow=None,
        quarterly_income=None,
        quarterly_balance=None,
        earnings_history=None,
        insider_purchases=None,
        institutional_holders=None,
        eps_trend=None,
        eps_revisions=None,
        price_targets={},
        rating_changes=None,
        options=None,
        headlines=[],
        news=[],
        earnings_dates=[],
        yields={},
        labor={},
        quote_source="replay",
        errors=errors,
    )


def last_settled_session(now: datetime) -> pd.Timestamp:
    calendar = xcals.get_calendar("XNYS")
    session = calendar.date_to_session(pd.Timestamp(now.date()), direction="previous")
    if pd.Timestamp(now) < calendar.session_close(session) + pd.Timedelta(minutes=30):
        session = calendar.previous_session(session)
    return session


def replay_dates(horizon_days: int, sessions: int, now: datetime) -> list[date]:
    """The `sessions` most recent as-of dates whose `horizon_days` outcome has settled."""
    calendar = xcals.get_calendar("XNYS")
    last = calendar.session_offset(last_settled_session(now), -horizon_days)
    window = calendar.sessions_window(last, -sessions)
    return [s.date() for s in window]


def is_replay(prediction: Prediction) -> bool:
    return any(w.startswith(f"{REPLAY_WARNING}:") for w in prediction.data_warnings)


# --- running ---------------------------------------------------------------------


@dataclass
class RunSummary:
    requested: int = 0
    skipped_done: int = 0
    saved: int = 0
    failed: dict[str, str] = field(default_factory=dict)  # "TICKER hN date" -> why


def _key(ticker: str, horizon: int, as_of: str) -> tuple[str, int, str]:
    return ticker.upper(), horizon, as_of


async def run_replay(
    tickers: Sequence[str],
    horizons: Sequence[int],
    sessions: int,
    age_bands: Sequence[str],
    path: Path,
    concurrency: int = 4,
    llm: JsonLLM | None = None,
    now: datetime | None = None,
) -> RunSummary:
    """Forecast every (ticker, horizon, as-of session) not already in `path`.

    Resumable: forecasts already in the file are skipped, so a run cut short by a
    quota limit continues where it stopped and spends nothing twice.
    """
    now = now or datetime.now(MARKET_TZ)
    llm = llm or build_llm()
    done = {_key(p.ticker, p.horizon_days, p.data_as_of) for p in load_log(path)[0]} if path.exists() else set()
    summary = RunSummary()
    gate = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()

    async def one(ticker: str, snapshot: MarketSnapshot, horizon: int, as_of: date) -> None:
        name = f"{ticker} h{horizon} {as_of}"
        async with gate:
            try:
                prediction = await predict(
                    ticker,
                    horizon_days=horizon,
                    age_bands=list(age_bands),
                    llm=llm,
                    snapshot=backdate_snapshot(snapshot, as_of),
                    documents_by_strategy={},
                )
            except Exception as exc:  # one failed forecast mustn't stop the run
                summary.failed[name] = f"{type(exc).__name__}: {exc}"
                return
        async with lock:
            log_prediction(prediction, path)
            summary.saved += 1

    async def for_ticker(ticker: str) -> None:
        jobs = []
        for horizon in horizons:
            for as_of in replay_dates(horizon, sessions, now):
                summary.requested += 1
                if _key(ticker, horizon, str(as_of)) in done:
                    summary.skipped_done += 1
                else:
                    jobs.append((horizon, as_of))
        if not jobs:
            return
        try:
            snapshot = await asyncio.to_thread(fetch_snapshot, ticker)
        except Exception as exc:
            summary.failed[ticker] = f"{type(exc).__name__}: {exc}"
            return
        await asyncio.gather(*(one(ticker, snapshot, h, d) for h, d in jobs))

    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.gather(*(for_ticker(t.upper()) for t in dict.fromkeys(tickers)))
    return summary


async def run_collect(
    tickers: Sequence[str],
    horizons: Sequence[int],
    age_bands: Sequence[str],
    path: Path = DEFAULT_LOG,
    concurrency: int = 4,
    llm: JsonLLM | None = None,
) -> RunSummary:
    """Today's live forecasts, appended to the prediction log: the clean data model B
    and the gate need. Run it daily, then `python main.py --score`."""
    llm = llm or build_llm()
    summary = RunSummary()
    gate = asyncio.Semaphore(concurrency)

    async def for_ticker(ticker: str) -> None:
        try:
            snapshot = await asyncio.to_thread(fetch_snapshot, ticker)
        except Exception as exc:
            summary.failed[ticker] = f"{type(exc).__name__}: {exc}"
            return
        for horizon in horizons:
            summary.requested += 1
            async with gate:
                try:
                    prediction = await predict(
                        ticker, horizon_days=horizon, age_bands=list(age_bands), llm=llm, snapshot=snapshot
                    )
                except Exception as exc:
                    summary.failed[f"{ticker} h{horizon}"] = f"{type(exc).__name__}: {exc}"
                    continue
            log_prediction(prediction, path)
            summary.saved += 1

    await asyncio.gather(*(for_ticker(t.upper()) for t in dict.fromkeys(tickers)))
    return summary


# --- training and report ---------------------------------------------------------


@dataclass
class ReplayResult:
    scored: int
    pending: int
    by_horizon: dict[int, dict[str, float | int | None]]  # accuracy, always-up, momentum, n
    strategy_accuracy: dict[str, float | None]
    strategy_weights: dict[str, float]
    stacker: StackerReport | None = None
    stacker_note: str | None = None
    saved: list[Path] = field(default_factory=list)
    weights_file: Path | None = None


def _rate(hits: Sequence[bool]) -> float | None:
    return float(np.mean(hits)) if hits else None


def horizon_table(report: Report) -> dict[int, dict[str, float | int | None]]:
    table: dict[int, dict[str, float | int | None]] = {}
    for horizon in sorted({o.prediction.horizon_days for o in report.outcomes}):
        rows = [o for o in report.outcomes if o.prediction.horizon_days == horizon]
        table[horizon] = {
            "n": len(rows),
            "days": len({o.prediction.data_as_of for o in rows}),
            "personas": _rate([o.prediction.direction == o.actual for o in rows]),
            "always_up": _rate([o.actual == "up" for o in rows]),
            "momentum": _rate([o.prediction.baselines.get("momentum") == o.actual for o in rows]),
            "linear_regression": _rate(
                [o.prediction.baselines.get("linear_regression") == o.actual for o in rows]
            ),
        }
    return table


def train(
    report: Report,
    model_names: Sequence[str],
    target: str = "absolute",
    test_fraction: float = 0.3,
    refit_every: int = 3,
    save_models: bool = True,
    weights_file: Path = DEFAULT_WEIGHTS_FILE,
    min_scored: int = 60,
    source: str = "replay",
) -> ReplayResult:
    """Walk-forward-evaluate model B on the scored replay, fit it on every row, store
    it, and write the strategy weights the scored calls suggest.

    `min_scored` is far below the spec's 300 on purpose and the stored sidecar
    says `replay`: the result pre-adjusts the weights, it doesn't pass a gate.
    """
    result = ReplayResult(
        scored=report.scored,
        pending=report.pending,
        by_horizon=horizon_table(report),
        strategy_accuracy=report.by_strategy,
        strategy_weights=report.strategy_weights,
    )
    if report.strategy_weights:
        weights_file.parent.mkdir(parents=True, exist_ok=True)
        weights_file.write_text(
            json.dumps({"strategy_weights": report.strategy_weights, "scored": report.scored,
                        "source": source}, indent=2),
            encoding="utf-8",
        )
        result.weights_file = weights_file

    data = stacker_rows(report.outcomes, target=target)
    if len(data) < min_scored:
        result.stacker_note = f"{len(data)} scored forecasts; need {min_scored} to fit a network"
        return result
    try:
        result.stacker = evaluate_stacker(
            data, model_names, test_fraction, refit_every,
            min_train=max(20, len(data) // 4), min_scored=min_scored,
        )
    except ValueError as exc:
        result.stacker_note = str(exc)
    if save_models:
        walk = {m.name: m for m in result.stacker.models} if result.stacker else {}
        for name in model_names:
            model = make_model(name).fit(data.X, data.y)
            meta = {
                "kind": f"model_b_{source}",
                "note": "trained on backdated forecasts: pre-adjusts weights, not live accuracy, "
                        "passes no gate",
                "target": target,
                "columns": list(data.feature_names),
                "rows": len(data),
                "data_through": str(data.dates.max()),
                "walk_forward": (
                    {"accuracy": walk[name].accuracy, "log_loss": walk[name].log_loss} if name in walk else None
                ),
            }
            result.saved.append(save(model, f"stacker-{source}-{name}", meta))
    return result


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def render_result(result: ReplayResult, caveat: bool = True) -> str:
    lines = [f"Scored {result.scored} forecasts ({result.pending} still pending)", ""]
    lines.append("Accuracy by horizon, 3-way (down / flat / up), same rows for every column:")
    lines.append(f"  {'horizon':<8} {'n':>5} {'days':>5} {'personas':>9} {'always-up':>10} "
                 f"{'momentum':>9} {'regression':>11}")
    for horizon, r in result.by_horizon.items():
        lines.append(
            f"  {str(horizon) + 'd':<8} {r['n']:>5} {r['days']:>5} {_pct(r['personas']):>9} "
            f"{_pct(r['always_up']):>10} {_pct(r['momentum']):>9} {_pct(r['linear_regression']):>11}"
        )
    if result.strategy_accuracy:
        lines += ["", "Per strategy, share of persona votes that were right:"]
        lines += [f"  {s:<14} {_pct(a)}" for s, a in result.strategy_accuracy.items()]
    if result.strategy_weights:
        shown = ",".join(f"{s}={w:g}" for s, w in result.strategy_weights.items())
        lines += ["", "Pre-adjusted strategy weights (pass to main.py --weights):", f"  {shown}"]
        if result.weights_file:
            lines.append(f"  saved to {result.weights_file}")
    if result.stacker:
        s = result.stacker
        lines += ["", f"Network (model B), walk-forward on {s.n_test} held-out forecasts from {s.test_start}:"]
        base = "  ".join(f"{k} {_pct(v)}" for k, v in s.baselines.items())
        lines.append(f"  baselines on those rows: {base}")
        lines.append(f"  {'model':<13} {'accuracy':>8} {'log-loss':>9}  (prior {s.prior_log_loss:.4f})")
        for m in [s.weights_auto, *s.models]:
            if m is not None:
                lines.append(f"  {m.name:<13} {_pct(m.accuracy):>8} {m.log_loss:>9.4f}")
    elif result.stacker_note:
        lines += ["", f"Network not evaluated: {result.stacker_note}"]
    lines += [f"  saved {p}" for p in result.saved]
    if caveat:
        lines += [
            "",
            "Read this as a pipeline check and a weight pre-adjustment, not live accuracy: only prices",
            "were backdated, the LLM may have seen the period, and tickers on one day are correlated.",
            "Always-up is the bar.",
        ]
    return "\n".join(lines)


def score_and_train(path: Path, model_names: Sequence[str], **kwargs) -> ReplayResult:
    return train(score_log(path), model_names, **kwargs)


