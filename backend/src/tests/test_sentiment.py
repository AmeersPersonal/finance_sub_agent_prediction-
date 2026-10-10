import asyncio

from ai.sentiment import HeadlineScore, HeadlineSentiment, score_headlines


class ScriptedLLM:
    model = "scripted"

    def __init__(self, scores):
        self.scores, self.calls = scores, 0

    async def generate_json(self, system, prompt, schema):
        self.calls += 1
        return HeadlineSentiment(
            scores=[HeadlineScore(headline=f"h{i}", score=s) for i, s in enumerate(self.scores)],
            overall=0.123,
            summary="Mixed.",
        )


def test_scores_are_bucketed():
    llm = ScriptedLLM([0.8, 0.1, -0.5, -0.2])
    result = asyncio.run(score_headlines("TEST", ["a", "b", "c", "d"], llm))
    assert result == {"overall": 0.12, "positive": 1, "negative": 1, "neutral": 2, "summary": "Mixed."}


def test_no_headlines_means_no_llm_call():
    llm = ScriptedLLM([])
    assert asyncio.run(score_headlines("TEST", [], llm)) is None
    assert llm.calls == 0
