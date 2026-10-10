"""Explain existing forecast/risk calculations without inventing advice."""

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
