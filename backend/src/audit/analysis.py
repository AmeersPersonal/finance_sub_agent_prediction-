"""Audit entry point: explain and sanity-check one prediction for a human reader.

Runs after `ai.main.predict()` on the same snapshot and returns what goes in
`Prediction.audit`: a company overview and data checks (info.py), a risk
checklist for the decision (risk.py), and a news digest with links (media.py,
the only part that calls the LLM, so `news=False` makes the audit free).
"""

from __future__ import annotations

from typing import Any

from ai.llm import JsonLLM
from ai.schemas import Prediction
from ai.tool import MarketSnapshot
from audit.info import company_overview, validate
from audit.media import news_digest
from audit.risk import decision_risk


async def audit_prediction(
    prediction: Prediction, snapshot: MarketSnapshot, llm: JsonLLM, news: bool = True
) -> dict[str, Any]:
    warnings = []
    digest = None
    if news:
        try:
            digest = await news_digest(snapshot.ticker, snapshot.news, llm)
        except Exception as exc:  # the digest is extra context, not a reason to fail
            warnings.append(f"news_digest: {type(exc).__name__}: {exc}")
    return {
        "company": company_overview(snapshot),
        "checks": validate(snapshot),
        "risk": decision_risk(prediction, snapshot),
        "news": digest,
        "warnings": warnings,
    }
