"""Flatten what the personas saw into one numeric row, logged with every prediction.

Point-in-time data (insiders, 13F, options, short interest) can't be recovered
historically, so this row is the only way to train a stacker on it later
(`ml/spec.md`, Phase 0). It reuses the strategy packets: no new data, no new math.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

# Shared by every strategy's packet; stored once, unprefixed.
COMMON_KEYS = frozenset(
    {"last_price", "previous_close", "change_today_pct", "horizon"}
)
# Identifiers and free text: not features.
SKIP_KEYS = frozenset(
    {"ticker", "company", "sector", "market_state", "unavailable_sources", "headlines"}
)


def _flatten(prefix: str, value: Any, out: dict[str, float | None]) -> None:
    if isinstance(value, Mapping):
        for key, inner in value.items():
            if key not in SKIP_KEYS:
                _flatten(f"{prefix}.{key}" if prefix else str(key), inner, out)
    elif isinstance(value, bool):
        out[prefix] = float(value)
    elif isinstance(value, (int, float)):
        out[prefix] = float(value) if math.isfinite(value) else None
    elif value is None:
        out[prefix] = None
    elif isinstance(value, (list, tuple)) and all(
        v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)) for v in value
    ):
        for i, item in enumerate(value):
            _flatten(f"{prefix}.{i}", item, out)
    # strings and mixed lists (dates, labels, headlines) are dropped


def extract_features(
    contexts: Mapping[str, Mapping[str, Any]],
    regression: Mapping[str, Any] | None = None,
    sentiment: Mapping[str, Any] | None = None,
) -> dict[str, float | None]:
    """`contexts` maps strategy name -> the packet its personas reasoned over.

    Keys are `<strategy>.<path>` (e.g. `long_term.valuation.trailing_pe`), shared
    keys are unprefixed, regression output is `regression.<field>`. Values are
    floats or None; a missing metric stays None rather than being dropped, so
    the column set is stable across rows.
    """
    out: dict[str, float | None] = {}
    for strategy, context in contexts.items():
        for key, value in context.items():
            if key in SKIP_KEYS:
                continue
            if key in COMMON_KEYS:
                _flatten(key, value, out)
            else:
                _flatten(f"{strategy}.{key}", value, out)
    if regression:
        _flatten("regression", regression, out)
    if sentiment:
        _flatten("sentiment", sentiment, out)
    return out
