"""Charts of how saved forecasts scored (the `/score` report as JSON)."""

from __future__ import annotations

from typing import Any, Sequence

import pandas as pd

from charts.base import chart, num, numbers


def _bars(id: str, title: str, values: dict[str, float | None], caption: str | None = None):
    names = sorted(values)
    return chart(
        id, title, "bar", names,
        [{"name": "Accuracy", "kind": "bar", "data": [num(values[n], 4) for n in names]}],
        y_label="Share correct (0 to 1)", caption=caption,
    )


ROLLING_WINDOW = 20
MIN_OUTCOMES = 10


def accuracy_over_time(outcomes: Sequence[Any]) -> dict[str, Any] | None:
    """Rolling hit rate of the personas and each baseline, in order of resolution.

    `outcomes` are `ai.evaluation.Outcome`s. Needs `MIN_OUTCOMES`; the window is
    `ROLLING_WINDOW` outcomes, so early points average over fewer (at least 5).
    """
    if len(outcomes) < MIN_OUTCOMES:
        return None
    ordered = sorted(outcomes, key=lambda o: (o.resolved_on, o.prediction.generated_at))
    hits = {"personas": [o.prediction.direction == o.actual for o in ordered]}
    for name in sorted({n for o in ordered for n in o.prediction.baselines}):
        hits[name] = [o.prediction.baselines.get(name) == o.actual if name in o.prediction.baselines
                      else None for o in ordered]
    window = min(ROLLING_WINDOW, len(ordered))
    series = [
        {"name": name, "kind": "line",
         "data": numbers(pd.Series(values, dtype="float").rolling(window, min_periods=5).mean())}
        for name, values in hits.items()
    ]
    return chart(
        "accuracy_over_time", "Accuracy over time", "line",
        [o.resolved_on.isoformat() for o in ordered], series,
        y_label="Share correct (0 to 1)",
        caption=f"Rolling over the last {window} resolved forecasts, ordered by the day each "
                "was scored. Compare the personas with always-up, not with 33%. "
                "Forecasts made on the same day overlap, so treat swings as noisy.",
    )


def score_charts(report: dict[str, Any], outcomes: Sequence[Any] = ()) -> list[dict[str, Any]]:
    """`report` is the dict `api.main._report_json` returns; `outcomes` are the
    `Report.outcomes` behind it (optional: adds the accuracy-over-time chart)."""
    if not report.get("scored"):
        return []
    charts = [_bars(
        "accuracy_vs_baselines", "Personas against the baselines", report["accuracy"],
        "3-way up/flat/down on the same outcomes. Always-up is the bar to beat, not 33%.",
    )]
    relative = report.get("relative") or {}
    if relative.get("accuracy"):
        charts.append(_bars(
            "accuracy_relative", f"Against {relative['benchmark']}: who called the stock's own move",
            relative["accuracy"],
            f"{relative['scored']} forecasts scored on the return relative to {relative['benchmark']}. "
            "Always-up can't profit from a rising market here.",
        ))
    over_time = accuracy_over_time(outcomes)
    if over_time:
        charts.append(over_time)
    for key, id, title in (
        ("by_strategy", "accuracy_by_strategy", "Accuracy by strategy"),
        ("by_age_band", "accuracy_by_age_band", "Accuracy by age band"),
        ("by_mode", "accuracy_by_mode", "Accuracy by reasoning mode"),
        ("by_model", "accuracy_by_model", "Accuracy by model"),
    ):
        if report.get(key):
            charts.append(_bars(id, title, report[key], "Individual persona votes."))

    buckets = report.get("by_confidence") or {}
    if buckets:
        names = list(buckets)  # already in strength order
        charts.append(chart(
            "accuracy_by_strength", "Accuracy by signal strength", "bar", names,
            [
                {"name": "Accuracy", "kind": "bar", "data": [num(buckets[n]["accuracy"]) for n in names]},
                {"name": "Forecasts", "kind": "bar", "data": [buckets[n]["n"] for n in names]},
            ],
            caption="Up and down calls only. If accuracy doesn't rise with strength, "
                    "don't present strength as a chance of being right.",
        ))
    if report.get("strategy_weights"):
        weights = report["strategy_weights"]
        names = sorted(weights)
        charts.append(chart(
            "strategy_weights", "Suggested strategy weights", "bar", names,
            [{"name": "Weight", "kind": "bar", "data": [num(weights[n], 3) for n in names]}],
            caption="About 1.0 is average; shrunk toward 1.0 when there are few votes.",
        ))
    return charts
