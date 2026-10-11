"""AI pipeline: fetch market data once, run every persona in parallel, aggregate."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone

import pandas as pd

from ai.agents import PROMPT_VERSION, build_context, horizon_info, run_persona, strategy_documents
from ai.confidence_score import aggregate
from ai.evaluation import baselines
from ai.features import extract_features
from ai.live import LiveFeed, apply_live_quote
from ai.llm import JsonLLM, build_llm
from ai.modes import DEFAULT_MODE, ReasoningMode
from ai.personas import Strategy, build_personas
from ai.policy import CallPolicy, apply_policy
from ai.schemas import Prediction
from ai.rag_retrieval import Snippet
from ai.sentiment import score_headlines
from ai.tool import MarketSnapshot, fetch_snapshot
from finance.indicators import atr, flat_band
from finance.linear_regression import run_regression
from finance.risk_management import atr_stop_distance, max_position_fraction

RISK_BUDGET = 0.01  # the sizing example risks 1% of an account per position
LARGE_PANEL_CALLS = 40  # beyond this the free Gemini tier spends most of its time in backoff


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
    modes: Sequence[ReasoningMode] | None = None,
    llm: JsonLLM | None = None,
    snapshot: MarketSnapshot | None = None,
    live_feed: LiveFeed | None = None,
    documents_by_strategy: Mapping[Strategy, list[Snippet]] | None = None,
    regression_daily: pd.DataFrame | None = None,
    policy: CallPolicy | None = None,
    price_signal: Callable[[pd.DataFrame], dict | None] | None = None,
) -> Prediction:
    """`llm`, `snapshot` and `live_feed` are injectable so tests run without network or
    API keys. With a `live_feed`, the snapshot's last price comes from its first tick.
    `policy` may withhold a weak call and adds P(right) (`ai/policy.py`);
    `price_signal` logs model A's probabilities beside the call (`ml/price_signal.py`)."""
    personas = build_personas(strategies, age_bands)
    modes = tuple(modes or (DEFAULT_MODE,))
    llm = llm or build_llm()
    snapshot = snapshot or await asyncio.to_thread(fetch_snapshot, ticker)
    close = snapshot.daily["Close"]
    warnings = [f"{source}: {why}" for source, why in snapshot.errors.items()]
    if live_feed is not None and (warning := await apply_live_quote(snapshot, live_feed)):
        warnings.append(warning)

    try:
        sentiment = await score_headlines(snapshot.ticker, snapshot.headlines, llm)
    except Exception as exc:  # sentiment is an input, not a reason to fail the prediction
        sentiment = None
        warnings.append(f"headline_sentiment: {type(exc).__name__}: sentiment unavailable")

    horizon = horizon_info(snapshot, horizon_days, flat_band(close, horizon_days))
    used = {p.strategy for p in personas}
    contexts = {s: build_context(s, snapshot, horizon, sentiment) for s in used}
    docs = {
        s: list(documents_by_strategy.get(s, [])) if documents_by_strategy is not None else strategy_documents(s, snapshot)
        for s in used
    }

    calls = len(personas) * len(modes)
    if calls > LARGE_PANEL_CALLS:
        warnings.append(f"modes: {calls} persona calls; expect rate-limit backoff on the free tier")
    results = await asyncio.gather(
        *(
            run_persona(p, contexts[p.strategy], docs[p.strategy], llm, mode)
            for p in personas
            for mode in modes
        )
    )
    if all(r.view is None for r in results):
        raise RuntimeError(f"All {len(results)} personas failed; first error: {results[0].error}")
    combined = aggregate(results, strategy_weights)

    try:
        regression = run_regression(regression_daily if regression_daily is not None else snapshot.daily, horizon_days)
    except ValueError as exc:
        regression = None
        warnings.append(f"linear_regression: {exc}")
    try:
        risk = position_risk(snapshot)
    except ValueError as exc:
        risk = None
        warnings.append(f"risk: {exc}")
    price_model = None
    if price_signal is not None:
        try:
            price_model = price_signal(regression_daily if regression_daily is not None else snapshot.daily)
        except Exception as exc:  # a logged side signal, never a reason to fail the prediction
            warnings.append(f"price_model: {type(exc).__name__}: unavailable")

    prediction = Prediction(
        ticker=snapshot.ticker,
        horizon_days=horizon_days,
        direction=combined.direction,
        confidence=combined.confidence,
        net_score=combined.net_score,
        agreement=combined.agreement,
        by_strategy=combined.by_strategy,
        modes=[m.name for m in modes],
        by_mode=combined.by_mode or {},
        stability=combined.stability,
        flat_band_pct=horizon["flat_band_pct"],
        last_price=snapshot.last_price,
        quote_source=snapshot.quote_source,
        data_as_of=str(snapshot.daily.index[-1].date()),
        next_earnings_date=horizon["next_earnings_date"],
        earnings_within_horizon=horizon["earnings_within_horizon"],
        baselines=baselines(
            close, horizon_days, regression.predicted_return_pct if regression else None
        ),
        linear_regression=dataclasses.asdict(regression) if regression else None,
        headline_sentiment=sentiment,
        risk=risk,
        features=extract_features(
            {s.value: c for s, c in contexts.items()},
            dataclasses.asdict(regression) if regression else None,
            sentiment,
        ),
        price_model=price_model,
        generated_at=datetime.now(timezone.utc),
        model=llm.model,
        prompt_version=PROMPT_VERSION,
        personas=list(results),
        data_warnings=warnings,
        input_snapshot={
            "fetched_at": snapshot.fetched_at.isoformat(),
            "selected_strategies": sorted(s.value for s in used),
            "selected_age_bands": sorted({p.age_band.label for p in personas}),
            "strategy_packets": {s.value: context for s, context in contexts.items()},
            "document_references": {s.value: [d.citation_id for d in snippets] for s, snippets in docs.items()},
        },
    )
    return apply_policy(prediction, policy) if policy is not None else prediction
