"""Phase 2 levers 1, 2, 5 and 6 (`ml/spec.md`), on scored persona calls.

1. Accuracy at coverage: the persona call's hit rate on its strongest 50% and
   30% of calls, and when all strategies agree, each beside always-up on the
   same rows (picking a subset moves the base rate too).
2. Strength calibrated into P(call is right), isotonic or Platt, judged
   walk-forward by Brier score against a constant hit rate.
5. The same tables for calls with earnings inside the horizon and without, and
   for calls made while insiders were buying in a cluster and without.
6. Ranking: on each day with enough tickers predicted, long the top fifth by
   the personas' net score and short the bottom fifth.

Also the bias check behind step 4 of the accuracy plan: what the personas call
against what happened, per horizon and per strategy, and whether votes that
cite missing data do worse.

"unclear" calls count as wrong with strength 0, as in `ai.evaluation.score`.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ai.evaluation import Outcome
from ml.walkforward import GATE_MARGIN, MIN_RANK_TICKERS, RANK_QUANTILE, schedule

INSIDERS = "long_term.insiders_last_6m."  # the packet's keys in Prediction.features
MIN_CLUSTER_BUYS = 3


def insider_buying_cluster(prediction) -> bool | None:
    """Several insider purchases and net buying, from the long-term packet.

    yfinance reports insider activity as trailing-6-month totals without dates,
    so "cluster" means at least `MIN_CLUSTER_BUYS` purchase transactions and
    more shares bought than sold over those 6 months; a narrower window inside
    the horizon isn't available. None when the packet had no insider data.
    """
    features = prediction.features or {}
    buys, net = features.get(INSIDERS + "buy_transactions"), features.get(INSIDERS + "net_shares")
    if buys is None or net is None:
        return None
    return buys >= MIN_CLUSTER_BUYS and net > 0

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
    insider_cluster: np.ndarray  # insiders were buying in a cluster (False when unknown)
    insider_known: np.ndarray  # the long-term packet had insider data

    def take(self, mask: np.ndarray) -> CallRows:
        return CallRows(**{k: v[mask] for k, v in self.__dict__.items()})


def _strategies_agree(prediction) -> bool:
    sign = {"up": 1, "down": -1}.get(raw_call(prediction))
    nets = list(prediction.by_strategy.values())
    return sign is not None and len(nets) >= 2 and all(n * sign > 0 for n in nets)


def raw_call(prediction) -> str:
    """The personas' own call: a call the policy withheld counts as made, so
    refitting the policy sees what it would have abstained from."""
    return prediction.withheld_call or prediction.direction


def call_rows(outcomes: Sequence[Outcome]) -> CallRows:
    outcomes = sorted(outcomes, key=lambda o: o.prediction.data_as_of)
    clusters = [insider_buying_cluster(o.prediction) for o in outcomes]
    calls = [raw_call(o.prediction) for o in outcomes]
    return CallRows(
        insider_cluster=np.array([bool(c) for c in clusters], dtype=bool),
        insider_known=np.array([c is not None for c in clusters], dtype=bool),
        strength=np.array(
            [0.0 if c == "unclear" else o.prediction.confidence for c, o in zip(calls, outcomes)]
        ),
        correct=np.array([c == o.actual for c, o in zip(calls, outcomes)], dtype=bool),
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
        "insider buying cluster": accuracy_at_coverage(rows.take(rows.insider_known & rows.insider_cluster)),
        "no insider buying cluster": accuracy_at_coverage(
            rows.take(rows.insider_known & ~rows.insider_cluster)
        ),
    }


def persona_rank_spread(outcomes: Sequence[Outcome]) -> dict | None:
    """Lever 6 for the personas: on each data date and horizon with at least
    `MIN_RANK_TICKERS` tickers predicted, long the top `RANK_QUANTILE` by net score
    and short the bottom, held over the horizon. The latest forecast per ticker
    and day counts once.

    Days with horizons longer than one day overlap, so `positive_share` isn't a
    count of independent bets. None until some day has enough tickers.
    """
    groups: dict[tuple[str, int], dict[str, Outcome]] = defaultdict(dict)
    for o in sorted(outcomes, key=lambda o: o.prediction.generated_at):
        groups[(o.prediction.data_as_of, o.prediction.horizon_days)][o.prediction.ticker] = o
    spreads, sizes = [], []
    for _, by_ticker in sorted(groups.items()):
        n = len(by_ticker)
        if n < MIN_RANK_TICKERS:
            continue
        k = max(1, int(n * RANK_QUANTILE))
        ranked = sorted(by_ticker.values(), key=lambda o: (o.prediction.net_score, o.prediction.ticker))
        returns = np.array([o.return_pct / 100 for o in ranked])
        spreads.append(returns[-k:].mean() - returns[:k].mean())
        sizes.append(n)
    if not spreads:
        return None
    spreads = np.array(spreads)
    return {
        "periods": len(spreads),
        "mean_tickers": float(np.mean(sizes)),
        "mean_spread_pct": float(spreads.mean() * 100),
        "positive_share": float((spreads > 0).mean()),
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


# --- the call policy (ai/policy.py) -----------------------------------------------

POLICY_COVERAGE = 0.5  # keep the strongest half of calls
MIN_POLICY_ROWS = 100  # per horizon, before an abstain threshold is even tried
MIN_POLICY_TEST = 30  # kept calls in the held-out part
CURVE_GRID = tuple(round(x, 2) for x in np.linspace(0, 1, 21))


def _abstain_rule(rows: CallRows, test_fraction: float) -> dict:
    """A strength threshold keeping `POLICY_COVERAGE` of calls, judged once out of
    sample: fit on the earlier calls whose outcome was known before the held-out
    ones begin, then compared with always-up on the held-out calls it keeps."""
    n = len(rows.correct)
    if n < MIN_POLICY_ROWS:
        return {"enabled": False, "n": n, "reason": f"{n} scored calls, need {MIN_POLICY_ROWS}"}
    cut = int(n * (1 - test_fraction))
    start = rows.dates[cut]
    train = np.flatnonzero((np.arange(n) < cut) & (rows.known_on <= start))
    called = rows.strength > 0
    train_calls = rows.strength[train][called[train]]
    rule = {"n": n, "test_start": str(start), "enabled": False}
    if not len(train_calls):
        return rule | {"reason": "no calls before the held-out block"}
    threshold = float(np.quantile(train_calls, 1 - POLICY_COVERAGE))
    kept = np.flatnonzero((np.arange(n) >= cut) & called & (rows.strength >= threshold))
    accuracy = float(rows.correct[kept].mean()) if len(kept) else None
    always_up = float(rows.up[kept].mean()) if len(kept) else None
    rule |= {"held_out_kept": len(kept), "held_out_accuracy": accuracy, "held_out_always_up": always_up}
    if len(kept) < MIN_POLICY_TEST:
        return rule | {"reason": f"{len(kept)} held-out calls kept, need {MIN_POLICY_TEST}"}
    if accuracy - always_up <= GATE_MARGIN:
        return rule | {"reason": f"kept calls don't beat always-up by {GATE_MARGIN * 100:g} points"}
    final = float(np.quantile(rows.strength[called], 1 - POLICY_COVERAGE))  # refit on every call
    return rule | {"enabled": True, "min_strength": round(final, 4)}


def fit_call_policy(outcomes: Sequence[Outcome], test_fraction: float = 0.3) -> dict:
    """The JSON `ai.policy.load_policy` reads. Each part is enabled only when it
    passed its held-out check; a disabled part keeps its numbers and the reason."""
    by_horizon: dict[int, list[Outcome]] = defaultdict(list)
    for o in outcomes:
        by_horizon[o.prediction.horizon_days].append(o)
    abstain = {
        str(h): _abstain_rule(call_rows(rows), test_fraction) for h, rows in sorted(by_horizon.items())
    }
    score = evaluate_calibration(outcomes)
    if score is None:
        calibration: dict = {"enabled": False, "reason": "too few resolved calls"}
    else:
        best = min(METHODS, key=score.brier.get)
        calibration = {"method": best, "brier": score.brier, "n_test": score.n_test,
                       "enabled": score.brier[best] < score.brier["constant"]}
        if calibration["enabled"]:
            rows = call_rows(outcomes)
            fitted = StrengthCalibrator(best).fit(rows.strength, rows.correct)
            probabilities = fitted.predict(np.array(CURVE_GRID))
            calibration["curve"] = [[s, round(float(p), 4)] for s, p in zip(CURVE_GRID, probabilities)]
        else:
            calibration["reason"] = "no better than the constant hit rate on held-out calls"
    return {
        "scored": len(outcomes),
        "data_through": max((o.prediction.data_as_of for o in outcomes), default=None),
        "abstain": abstain,
        "calibration": calibration,
    }


# --- bias: what the personas call against what happened ---------------------------

ACTUALS = ("down", "flat", "up")
CALLS = ("up", "down", "flat", "unclear")
# A rationale that blames absent inputs. Matched loosely: it's a diagnostic, not a label.
MISSING_DATA = re.compile(
    r"\b(missing|unavailable|not available|lack of|no data|absence of|null)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class VoteBias:
    votes: int
    share: dict[str, float]  # direction -> share of this strategy's votes
    hit_rate: dict[str, float | None]  # direction -> share of those votes that were right


@dataclass(frozen=True)
class BiasReport:
    horizon_days: int
    n: int
    confusion: dict[str, dict[str, int]]  # call -> actual -> count
    actual_share: dict[str, float]
    call_share: dict[str, float]
    by_strategy: dict[str, VoteBias]
    missing_data_share: float | None  # share of persona votes whose rationale cites missing data
    missing_data_hit_rate: float | None
    other_hit_rate: float | None


def _share(counts: Counter, keys: Sequence[str]) -> dict[str, float]:
    total = sum(counts[k] for k in keys)
    return {k: counts[k] / total if total else 0.0 for k in keys}


def _rate(hits: int, n: int) -> float | None:
    return hits / n if n else None


def _horizon_bias(horizon: int, outcomes: Sequence[Outcome]) -> BiasReport:
    confusion = {c: {a: 0 for a in ACTUALS} for c in CALLS}
    for o in outcomes:
        confusion[raw_call(o.prediction)][o.actual] += 1

    votes: dict[str, Counter] = defaultdict(Counter)
    hits: dict[str, Counter] = defaultdict(Counter)
    flagged = [0, 0]  # votes, hits
    other = [0, 0]
    for o in outcomes:
        for r in o.prediction.personas:
            if r.view is None:
                continue
            right = r.view.direction == o.actual
            votes[r.strategy][r.view.direction] += 1
            hits[r.strategy][r.view.direction] += right
            bucket = flagged if MISSING_DATA.search(r.view.rationale or "") else other
            bucket[0] += 1
            bucket[1] += right

    by_strategy = {
        s: VoteBias(
            votes=sum(c.values()),
            share=_share(c, ACTUALS),
            hit_rate={d: _rate(hits[s][d], c[d]) for d in ACTUALS},
        )
        for s, c in sorted(votes.items())
    }
    total_votes = flagged[0] + other[0]
    return BiasReport(
        horizon_days=horizon,
        n=len(outcomes),
        confusion=confusion,
        actual_share=_share(Counter(o.actual for o in outcomes), ACTUALS),
        call_share=_share(Counter(raw_call(o.prediction) for o in outcomes), CALLS),
        by_strategy=by_strategy,
        missing_data_share=_rate(flagged[0], total_votes),
        missing_data_hit_rate=_rate(flagged[1], flagged[0]),
        other_hit_rate=_rate(other[1], other[0]),
    )


def bias_report(outcomes: Sequence[Outcome]) -> list[BiasReport]:
    """One report per horizon, shortest first. Persona votes are counted per
    persona-mode sample, so a run with several modes counts each of them."""
    by_horizon: dict[int, list[Outcome]] = defaultdict(list)
    for o in outcomes:
        by_horizon[o.prediction.horizon_days].append(o)
    return [_horizon_bias(h, rows) for h, rows in sorted(by_horizon.items())]
