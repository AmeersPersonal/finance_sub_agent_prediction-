"""AI pipeline: fetch market data once, run every persona in parallel, aggregate."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Mapping
from datetime import datetime, timezone

from ai.agents import PROMPT_VERSION, build_context, horizon_info, run_persona, strategy_documents
from ai.confidence_score import aggregate
from ai.evaluation import baselines
from ai.llm import GeminiLLM, JsonLLM
from ai.personas import Strategy, build_personas
from ai.schemas import Prediction
from ai.sentiment import score_headlines
from ai.tool import MarketSnapshot, fetch_snapshot
from finance.indicators import atr, flat_band
from finance.linear_regression import run_regression
from finance.risk_management import atr_stop_distance, max_position_fraction

RISK_BUDGET = 0.01  # the sizing example risks 1% of an account per position


def position_risk(snapshot: MarketSnapshot) -> dict:
    """A 2-ATR stop and the position size that risks 1% of an account on it."""
    atr_value = atr(snapshot.daily)
    stop = atr_stop_distance(atr_value, snapshot.last_price)
    return {
        "atr_14_pct": round(atr_value / snapshot.last_price * 100, 2),
        "stop_distance_2atr_pct": round(stop * 100, 2),
        "max_position_pct_of_account_risking_1pct": round(
            max_position_fraction(RISK_BUDGET, stop) * 100, 1
        ),
    }


async def predict(
    ticker: str,
    horizon_days: int = 5,
    strategies: list[Strategy] | None = None,
    age_bands: list[str] | None = None,
    strategy_weights: Mapping[str, float] | None = None,
    llm: JsonLLM | None = None,
    snapshot: MarketSnapshot | None = None,
) -> Prediction:
    """`llm` and `snapshot` are injectable so tests run without network or API keys."""
    personas = build_personas(strategies, age_bands)
    llm = llm or GeminiLLM()
    snapshot = snapshot or await asyncio.to_thread(fetch_snapshot, ticker)
    close = snapshot.daily["Close"]
    warnings = [f"{source}: {why}" for source, why in snapshot.errors.items()]

    try:
        sentiment = await score_headlines(snapshot.ticker, snapshot.headlines, llm)
    except Exception as exc:  # sentiment is an input, not a reason to fail the prediction
        sentiment = None
        warnings.append(f"headline_sentiment: {type(exc).__name__}: {exc}")

    horizon = horizon_info(snapshot, horizon_days, flat_band(close, horizon_days))
    used = {p.strategy for p in personas}
    contexts = {s: build_context(s, snapshot, horizon, sentiment) for s in used}
    docs = {s: strategy_documents(s, snapshot) for s in used}

    results = await asyncio.gather(
        *(run_persona(p, contexts[p.strategy], docs[p.strategy], llm) for p in personas)
    )
    if all(r.view is None for r in results):
        raise RuntimeError(f"All {len(results)} personas failed; first error: {results[0].error}")
    combined = aggregate(results, strategy_weights)

    try:
        regression = run_regression(snapshot.daily, horizon_days)
    except ValueError as exc:
        regression = None
        warnings.append(f"linear_regression: {exc}")
    try:
        risk = position_risk(snapshot)
    except ValueError as exc:
        risk = None
        warnings.append(f"risk: {exc}")

    return Prediction(
        ticker=snapshot.ticker,
        horizon_days=horizon_days,
        direction=combined.direction,
        confidence=combined.confidence,
        net_score=combined.net_score,
        agreement=combined.agreement,
        by_strategy=combined.by_strategy,
        flat_band_pct=horizon["flat_band_pct"],
        last_price=snapshot.last_price,
        data_as_of=str(snapshot.daily.index[-1].date()),
        next_earnings_date=horizon["next_earnings_date"],
        earnings_within_horizon=horizon["earnings_within_horizon"],
        baselines=baselines(
            close, horizon_days, regression.predicted_return_pct if regression else None
        ),
        linear_regression=dataclasses.asdict(regression) if regression else None,
        headline_sentiment=sentiment,
        risk=risk,
        generated_at=datetime.now(timezone.utc),
        model=llm.model,
        prompt_version=PROMPT_VERSION,
        personas=list(results),
        data_warnings=warnings,
    )
