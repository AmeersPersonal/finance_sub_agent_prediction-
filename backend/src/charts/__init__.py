"""Chart-ready JSON for the frontend. Pure functions: no network, no database, no LLM.

Every builder returns a list of chart dicts in the shape `base.chart` documents,
so the frontend needs one renderer, not one per endpoint.
"""

from charts.backtest import backtest_charts
from charts.base import chart
from charts.prediction import prediction_charts
from charts.price import price_charts
from charts.score import score_charts

__all__ = ["backtest_charts", "chart", "prediction_charts", "price_charts", "score_charts"]
