"""The call policy: what scored history says to do with a fresh persona call.

`python -m ml coverage --save` fits it from resolved forecasts and writes
`data/call_policy.json`; `main.py --policy` applies it. Two parts, each used
only when it passed its own held-out check when fitted:

- abstain: per horizon, a strength below which the call is withheld and shown
  as "unclear" (the withheld call is kept in `Prediction.withheld_call`).
- calibration: strength -> P(call is right), a monotone curve, in
  `Prediction.p_correct`. Strength itself is never a probability.

Neither touches the personas, the vote or `net_score`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ai.schemas import Prediction

DEFAULT_POLICY = Path(__file__).resolve().parents[2] / "data" / "call_policy.json"


@dataclass(frozen=True)
class CallPolicy:
    abstain: dict[int, float]  # horizon -> min strength, only horizons that passed
    curve: tuple[tuple[float, float], ...] | None  # (strength, P(right)), when it passed
    fitted: dict[str, Any]  # the whole file, for display

    def p_correct(self, strength: float) -> float | None:
        if self.curve is None:
            return None
        xs, ys = zip(*self.curve)
        return round(float(np.interp(strength, xs, ys)), 4)


def from_dict(data: dict[str, Any]) -> CallPolicy:
    abstain = {
        int(h): float(rule["min_strength"])
        for h, rule in (data.get("abstain") or {}).items()
        if rule.get("enabled") and rule.get("min_strength") is not None
    }
    calibration = data.get("calibration") or {}
    curve = (
        tuple((float(s), float(p)) for s, p in calibration["curve"])
        if calibration.get("enabled") and calibration.get("curve")
        else None
    )
    return CallPolicy(abstain=abstain, curve=curve, fitted=data)


def load_policy(path: Path = DEFAULT_POLICY) -> CallPolicy | None:
    if not path.exists():
        return None
    return from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_policy(data: dict[str, Any], path: Path = DEFAULT_POLICY) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def apply_policy(prediction: Prediction, policy: CallPolicy) -> Prediction:
    """Withhold a weak call and attach P(right) for the call that stands."""
    threshold = policy.abstain.get(prediction.horizon_days)
    if (
        threshold is not None
        and prediction.direction != "unclear"
        and prediction.confidence < threshold
    ):
        prediction.withheld_call = prediction.direction
        prediction.direction = "unclear"
        prediction.data_warnings.append(
            f"policy: {prediction.withheld_call} call withheld, strength "
            f"{prediction.confidence:.2f} is below {threshold:.2f} for {prediction.horizon_days}-day calls"
        )
    if prediction.direction != "unclear":
        prediction.p_correct = policy.p_correct(prediction.confidence)
    return prediction
