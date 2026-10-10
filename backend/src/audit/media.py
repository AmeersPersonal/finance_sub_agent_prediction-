"""Company news digest: one LLM call turns recent news into one-line TL;DRs.

Links, sources and dates come from the feed (ai/feeds.py), never from the
model. The model refers to items only by number, so it can't invent a URL. The
model is reached through ai/llm.py's `JsonLLM`, like every other call.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ai.feeds import NewsItem
from ai.llm import JsonLLM

MAX_ITEMS = 8


class ItemSummary(BaseModel):
    item: int = Field(description="Number of the news item this summarises")
    tldr: str = Field(description="One plain sentence: what happened and why it matters for the stock")
    relevance: Literal["high", "medium", "low"] = Field(
        description="How much this item matters for the stock price"
    )


class NewsDigest(BaseModel):
    items: list[ItemSummary]
    summary: str = Field(description="Two sentences on what the news as a whole says about the company")


SYSTEM = (
    "You summarise financial news for a retail investor. Use only the titles and "
    "summaries given: add no facts, numbers or outside knowledge, and refer to each "
    "item by its number."
)


async def news_digest(
    ticker: str, news: list[NewsItem], llm: JsonLLM, limit: int = MAX_ITEMS
) -> dict[str, Any] | None:
    items = [n for n in news if n.title][:limit]
    if not items:
        return None
    listing = "\n".join(
        f"{i}. {n.title}" + (f" -- {n.summary}" if n.summary else "") for i, n in enumerate(items, 1)
    )
    digest = await llm.generate_json(SYSTEM, f"Stock: {ticker}\n\nNews:\n{listing}", NewsDigest)
    by_number = {s.item: s for s in digest.items if 1 <= s.item <= len(items)}
    return {
        "summary": digest.summary,
        "items": [
            {
                "title": n.title,
                "link": n.link,
                "source": n.source,
                "published": n.published,
                "tldr": by_number[i].tldr if i in by_number else None,
                "relevance": by_number[i].relevance if i in by_number else None,
            }
            for i, n in enumerate(items, 1)
        ],
    }
