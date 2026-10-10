"""Risk behind one investment decision, as a checklist a human can read.

`finance/risk_management.py` computes single measures (Altman Z, ATR stop
distance, position size), and the rest of `finance/` holds volatility,
drawdown, leverage and Beneish. This module adds no new math. It reads those
measures plus the prediction's own signal quality (agreement, strength,
stability, earnings in the window) and turns them into flags, each with a level
and a plain reason. Deterministic; no LLM.

`learning_context` explains a forecast's numbers and limits in plain words for
the dashboard; it adds no advice.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ai.schemas import Prediction
from ai.tool import MarketSnapshot
from finance import indicators as ind
from finance.fundamentals import NOT_APPLICABLE_SECTORS, beneish_m_score, financial_health
from finance.positioning import short_interest
from finance.risk_management import altman_z, altman_z_ttm

LEVELS = ("low", "medium", "high")
WEAK_AGREEMENT = 0.6
WEAK_STRENGTH = 0.25
UNSTABLE = 0.6
ELEVATED_VOLATILITY = 0.35  # annualised, last year
HIGH_VOLATILITY = 0.60
DEEP_DRAWDOWN = -0.5
HIGH_LEVERAGE = 2.0  # debt / equity
CROWDED_SHORT_PCT = 20.0
MANY_MISSING_SOURCES = 5

Flag = Callable[[str, str, str], None]


def _safe(compute: Callable[..., Any], *args: Any) -> Any:
    try:
        return compute(*args)
    except Exception:
        return None


def decision_risk(prediction: Prediction, snapshot: MarketSnapshot) -> dict[str, Any]:
    """`level` is the worst flag's level ("low" when nothing is flagged); flags are
    sorted worst first."""
    flags: list[dict[str, str]] = []

    def flag(factor: str, level: str, detail: str) -> None:
        flags.append({"factor": factor, "level": level, "detail": detail})

    _signal(prediction, flag)
    _events(prediction, flag)
    _price(prediction, snapshot, flag)
    _company(snapshot, flag)
    if len(snapshot.errors) >= MANY_MISSING_SOURCES:
        flag(
            "data",
            "medium",
            f"{len(snapshot.errors)} data sources were unavailable "
            f"({', '.join(sorted(snapshot.errors))}); personas saw less than usual.",
        )

    flags.sort(key=lambda f: LEVELS.index(f["level"]), reverse=True)
    return {"level": flags[0]["level"] if flags else "low", "flags": flags}


def _signal(p: Prediction, flag: Flag) -> None:
    if p.direction == "unclear":
        flag("signal", "high", f"No call: personas split or leaned only weakly (net {p.net_score:+.2f}).")
        return
    if p.agreement < WEAK_AGREEMENT:
        flag(
            "agreement",
            "medium",
            f"Only {p.agreement:.0%} of personas (strategy-weighted) back the {p.direction} call.",
        )
    if p.confidence < WEAK_STRENGTH:
        flag(
            "strength",
            "medium",
            f"Signal strength {p.confidence:.2f} is weak (and strength isn't a probability).",
        )
    if len(p.modes) > 1 and p.stability is not None and p.stability < UNSTABLE:
        flag(
            "stability",
            "medium",
            f"Only {p.stability:.0%} of samples across reasoning modes match the call.",
        )
    regression = p.baselines.get("linear_regression")
    if p.direction in ("up", "down") and regression and regression != p.direction:
        flag("baseline", "low", f"The linear-regression baseline says {regression}.")


def _events(p: Prediction, flag: Flag) -> None:
    if p.earnings_within_horizon:
        flag(
            "earnings",
            "high",
            f"Earnings on {p.next_earnings_date} fall inside the horizon; the report can "
            "move the price well past the flat band either way.",
        )
    elif p.earnings_within_horizon is None:
        flag(
            "earnings",
            "medium",
            "The earnings calendar was unavailable, so a report inside the horizon can't be ruled out.",
        )


def _price(p: Prediction, snapshot: MarketSnapshot, flag: Flag) -> None:
    close = snapshot.daily["Close"]
    volatility = _safe(ind.annualized_volatility, close.iloc[-ind.TRADING_DAYS :])
    if volatility is not None and volatility >= ELEVATED_VOLATILITY:
        sizing = ""
        if p.risk:
            sizing = (
                f" A 2-ATR stop sits {p.risk['stop_distance_2atr_pct']}% away, so risking 1% "
                f"of an account caps the position at "
                f"{p.risk['max_position_pct_of_account_risking_1pct']}% of it."
            )
        flag(
            "volatility",
            "high" if volatility >= HIGH_VOLATILITY else "medium",
            f"Annualised volatility over the last year is {volatility:.0%}.{sizing}",
        )
    drawdown = _safe(ind.max_drawdown, close)
    if drawdown is not None and drawdown <= DEEP_DRAWDOWN:
        years = round((close.index[-1] - close.index[0]).days / 365.25)
        flag("drawdown", "medium", f"The stock fell {-drawdown:.0%} peak to trough within {years} years.")


def _company(snapshot: MarketSnapshot, flag: Flag) -> None:
    info = snapshot.info
    sector, market_cap = info.get("sector"), info.get("marketCap")
    z = _safe(
        altman_z_ttm, snapshot.quarterly_balance, snapshot.quarterly_income, market_cap, sector
    ) or _safe(altman_z, snapshot.balance_sheet, snapshot.income_stmt, market_cap, sector)
    if z and z["zone"] != "safe":
        flag(
            "bankruptcy_risk",
            "high" if z["zone"] == "distress" else "medium",
            f"Altman Z {z['z_score']:.2f} ({z['basis']} data) is in the {z['zone']} zone.",
        )
    m = _safe(beneish_m_score, snapshot.income_stmt, snapshot.balance_sheet, snapshot.cashflow, sector)
    if m and m["above_threshold_possible_manipulation"]:
        flag(
            "earnings_quality",
            "high",
            f"Beneish M-score {m['m_score']:.2f} is above {m['threshold']}, a pattern seen in "
            "earnings manipulators (a screen, not proof).",
        )
    if sector not in NOT_APPLICABLE_SECTORS:  # banks run on leverage by design
        health = _safe(
            financial_health, snapshot.income_stmt, snapshot.balance_sheet, snapshot.cashflow, info
        ) or {}
        leverage = health.get("debt_to_equity")
        if leverage is not None and leverage > HIGH_LEVERAGE:
            flag("leverage", "medium", f"Debt is {leverage:.1f}x shareholders' equity.")
    short = (_safe(short_interest, info) or {}).get("short_pct_of_float")
    if short is not None and short >= CROWDED_SHORT_PCT:
        flag(
            "short_interest",
            "medium",
            f"{short:.0f}% of the float is sold short; crowded shorts can squeeze sharply.",
        )


STRATEGY_LESSONS = {
    'long_term': 'Long-term investing studies business health and diversification over years. A short forecast does not test a long-term plan.',
    'day_trader': 'Day and swing trading study price action and news. Trading costs and rapid losses affect outcomes; this forecast is measured in days, not minutes.',
    'index_options': 'Options and hedges depend on expiration, volatility, and contract terms. Stock direction alone does not predict an option profit.',
}


def learning_context(prediction) -> dict:
    strategies = sorted({p.strategy for p in prediction.personas})
    return {
        'forecast_question': f'Will {prediction.ticker} rise, fall, or stay inside its flat band over {prediction.horizon_days} trading days?',
        'confidence_meaning': 'Agent signal strength, not a calibrated probability of being correct.',
        'flat_vs_unclear': 'Flat predicts a small price move; unclear means the agents disagree or lean weakly.',
        'regression_meaning': 'An independent historical price/volume benchmark; it does not train on agent opinions.',
        'risk': prediction.risk,
        'risk_meaning': 'An illustrative volatility-based stop and position size. It is not a guarantee against losses or a personal allocation.',
        'strategy_lessons': {s: STRATEGY_LESSONS[s] for s in strategies if s in STRATEGY_LESSONS},
        'personalization': 'Age describes a simulated perspective. Actual goals, experience, and risk tolerance still matter.',
        'evaluation': 'The outcome can be checked after the forecast horizon. Compare performance across many forecasts.',
    }
