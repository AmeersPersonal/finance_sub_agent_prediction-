"""Training rows for the ml models, labelled exactly like the scorer.

Model A rows come from daily prices: the regression's features
(`finance.linear_regression.FEATURE_FUNCTIONS`) and the 3-way up / flat / down
label from `finance.indicators.flat_band_series`, pooled across tickers.
Model B rows come from scored live predictions (`ai.evaluation.score`): each
persona's vote collapsed across its reasoning modes, plus the aggregate call.

Every row carries `known_on`, the day its label became known. Walk-forward
training keeps only rows known by the day it predicts (`ml/walkforward.py`),
which is the purge gap.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace

import numpy as np
import pandas as pd

from ai.evaluation import Outcome
from ai.schemas import PersonaView
from finance.indicators import flat_band_series
from finance.linear_regression import FEATURES, build_features, forward_return
from ml.model import CLASSES  # column order of every predict_proba

DOWN, FLAT, UP = range(3)
CLASS_INDEX = {c: i for i, c in enumerate(CLASSES)}


@dataclass(frozen=True)
class Dataset:
    X: np.ndarray  # float, NaN where a value is missing
    y: np.ndarray  # index into CLASSES
    dates: np.ndarray  # datetime64[D]: the day the features were known (the prediction day)
    known_on: np.ndarray  # datetime64[D]: the day the label became known
    tickers: np.ndarray
    forward_return: np.ndarray  # over the horizon, a fraction (vs the benchmark for "relative")
    past_return: np.ndarray  # over the previous horizon, for the momentum baseline; NaN for B
    feature_names: tuple[str, ...]
    horizon_days: int | None  # None when rows mix horizons (model B)
    target: str = "absolute"
    outcomes: tuple[Outcome, ...] = ()  # model B only, row-aligned

    def __len__(self) -> int:
        return len(self.y)

    def take(self, rows: np.ndarray) -> Dataset:
        """The same dataset restricted to `rows` (indices or a boolean mask)."""
        rows = np.flatnonzero(rows) if rows.dtype == bool else rows
        arrays = {
            f.name: getattr(self, f.name)[rows]
            for f in fields(self)
            if isinstance(getattr(self, f.name), np.ndarray)
        }
        outcomes = tuple(self.outcomes[i] for i in rows) if self.outcomes else ()
        return replace(self, **arrays, outcomes=outcomes)


def _days(index: pd.Index) -> np.ndarray:
    return np.array([ts.date() for ts in index], dtype="datetime64[D]")


def relative_close(close: pd.Series, benchmark_close: pd.Series) -> pd.Series:
    """Price of the stock in units of the benchmark: its return is the excess return."""
    return close / benchmark_close.reindex(close.index)


def label(returns: np.ndarray, band: np.ndarray) -> np.ndarray:
    """`finance.indicators.classify_move`, vectorised, as CLASSES indices."""
    return np.where(returns > band, UP, np.where(returns < -band, DOWN, FLAT))


def price_rows(
    daily: pd.DataFrame,
    horizon_days: int,
    features: Sequence[str] = FEATURES,
    ticker: str = "",
    benchmark: pd.DataFrame | None = None,
) -> Dataset:
    """One row per day with every feature and a known label.

    With a `benchmark` the target is the return relative to it (lever 4,
    `ml/spec.md`) and the flat band is sized from the relative series' own
    volatility; the features stay the stock's own.
    """
    close = daily["Close"]
    series = close if benchmark is None else relative_close(close, benchmark["Close"])
    X = build_features(daily, features)
    target = forward_return(series, horizon_days)
    band = flat_band_series(series, horizon_days)
    past = series / series.shift(horizon_days) - 1
    known_on = pd.Series(_days(daily.index), index=daily.index).shift(-horizon_days)

    usable = (X.notna().all(axis=1) & target.notna() & band.notna() & past.notna()).to_numpy()
    returns = target.to_numpy()[usable]
    return Dataset(
        X=X.to_numpy(dtype=float)[usable],
        y=label(returns, band.to_numpy()[usable]),
        dates=_days(daily.index)[usable],
        known_on=known_on.to_numpy()[usable].astype("datetime64[D]"),
        tickers=np.full(int(usable.sum()), ticker, dtype=object),
        forward_return=returns,
        past_return=past.to_numpy()[usable],
        feature_names=tuple(features),
        horizon_days=horizon_days,
        target="absolute" if benchmark is None else "relative",
    )


def concat(parts: Sequence[Dataset]) -> Dataset:
    """Rows of several datasets with the same columns, ordered by date then ticker."""
    if not parts:
        raise ValueError("no datasets to combine")
    first = parts[0]
    if any(p.feature_names != first.feature_names for p in parts):
        raise ValueError("datasets have different feature columns")
    arrays = {
        f.name: np.concatenate([getattr(p, f.name) for p in parts])
        for f in fields(first)
        if isinstance(getattr(first, f.name), np.ndarray)
    }
    combined = replace(first, **arrays, outcomes=tuple(o for p in parts for o in p.outcomes))
    return combined.take(np.lexsort((combined.tickers.astype(str), combined.dates)))


def pooled_price_rows(
    dailies: Mapping[str, pd.DataFrame],
    horizon_days: int,
    features: Sequence[str] = FEATURES,
    benchmark: pd.DataFrame | None = None,
) -> Dataset:
    return concat(
        [price_rows(d, horizon_days, features, t, benchmark) for t, d in dailies.items()]
    )


# --- Model B: scored persona predictions -----------------------------------------


def _persona_mass(views: Sequence[PersonaView]) -> dict[str, float]:
    """Mean conviction per direction across a persona's modes, as `ai.confidence_score`."""
    return {d: sum(v.conviction for v in views if v.direction == d) / len(views) for d in CLASSES}


def _nan(value: float | bool | None) -> float:
    return float("nan") if value is None else float(value)


def stacker_features(outcome: Outcome, include_packet: bool = False) -> dict[str, float]:
    """What model B learns from: every persona's vote, each strategy's and reasoning
    mode's net score, and the aggregate call. A persona that didn't run scores 0 (no
    vote). `include_packet` adds `Prediction.features`, hundreds of columns: only
    worth it with far more than 300 scored predictions."""
    p = outcome.prediction
    views: dict[str, list[PersonaView]] = {}
    for r in p.personas:
        if r.view is not None:
            views.setdefault(r.persona_id, []).append(r.view)
    row: dict[str, float] = {}
    for persona_id, persona_views in views.items():
        mass = _persona_mass(persona_views)
        row[f"persona.{persona_id}.net"] = mass["up"] - mass["down"]
        row[f"persona.{persona_id}.flat"] = mass["flat"]
    row |= {f"strategy.{s}": v for s, v in p.by_strategy.items()}
    row |= {f"mode.{m}": v for m, v in p.by_mode.items()}
    row |= {
        "call.net_score": p.net_score,
        "call.confidence": p.confidence,
        "call.agreement": p.agreement,
        "call.stability": _nan(p.stability),
        "horizon_days": float(p.horizon_days),
        "flat_band_pct": p.flat_band_pct,
        "earnings_within_horizon": _nan(p.earnings_within_horizon),
    }
    if include_packet and p.features:
        row |= {f"packet.{k}": _nan(v) for k, v in p.features.items()}
    return row


# Columns missing from a row: no vote is 0, anything else is unknown.
_VOTE_PREFIXES = ("persona.", "strategy.", "mode.")


def stacker_rows(
    outcomes: Sequence[Outcome],
    columns: Sequence[str] | None = None,
    include_packet: bool = False,
    target: str = "absolute",
) -> Dataset:
    """Model B rows. `columns` fixes the column order (a saved model's); by default
    it's every column seen, sorted.

    `target="relative"` labels each row with the outcome relative to SPY
    (`Outcome.relative_actual`, `ai.evaluation`) and drops outcomes scored
    without SPY closes. The band is the prediction's own flat band, not one sized
    from the relative series as in model A, since that history isn't logged.
    """
    if target not in ("absolute", "relative"):
        raise ValueError(f"unknown target {target!r}; choose absolute or relative")
    relative = target == "relative"
    if relative:
        outcomes = [o for o in outcomes if o.relative_actual is not None]
    rows = [stacker_features(o, include_packet) for o in outcomes]
    columns = tuple(columns) if columns is not None else tuple(sorted({k for r in rows for k in r}))
    X = np.array(
        [
            [r.get(c, 0.0 if c.startswith(_VOTE_PREFIXES) else np.nan) for c in columns]
            for r in rows
        ],
        dtype=float,
    ).reshape(len(rows), len(columns))
    return Dataset(
        X=X,
        y=np.array([CLASS_INDEX[o.relative_actual if relative else o.actual] for o in outcomes], dtype=int),
        dates=np.array([o.prediction.data_as_of for o in outcomes], dtype="datetime64[D]"),
        known_on=np.array([o.resolved_on for o in outcomes], dtype="datetime64[D]"),
        tickers=np.array([o.prediction.ticker for o in outcomes], dtype=object),
        forward_return=np.array(
            [(o.relative_return_pct if relative else o.return_pct) / 100 for o in outcomes], dtype=float
        ),
        past_return=np.full(len(outcomes), np.nan),
        feature_names=columns,
        horizon_days=None,
        target=target,
        outcomes=tuple(outcomes),
    ).take(np.argsort(np.array([o.prediction.data_as_of for o in outcomes]), kind="stable"))
