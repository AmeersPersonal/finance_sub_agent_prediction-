"""Ticker lists for the ml commands. Yahoo rejects some symbols over time; the
commands skip a ticker with no history and carry on."""

from __future__ import annotations

# The 25-ticker set of the regression feature experiment (finance/spec.md).
DEFAULT_TICKERS = (
    "SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "XOM",
    "JNJ", "PG", "KO", "WMT", "UNH", "HD", "CAT", "BA", "DIS", "NFLX", "AMD", "INTC", "PFE",
)

# Large caps across every sector, plus the broad ETFs: ~100 names for a model A
# run with more cross-section than the default 25.
LARGE_UNIVERSE = (
    *DEFAULT_TICKERS,
    "ABBV", "ABT", "ACN", "ADBE", "AIG", "AMAT", "AMGN", "AMT", "AVGO", "AXP", "BAC", "BK",
    "BKNG", "BLK", "BMY", "BRK-B", "C", "CL", "CMCSA", "COF", "COP", "COST", "CRM", "CSCO",
    "CVS", "CVX", "DE", "DHR", "DUK", "EMR", "F", "FDX", "GD", "GE", "GILD", "GM", "GS",
    "HON", "IBM", "INTU", "LIN", "LLY", "LMT", "LOW", "MA", "MCD", "MDLZ", "MDT", "MET",
    "MMM", "MO", "MRK", "MS", "NEE", "NKE", "ORCL", "PEP", "PM", "PYPL", "QCOM", "RTX",
    "SBUX", "SCHW", "SO", "SPG", "T", "TGT", "TMO", "TMUS", "TXN", "UNP", "UPS", "USB",
    "V", "VZ", "WFC",
)

UNIVERSES = {"default": DEFAULT_TICKERS, "large": LARGE_UNIVERSE}
