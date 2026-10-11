"""The trader personas: strategy x age band, minus combinations that can't exist."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Strategy(str, Enum):
    LONG_TERM = "long_term"
    DAY_TRADER = "day_trader"
    INDEX_OPTIONS = "index_options"


STRATEGY_TITLES = {
    Strategy.LONG_TERM: "long-term stock holder",
    Strategy.DAY_TRADER: "day trader",
    Strategy.INDEX_OPTIONS: "S&P 500 index and options (calls/puts) trader",
}

STRATEGY_PROFILES = {
    Strategy.LONG_TERM: (
        "Buys businesses, not tickers. Cares about revenue growth, valuation, the balance "
        "sheet and the 5-year trend; ignores day-to-day noise. Natural horizon: years."
    ),
    Strategy.DAY_TRADER: (
        "Trades intraday price action and volume: VWAP, RSI, gaps, momentum and news "
        "catalysts. Flat by the close; ignores fundamentals. Natural horizon: minutes to a day."
    ),
    Strategy.INDEX_OPTIONS: (
        "Trades the S&P 500 (SPY/SPX) and calls/puts. Reads implied volatility, put/call "
        "ratios, the VIX and how the stock moves with the index. Natural horizon: days to weeks."
    ),
}


@dataclass(frozen=True)
class AgeBand:
    label: str
    min_age: int
    max_age: int
    profile: str


# Working assumptions, not survey data. A sourced profile dropped into
# ai/docs/age_profiles/<label>.md replaces the text below (see rag_retrieval).
AGE_BANDS = (
    AgeBand(
        "16-17", 16, 17,
        "Trades through a custodial or youth cash account an adult controls: small balance, "
        "no margin, options or short selling. Learns from social media and family; tends to "
        "buy well-known brands and hold.",
    ),
    AgeBand(
        "18-24", 18, 24,
        "Small account, long runway, high risk tolerance. Leans on social media, Reddit and "
        "finfluencers; drawn to momentum and popular names.",
    ),
    AgeBand(
        "25-39", 25, 39,
        "Growing income and account size. Mixes growth investing with active trading; the "
        "group most likely to use options.",
    ),
    AgeBand(
        "40-54", 40, 54,
        "Larger portfolio and family obligations. Leans on fundamentals and diversification; "
        "more cautious with speculative positions.",
    ),
    AgeBand(
        "55-65", 55, 65,
        "Nearing retirement. Prioritises capital preservation, dividends and low volatility; "
        "reacts strongly to drawdowns.",
    ),
)

# Under-18s can only use custodial/youth cash accounts: no margin means no short
# selling or options, and unsettled-cash rules make real day trading impractical.
MINOR_STRATEGIES = frozenset({Strategy.LONG_TERM})


@dataclass(frozen=True)
class Persona:
    strategy: Strategy
    age_band: AgeBand

    @property
    def id(self) -> str:
        return f"{self.strategy.value}:{self.age_band.label}"


def is_eligible(strategy: Strategy, band: AgeBand) -> bool:
    return band.min_age >= 18 or strategy in MINOR_STRATEGIES


def build_personas(
    strategies: list[Strategy] | None = None, age_bands: list[str] | None = None
) -> list[Persona]:
    """Every eligible strategy x age-band persona, optionally filtered."""
    chosen_strategies = strategies or list(Strategy)
    chosen_bands = [b for b in AGE_BANDS if age_bands is None or b.label in age_bands]
    personas = [
        Persona(strategy, band)
        for strategy in chosen_strategies
        for band in chosen_bands
        if is_eligible(strategy, band)
    ]
    if not personas:
        raise ValueError(
            "No eligible personas for that selection (ages 16-17 can only be long_term)"
        )
    return personas
