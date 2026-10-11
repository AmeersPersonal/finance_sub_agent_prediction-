"""Headline sentiment: one Gemini call scores each headline's bearing on the stock.

The score is fed to the short-horizon personas as a number next to the raw
headlines. Social-media sentiment isn't included: there's no free API for it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ai.llm import JsonLLM

POSITIVE_ABOVE = 0.2  # per-headline scores beyond +/- this count as positive / negative


class HeadlineScore(BaseModel):
    headline: str
    score: float = Field(ge=-1, le=1, description="-1 very negative ... +1 very positive")


class HeadlineSentiment(BaseModel):
    scores: list[HeadlineScore]
    overall: float = Field(
        ge=-1, le=1, description="Net effect of all headlines on the stock, -1 to +1"
    )
    summary: str = Field(description="One sentence on the dominant news theme")


SYSTEM = (
    "You score financial news headlines for their likely effect on one stock's price. "
    "Judge each headline only as it bears on that company; market-wide headlines that "
    "barely mention it score near 0. Don't use outside knowledge of later events."
)


async def score_headlines(ticker: str, headlines: list[str], llm: JsonLLM) -> dict | None:
    if not headlines:
        return None
    numbered = "\n".join(f"{i}. {h}" for i, h in enumerate(headlines, 1))
    result = await llm.generate_json(
        SYSTEM, f"Stock: {ticker}\n\nHeadlines:\n{numbered}", HeadlineSentiment
    )
    scores = [s.score for s in result.scores]
    return {
        "overall": round(result.overall, 2),
        "positive": sum(s > POSITIVE_ABOVE for s in scores),
        "negative": sum(s < -POSITIVE_ABOVE for s in scores),
        "neutral": sum(abs(s) <= POSITIVE_ABOVE for s in scores),
        "summary": result.summary,
    }
