"""Walk-forward evaluation of the ml models against the scorer's baselines.

Test dates are the last `test_fraction` of the dataset's distinct dates, cut
into blocks of `refit_every` dates. Before each block the model is refit on
every row whose label was known by the block's first date (`Dataset.known_on`).
With a fixed horizon that's a purge gap of exactly the horizon, and all rows
from one date land on the same side: cross-validation grouped by date, never a
random split.

Reported against always-up (the bar), momentum and the linear regression for
model A; against the persona call, the logged baselines and `--weights auto`
for model B. Plus log-loss, Brier score, a reliability table and, for model
A, the trading result through `finance.backtest` and a cross-sectional
long-short spread (lever 6).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from functools import partial

import numpy as np
import pandas as pd

from ai.confidence_score import aggregate
from ai.evaluation import derive_strategy_weights
from finance import linear_regression
from finance.backtest import strategy_returns, summarize
from finance.indicators import TRADING_DAYS
from ml.dataset import CLASS_INDEX, CLASSES, DOWN, UP, Dataset
from ml.model import Classifier, PriorModel, make_model

# Noise in a 3-way hit rate at ~200 test days per ticker is about 2-3 points (ml/spec.md).
GATE_MARGIN = 0.025
MIN_SCORED_FOR_STACKER = 300
RANK_QUANTILE = 0.2  # top / bottom quintile
MIN_RANK_TICKERS = 5


@dataclass(frozen=True)
class Block:
    start: np.datetime64
    train: np.ndarray  # row indices whose label was known by `start`
    test: np.ndarray  # row indices dated within the block


def schedule(
    dates: np.ndarray, known_on: np.ndarray, test_fraction: float, refit_every: int
) -> list[Block]:
    if not 0 < test_fraction < 1 or refit_every < 1:
        raise ValueError("test_fraction must be in (0, 1) and refit_every at least 1")
    days = np.unique(dates)
    first = int(len(days) * (1 - test_fraction))
    blocks = []
    for k in range(first, len(days), refit_every):
        start, end = days[k], days[min(k + refit_every, len(days)) - 1]
        blocks.append(
            Block(
                start=start,
                train=np.flatnonzero(known_on <= start),
                test=np.flatnonzero((dates >= start) & (dates <= end)),
            )
        )
    return blocks


@dataclass(frozen=True)
class Predictions:
    rows: np.ndarray  # dataset rows that were predicted, in date order
    proba: np.ndarray  # (len(rows), 3), CLASSES order
    refits: int
    skipped_rows: int  # test rows in blocks with too few known rows to train on


def walk_forward(
    data: Dataset,
    make: Callable[[], Classifier],
    test_fraction: float = 0.2,
    refit_every: int = 21,
    min_train: int = 100,
) -> Predictions:
    rows, probas, refits, skipped = [], [], 0, 0
    for block in schedule(data.dates, data.known_on, test_fraction, refit_every):
        if len(block.train) < min_train:
            skipped += len(block.test)
            continue
        model = make().fit(data.X[block.train], data.y[block.train])
        rows.append(block.test)
        probas.append(model.predict_proba(data.X[block.test]))
        refits += 1
    if not rows:
        raise ValueError(f"no test block had {min_train} known rows to train on")
    return Predictions(np.concatenate(rows), np.vstack(probas), refits, skipped)


def _on_rows(run: Predictions, rows: np.ndarray) -> np.ndarray:
    """`run`'s probabilities for `rows`, a subset of `run.rows`. Datasets are sorted by
    date and blocks run in date order, so `run.rows` is ascending."""
    return run.proba[np.searchsorted(run.rows, rows)]


# --- metrics ---------------------------------------------------------------------


def accuracy(calls: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean(calls == y))


def log_loss(proba: np.ndarray, y: np.ndarray) -> float:
    return float(-np.mean(np.log(np.clip(proba[np.arange(len(y)), y], 1e-12, 1))))


def brier(proba: np.ndarray, y: np.ndarray) -> float:
    """Multi-class Brier score: 0 is perfect; always predicting 1/3 each scores 0.67."""
    return float(np.mean(np.sum((proba - np.eye(len(CLASSES))[y]) ** 2, axis=1)))


@dataclass(frozen=True)
class ReliabilityBin:
    label: str
    n: int
    mean_probability: float | None  # of the predicted class
    hit_rate: float | None


def reliability(
    proba: np.ndarray, y: np.ndarray, edges: Sequence[float] = (0, 0.4, 0.5, 0.6, 1.0001)
) -> list[ReliabilityBin]:
    """Does a 55% call come true about 55% of the time?"""
    top, calls = proba.max(axis=1), proba.argmax(axis=1)
    bins = []
    for low, high in zip(edges[:-1], edges[1:]):
        inside = (top >= low) & (top < high)
        n = int(inside.sum())
        bins.append(
            ReliabilityBin(
                label=f"{low:.2f}-{min(high, 1):.2f}",
                n=n,
                mean_probability=float(top[inside].mean()) if n else None,
                hit_rate=float((calls[inside] == y[inside]).mean()) if n else None,
            )
        )
    return bins


@dataclass(frozen=True)
class ModelScore:
    name: str
    accuracy: float
    log_loss: float
    brier: float
    reliability: list[ReliabilityBin]
    refits: int
    beats_always_up_share: float | None = None  # model A: share of tickers
    trading: dict | None = None  # model A: equal-weight portfolio after costs
    rank_spread: dict | None = None  # model A: top minus bottom quintile, per period
    passes_gate: bool = False


def _score(name: str, y: np.ndarray, proba: np.ndarray, refits: int) -> ModelScore:
    return ModelScore(
        name=name,
        accuracy=accuracy(proba.argmax(axis=1), y),
        log_loss=log_loss(proba, y),
        brier=brier(proba, y),
        reliability=reliability(proba, y),
        refits=refits,
    )


# --- model A: pooled price rows --------------------------------------------------


def regression_calls(
    data: Dataset, test_fraction: float, refit_every: int, min_train: int = 100
) -> dict[int, int] | None:
    """The linear-regression baseline on the same rows and refit schedule: OLS per
    ticker on `linear_regression.FEATURES`, calling up when it predicts a gain.
    None when the dataset lacks those columns."""
    try:
        columns = [data.feature_names.index(f) for f in linear_regression.FEATURES]
    except ValueError:
        return None
    calls: dict[int, int] = {}
    for block in schedule(data.dates, data.known_on, test_fraction, refit_every):
        for ticker in np.unique(data.tickers[block.test]):
            train = block.train[data.tickers[block.train] == ticker]
            test = block.test[data.tickers[block.test] == ticker]
            if len(train) < min_train:
                continue
            fit = linear_regression.fit(data.X[np.ix_(train, columns)], data.forward_return[train])
            predicted = fit.predict(data.X[np.ix_(test, columns)])
            calls |= dict(zip(test.tolist(), np.where(predicted > 0, UP, DOWN).tolist()))
    return calls


def _non_overlapping(data: Dataset, rows: np.ndarray) -> np.ndarray:
    """`rows` dated on every horizon-th test date, so holding periods don't overlap."""
    days = np.unique(data.dates[rows])[:: data.horizon_days or 1]
    return rows[np.isin(data.dates[rows], days)]


def trading(data: Dataset, rows: np.ndarray, signal: np.ndarray, cost_bps: float) -> dict:
    """Each ticker holds sign(signal) over non-overlapping periods, after costs; the
    portfolio is the equal-weight average across tickers each period."""
    keep = np.isin(rows, _non_overlapping(data, rows))
    frame = pd.DataFrame(
        {
            "date": data.dates[rows][keep],
            "ticker": data.tickers[rows][keep],
            "signal": signal[keep],
            "forward": data.forward_return[rows][keep],
        }
    )
    per_ticker = [
        pd.Series(
            strategy_returns(g["signal"].to_numpy(), g["forward"].to_numpy(), cost_bps / 10_000),
            index=g["date"].to_numpy(),
        )
        for _, g in frame.groupby("ticker")
    ]
    portfolio = pd.concat(per_ticker, axis=1).mean(axis=1).sort_index().to_numpy()
    return summarize(portfolio, TRADING_DAYS / (data.horizon_days or 1))


def rank_spread(data: Dataset, rows: np.ndarray, score: np.ndarray) -> dict | None:
    """Lever 6: rank tickers each period by P(up) - P(down); long the top quintile,
    short the bottom. Returns the mean spread and how often it was positive."""
    keep = np.isin(rows, _non_overlapping(data, rows))
    dates, forward, score = data.dates[rows][keep], data.forward_return[rows][keep], score[keep]
    spreads = []
    for day in np.unique(dates):
        on_day = dates == day
        n = int(on_day.sum())
        if n < MIN_RANK_TICKERS:
            continue
        k = max(1, int(n * RANK_QUANTILE))
        order = np.argsort(score[on_day], kind="stable")
        ranked = forward[on_day][order]
        spreads.append(ranked[-k:].mean() - ranked[:k].mean())
    if not spreads:
        return None
    spreads = np.array(spreads)
    return {
        "periods": len(spreads),
        "mean_spread_pct": float(spreads.mean() * 100),
        "positive_share": float((spreads > 0).mean()),
    }


@dataclass
class PriceReport:
    horizon_days: int
    target: str
    tickers: list[str]
    n_test: int
    test_start: str
    refit_every: int
    baselines: dict[str, float]  # 3-way accuracy on the same rows
    prior_log_loss: float
    buy_and_hold: dict
    models: list[ModelScore] = field(default_factory=list)


def evaluate_price_models(
    data: Dataset,
    model_names: Sequence[str],
    test_fraction: float = 0.2,
    refit_every: int = 21,
    cost_bps: float = 5.0,
    makers: dict[str, Callable[[], Classifier]] | None = None,
) -> PriceReport:
    """Model A. Every model and baseline is scored on the same test rows; rows the
    regression baseline couldn't cover (too little history per ticker) are dropped
    for everyone."""
    makers = makers or {}
    regression = regression_calls(data, test_fraction, refit_every)
    runs = {
        name: walk_forward(
            data, makers.get(name) or partial(make_model, name), test_fraction, refit_every
        )
        for name in model_names
    }
    prior = walk_forward(data, PriorModel, test_fraction, refit_every)
    common = prior.rows
    for run in runs.values():
        common = np.intersect1d(common, run.rows)
    if regression is not None:
        common = np.intersect1d(common, np.fromiter(regression, dtype=int))
    if not len(common):
        raise ValueError("no test rows that every model could predict")

    y = data.y[common]
    baselines = {
        "always_up": accuracy(np.full(len(y), UP), y),
        "momentum": accuracy(np.where(data.past_return[common] >= 0, UP, DOWN), y),
    }
    if regression is not None:
        baselines["linear_regression"] = accuracy(np.array([regression[r] for r in common]), y)

    tickers = data.tickers[common]
    report = PriceReport(
        horizon_days=data.horizon_days or 0,
        target=data.target,
        tickers=sorted(set(tickers.tolist())),
        n_test=len(common),
        test_start=str(data.dates[common].min()),
        refit_every=refit_every,
        baselines=baselines,
        prior_log_loss=log_loss(_on_rows(prior, common), y),
        buy_and_hold=trading(data, common, np.ones(len(common)), cost_bps),
    )
    for name, run in runs.items():
        proba = _on_rows(run, common)
        calls = proba.argmax(axis=1)
        # Per ticker: is the model right more often than always-up on its own rows?
        beats = [
            np.mean(calls[tickers == t] == y[tickers == t]) > np.mean(y[tickers == t] == UP)
            for t in report.tickers
        ]
        scored = _score(name, y, proba, run.refits)
        signal = proba[:, UP] - proba[:, DOWN]
        report.models.append(
            replace(
                scored,
                beats_always_up_share=float(np.mean(beats)),
                trading=trading(data, common, signal, cost_bps),
                rank_spread=rank_spread(data, common, signal),
                passes_gate=bool(
                    scored.accuracy - baselines["always_up"] > GATE_MARGIN and np.mean(beats) > 0.5
                ),
            )
        )
    return report


# --- model B: the persona stacker ------------------------------------------------


def _strategy_votes(data: Dataset, rows: np.ndarray) -> dict[str, list[bool]]:
    votes: dict[str, list[bool]] = defaultdict(list)
    for i in rows:
        outcome = data.outcomes[i]
        for r in outcome.prediction.personas:
            if r.view is not None:
                votes[r.strategy].append(r.view.direction == outcome.actual)
    return votes


def _reweighted_call(outcome, weights: dict[str, float]) -> str:
    return aggregate(outcome.prediction.personas, weights or None).direction


def weights_auto_proba(
    data: Dataset, test_fraction: float, refit_every: int, min_train: int
) -> tuple[np.ndarray, np.ndarray]:
    """`--weights auto` replayed walk-forward: strategy weights from the outcomes known
    before each block, the test predictions re-aggregated with them. Its call gets
    the probability its weighted calls were right in training; the other two
    classes share the rest. An "unclear" call gets the training class frequencies."""
    rows, probas = [], []
    for block in schedule(data.dates, data.known_on, test_fraction, refit_every):
        if len(block.train) < min_train:
            continue
        weights = derive_strategy_weights(_strategy_votes(data, block.train))
        train_calls = [_reweighted_call(data.outcomes[i], weights) for i in block.train]
        hit = np.mean([c == data.outcomes[i].actual for c, i in zip(train_calls, block.train)])
        hit = float(np.clip(hit, 0.05, 0.95))
        prior = PriorModel().fit(data.X[block.train], data.y[block.train]).prior_
        for i in block.test:
            call = _reweighted_call(data.outcomes[i], weights)
            if call == "unclear":
                probas.append(prior)
            else:
                p = np.full(len(CLASSES), (1 - hit) / 2)
                p[CLASS_INDEX[call]] = hit
                probas.append(p)
            rows.append(i)
    return np.array(rows, dtype=int), np.array(probas).reshape(len(rows), len(CLASSES))


@dataclass
class StackerReport:
    scored: int
    n_test: int
    test_start: str | None
    baselines: dict[str, float | None]  # 3-way accuracy on the same rows
    weights_auto: ModelScore | None
    prior_log_loss: float | None
    models: list[ModelScore] = field(default_factory=list)
    blocked: str | None = None  # why nothing was evaluated


def _call_accuracy(data: Dataset, rows: np.ndarray, call: Callable) -> float | None:
    """Hit rate of `call(outcome)` over `rows`, skipping rows where it returns None.
    An "unclear" persona call counts as wrong, as in `ai.evaluation.score`."""
    pairs = [(call(data.outcomes[i]), data.outcomes[i].actual) for i in rows]
    hits = [c == actual for c, actual in pairs if c is not None]
    return float(np.mean(hits)) if hits else None


def evaluate_stacker(
    data: Dataset,
    model_names: Sequence[str],
    test_fraction: float = 0.3,
    refit_every: int = 5,
    min_train: int = 100,
    min_scored: int = MIN_SCORED_FOR_STACKER,
) -> StackerReport:
    """Model B. Gate: better log-loss *and* accuracy than `--weights auto` on held-out
    dates, with at least `min_scored` scored predictions."""
    if len(data) < min_scored:
        return StackerReport(
            scored=len(data), n_test=0, test_start=None, baselines={}, weights_auto=None,
            prior_log_loss=None,
            blocked=f"{len(data)} scored predictions; model B needs {min_scored} (ml/spec.md)",
        )
    auto = Predictions(*weights_auto_proba(data, test_fraction, refit_every, min_train), 0, 0)
    runs = {
        name: walk_forward(data, partial(make_model, name), test_fraction, refit_every, min_train)
        for name in model_names
    }
    prior = walk_forward(data, PriorModel, test_fraction, refit_every, min_train)
    rows = prior.rows  # the same schedule and min_train, so every run predicts these rows
    y = data.y[rows]
    auto_proba = _on_rows(auto, rows)

    baselines = {
        "personas": _call_accuracy(data, rows, lambda o: o.prediction.direction),
        "always_up": accuracy(np.full(len(y), UP), y),
        "momentum": _call_accuracy(data, rows, lambda o: o.prediction.baselines.get("momentum")),
        "linear_regression": _call_accuracy(
            data, rows, lambda o: o.prediction.baselines.get("linear_regression")
        ),
    }
    weights_auto = _score("weights_auto", y, auto_proba, prior.refits)
    report = StackerReport(
        scored=len(data),
        n_test=len(rows),
        test_start=str(data.dates[rows].min()),
        baselines=baselines,
        weights_auto=weights_auto,
        prior_log_loss=log_loss(prior.proba, y),
    )
    for name, run in runs.items():
        scored = _score(name, y, run.proba, run.refits)
        passes = scored.log_loss < weights_auto.log_loss and scored.accuracy > weights_auto.accuracy
        report.models.append(replace(scored, passes_gate=passes))
    return report
