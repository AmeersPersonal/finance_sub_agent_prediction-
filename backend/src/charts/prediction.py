"""Charts that explain one saved forecast."""

from __future__ import annotations

from typing import Any

from ai.schemas import Prediction
from charts.base import chart, num

DIRECTIONS = ("up", "flat", "down")
SIGN = {"up": 1.0, "flat": 0.0, "down": -1.0}


def _votes(prediction: Prediction):
    return [r for r in prediction.personas if r.view is not None]


def prediction_charts(prediction: Prediction) -> list[dict[str, Any]]:
    charts = []
    votes = _votes(prediction)

    if votes:
        counts = {d: sum(r.view.direction == d for r in votes) for d in DIRECTIONS}
        charts.append(chart(
            "direction_votes", "How the personas voted", "bar", list(DIRECTIONS),
            [{"name": "Votes", "kind": "bar", "data": [counts[d] for d in DIRECTIONS]}],
            y_label="Persona votes",
            caption=f"Call: {prediction.direction}. Flat means expected to stay inside the "
                    f"+/-{prediction.flat_band_pct:g}% band; it is not the same as unclear.",
        ))
        labels = [f"{r.persona_id} [{r.mode}]" if len(prediction.modes) > 1 else r.persona_id for r in votes]
        charts.append(chart(
            "persona_conviction", "Conviction by persona", "bar", labels,
            [{"name": "Signed conviction", "kind": "bar",
              "data": [num(SIGN[r.view.direction] * r.view.conviction, 3) for r in votes],
              "group": [r.strategy for r in votes]}],
            y_label="Down (-1) to up (+1)",
            caption="Direction times conviction. Bars are grouped by strategy.",
        ))

    if prediction.by_strategy:
        names = sorted(prediction.by_strategy)
        charts.append(chart(
            "strategy_scores", "Net score by strategy", "bar", names,
            [{"name": "Net score", "kind": "bar", "data": [num(prediction.by_strategy[n], 3) for n in names]}],
            y_label="Down (-1) to up (+1)",
            caption="Each strategy gets one vote, however many personas it has.",
        ))
    if len(prediction.by_mode) > 1:
        names = sorted(prediction.by_mode)
        charts.append(chart(
            "mode_scores", "Net score by reasoning mode", "bar", names,
            [{"name": "Net score", "kind": "bar", "data": [num(prediction.by_mode[n], 3) for n in names]}],
            y_label="Down (-1) to up (+1)",
        ))

    signal = {"Signal strength": prediction.confidence, "Agreement": prediction.agreement}
    if prediction.stability is not None:
        signal["Stability"] = prediction.stability
    charts.append(chart(
        "signal", "Signal summary", "bar", list(signal),
        [{"name": "Value", "kind": "bar", "data": [num(v, 3) for v in signal.values()]}],
        y_label="0 to 1",
        caption="Signal strength is not a probability that the call is right.",
    ))

    band, price = prediction.flat_band_pct / 100, prediction.last_price
    rows = [
        ("Flat band low", price * (1 - band)),
        ("Last price", price),
        ("Flat band high", price * (1 + band)),
    ]
    regression = prediction.linear_regression or {}
    if regression.get("predicted_return_pct") is not None:
        rows.append(("Regression", price * (1 + regression["predicted_return_pct"] / 100)))
    charts.append(chart(
        "price_band", f"Where {prediction.ticker} would count as flat", "range",
        [name for name, _ in rows],
        [{"name": "Price", "kind": "bar", "data": [num(v, 2) for _, v in rows]}],
        y_label="Price",
        caption=f"Over {prediction.horizon_days} trading days, a move inside the band counts as flat.",
    ))

    strategy, hold = regression.get("strategy"), regression.get("buy_and_hold")
    if strategy and hold:
        metrics = [("total_return_pct", "Total return %"), ("max_drawdown_pct", "Max drawdown %")]
        charts.append(chart(
            "regression_vs_hold", "Regression walk-forward vs buy and hold", "bar",
            [label for _, label in metrics],
            [
                {"name": "Regression", "kind": "bar", "data": [num(strategy.get(k), 2) for k, _ in metrics]},
                {"name": "Buy and hold", "kind": "bar", "data": [num(hold.get(k), 2) for k, _ in metrics]},
            ],
            caption=f"Out-of-sample, non-overlapping periods, {regression.get('cost_bps', 0):g} bps costs.",
        ))

    called = {"Personas": prediction.direction, **prediction.baselines}
    charts.append(chart(
        "baselines", "The call next to the naive baselines", "table", list(called),
        [{"name": "Call", "kind": "table", "data": list(called.values())}],
    ))
    return charts
