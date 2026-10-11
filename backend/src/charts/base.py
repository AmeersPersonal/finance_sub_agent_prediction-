"""The one chart shape every builder returns.

    {
      "id": "price",                 # stable key the frontend can place by
      "title": "...",
      "kind": "candlestick" | "line" | "bar" | "range" | "table",
      "x": ["2026-10-08", ...],      # shared x values (dates or category labels)
      "series": [{"name": "...", "kind": "line" | "bar" | "candlestick", "data": [...]}],
      "y_label": "...",              # optional axis label / unit
      "reference_lines": [{"label": "Overbought", "value": 70}],   # "axis": "x" for a vertical line
      "caption": "plain-words note shown under the chart"
    }

Series `data` lines up index for index with `x`. Missing values are `null`
(never NaN, which isn't valid JSON). Candlestick data are `[open, high, low, close]`.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def num(value: Any, digits: int = 4) -> float | None:
    """A JSON-safe float: NaN, inf and missing values become None."""
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return round(value, digits) if math.isfinite(value) else None


def numbers(values: Any, digits: int = 4) -> list[float | None]:
    return [num(v, digits) for v in values]


def iso(index: pd.Index, daily: bool) -> list[str]:
    """Daily bars become dates, intraday bars full timestamps (in the index's timezone)."""
    return [t.strftime("%Y-%m-%d") if daily else t.isoformat() for t in pd.DatetimeIndex(index)]


def chart(
    id: str,
    title: str,
    kind: str,
    x: list,
    series: list[dict[str, Any]],
    *,
    y_label: str | None = None,
    reference_lines: list[dict[str, Any]] | None = None,
    caption: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id, "title": title, "kind": kind, "x": x, "series": series,
        "y_label": y_label, "reference_lines": reference_lines or [], "caption": caption,
    }
