"""Model A's probabilities for a fresh forecast, logged in `Prediction.price_model`.

Model A failed its gate, so this never changes the call and is never shown to
the personas. It's logged so model B can learn whether it adds anything on top
of them (`dataset.stacker_features`), and only counts there for forecasts made
after the model's last training label (`trained_through`).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from finance.linear_regression import build_features
from ml.model import CLASSES
from ml.store import DEFAULT_DIR, latest, load

DEFAULT_MODEL = "logistic"  # the best-calibrated of the three on the reliability table

PriceSignal = Callable[[pd.DataFrame], dict[str, Any] | None]


def price_signal(
    horizon_days: int, model: str = DEFAULT_MODEL, directory: Path = DEFAULT_DIR
) -> PriceSignal | None:
    """A function from daily bars to model A's call for `horizon_days`, or None
    when no model was saved for that horizon (`python -m ml price --save`)."""
    path = latest(f"price-{model}-{horizon_days}d-absolute", directory)
    if path is None:
        return None
    fitted, meta = load(path)
    features = meta["features"]

    def signal(daily: pd.DataFrame) -> dict[str, Any] | None:
        row = build_features(daily, features).iloc[[-1]]
        if row.isna().any(axis=None):
            return None
        probabilities = fitted.predict_proba(row.to_numpy(dtype=float))[0]
        return {
            "name": meta["name"],
            "file": meta["file"],
            "trained_through": meta["data_through"],
            "passes_gate": (meta.get("walk_forward") or {}).get("passes_gate"),
            **{f"p_{c}": round(float(p), 4) for c, p in zip(CLASSES, probabilities)},
        }

    return signal
