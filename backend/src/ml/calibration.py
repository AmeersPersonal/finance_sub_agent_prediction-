"""Phase 2 levers 1, 2 and 5 (`ml/spec.md`), on scored persona calls.

1. Accuracy at coverage: the persona call's hit rate on its strongest 50% and
   30% of calls, and when all strategies agree, each beside always-up on the
   same rows (picking a subset moves the base rate too).
2. Strength calibrated into P(call is right), isotonic or Platt, judged
   walk-forward by Brier score against a constant hit rate.
5. The same tables for calls with earnings inside the horizon and without.

"unclear" calls count as wrong with strength 0, as in `ai.evaluation.score`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ai.evaluation import Outcome
from ml.walkforward import schedule

COVERAGES = (1.0, 0.5, 0.3)
METHODS = ("isotonic", "platt")


@dataclass(frozen=True)
class CallRows:
    strength: np.ndarray  # Prediction.confidence; 0 when unclear
    correct: np.ndarray  # the persona call matched the outcome
    up: np.ndarray  # the outcome was up: always-up was right
    earnings: np.ndarray  # earnings inside the horizon (False when unknown)
    agree: np.ndarray  # an up/down call that every strategy's net score leans toward
    dates: np.ndarray
    known_on: np.ndarray

    def take(self, mask: np.ndarray) -> CallRows:
        return CallRows(**{k: v[mask] for k, v in self.__dict__.items()})


def _strategies_agree(prediction) -> bool:
    sign = {"up": 1, "down": -1}.get(prediction.direction)
    nets = list(prediction.by_strategy.values())
    return sign is not None and len(nets) >= 2 and all(n * sign > 0 for n in nets)


def call_rows(outcomes: Sequence[Outcome]) -> CallRows:
    outcomes = sorted(outcomes, key=lambda o: o.prediction.data_as_of)
    return CallRows(
        strength=np.array(
            [0.0 if o.prediction.direction == "unclear" else o.prediction.confidence for o in outcomes]
        ),
        correct=np.array([o.prediction.direction == o.actual for o in outcomes], dtype=bool),
        up=np.array([o.actual == "up" for o in outcomes], dtype=bool),
        earnings=np.array([bool(o.prediction.earnings_within_horizon) for o in outcomes], dtype=bool),
        agree=np.array([_strategies_agree(o.prediction) for o in outcomes], dtype=bool),
        dates=np.array([o.prediction.data_as_of for o in outcomes], dtype="datetime64[D]"),
        known_on=np.array([o.resolved_on for o in outcomes], dtype="datetime64[D]"),
    )


@dataclass(frozen=True)
class CoverageRow:
    label: str
    n: int
    min_strength: float | None  # abstain below this to get this coverage
    accuracy: float | None
    always_up: float | None  # on the same rows


def accuracy_at_coverage(
    rows: CallRows, coverages: Sequence[float] = COVERAGES, prefix: str = ""
) -> list[CoverageRow]:
    """Hit rate on the top `coverage` share of calls by strength (ties broken by date)."""
    order = np.argsort(-rows.strength, kind="stable")
    table = []
    for coverage in coverages:
        k = math.ceil(coverage * len(order))
        top = order[:k]
        table.append(
            CoverageRow(
                label=f"{prefix}top {coverage:.0%}",
                n=k,
                min_strength=float(rows.strength[top].min()) if k else None,
                accuracy=float(rows.correct[top].mean()) if k else None,
                always_up=float(rows.up[top].mean()) if k else None,
            )
        )
    return table


def coverage_report(outcomes: Sequence[Outcome]) -> dict[str, list[CoverageRow]]:
    rows = call_rows(outcomes)
    agree = rows.take(rows.agree)
    return {
        "all calls": accuracy_at_coverage(rows),
        "all strategies agree": accuracy_at_coverage(agree, (1.0,)),
        "earnings inside the horizon": accuracy_at_coverage(rows.take(rows.earnings)),
        "no earnings inside the horizon": accuracy_at_coverage(rows.take(~rows.earnings)),
    }


class StrengthCalibrator:
    """Maps persona strength to P(call is right). Isotonic is monotone and needs no
    shape assumption; Platt (a logistic curve) is smoother with few rows."""

    def __init__(self, method: str = "isotonic") -> None:
        if method not in METHODS:
            raise ValueError(f"unknown method {method!r}; choose from {', '.join(METHODS)}")
        self.method = method

    def fit(self, strength: np.ndarray, correct: np.ndarray) -> StrengthCalibrator:
        self._constant = float(correct.mean()) if len(np.unique(correct)) < 2 else None
        if self._constant is not None:
            return self
        if self.method == "isotonic":
            from sklearn.isotonic import IsotonicRegression

            self._model = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip")
            self._model.fit(strength, correct.astype(float))
        else:
            from sklearn.linear_model import LogisticRegression

            self._model = LogisticRegression().fit(strength.reshape(-1, 1), correct)
        return self

    def predict(self, strength: np.ndarray) -> np.ndarray:
        if self._constant is not None:
            return np.full(len(strength), self._constant)
        if self.method == "isotonic":
            return self._model.predict(strength)
        return self._model.predict_proba(strength.reshape(-1, 1))[:, 1]


@dataclass(frozen=True)
class CalibrationScore:
    n_test: int
    brier: dict[str, float]  # method -> Brier on held-out calls; "constant" is the reference
    curve: dict[str, list[tuple[float, float]]]  # method -> (strength, probability), fit on all


CURVE_POINTS = (0.15, 0.25, 0.4, 0.6, 0.8)


def evaluate_calibration(
    outcomes: Sequence[Outcome],
    test_fraction: float = 0.3,
    refit_every: int = 5,
    min_train: int = 50,
) -> CalibrationScore | None:
    """Walk-forward: each method is fit on calls resolved before a block and scored on
    the block. None when no block has `min_train` resolved calls before it."""
    rows = call_rows(outcomes)
    if not len(rows.correct):
        return None
    predicted: dict[str, list[np.ndarray]] = {m: [] for m in (*METHODS, "constant")}
    tested: list[np.ndarray] = []
    for block in schedule(rows.dates, rows.known_on, test_fraction, refit_every):
        if len(block.train) < min_train:
            continue
        tested.append(block.test)
        train_s, train_c = rows.strength[block.train], rows.correct[block.train]
        predicted["constant"].append(np.full(len(block.test), train_c.mean()))
        for method in METHODS:
            fitted = StrengthCalibrator(method).fit(train_s, train_c)
            predicted[method].append(fitted.predict(rows.strength[block.test]))
    if not tested:
        return None
    test = np.concatenate(tested)
    actual = rows.correct[test].astype(float)
    brier = {m: float(np.mean((np.concatenate(p) - actual) ** 2)) for m, p in predicted.items()}
    points = np.array(CURVE_POINTS)
    curve = {}
    for method in METHODS:
        fitted = StrengthCalibrator(method).fit(rows.strength, rows.correct)
        curve[method] = list(zip(CURVE_POINTS, fitted.predict(points).tolist()))
    return CalibrationScore(n_test=len(test), brier=brier, curve=curve)
