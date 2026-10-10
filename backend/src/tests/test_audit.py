import asyncio

import pytest

from ai.main import predict
from audit.analysis import audit_prediction
from audit.info import company_overview, validate
from audit.media import news_digest
from audit.risk import decision_risk


@pytest.fixture
def prediction(snapshot, fake_llm):
    return asyncio.run(predict("TEST", llm=fake_llm, snapshot=snapshot))


def _checks(snapshot) -> dict:
    return {c["check"]: c["ok"] for c in validate(snapshot)}


def test_company_overview_truncates_the_summary(snapshot):
    snapshot.info["longBusinessSummary"] = "word " * 200
    overview = company_overview(snapshot)
    assert overview["name"] == "Test Corp" and overview["sector"] == "Technology"
    assert len(overview["summary"]) <= 403 and overview["summary"].endswith("...")


def test_validation_passes_on_clean_data(snapshot):
    checks = _checks(snapshot)
    assert checks["fresh_prices"] and checks["quote_matches_history"]
    assert checks["enough_history"] and checks["sources_complete"]
    assert checks["is_equity"] is None  # the fixture has no quoteType: unknown, not failed


def test_validation_catches_bad_inputs(snapshot):
    snapshot.info.update(quoteType="ETF", currency="EUR")
    snapshot.last_price *= 4  # e.g. a pre-split quote against post-split history
    snapshot.errors = {"options": "HTTPError: 429"}
    snapshot.daily = snapshot.daily.iloc[-130:-30]  # short, and its last bar is weeks old
    checks = _checks(snapshot)
    assert not any(checks.values())
    etf = next(c for c in validate(snapshot) if c["check"] == "is_equity")
    assert "no statements" in etf["detail"]


def test_risk_flags_earnings_inside_the_horizon_first(prediction, snapshot):
    risk = decision_risk(prediction, snapshot)
    assert risk["level"] == "high"
    assert risk["flags"][0]["factor"] == "earnings"
    levels = [f["level"] for f in risk["flags"]]
    assert levels == sorted(levels, key=["low", "medium", "high"].index, reverse=True)


def test_risk_flags_an_unclear_call_and_company_distress(prediction, snapshot):
    unclear = prediction.model_copy(update={"direction": "unclear", "earnings_within_horizon": False})
    snapshot.info.update(marketCap=1e8, shortPercentOfFloat=0.3)  # tiny equity cushion, crowded short
    snapshot.quarterly_balance.loc["Retained Earnings", snapshot.quarterly_balance.columns[0]] = -100e9
    factors = {f["factor"]: f["level"] for f in decision_risk(unclear, snapshot)["flags"]}
    assert factors["signal"] == "high"
    assert factors["bankruptcy_risk"] in ("medium", "high")
    assert factors["short_interest"] == "medium"
    assert "earnings" not in factors


def test_risk_is_low_when_nothing_is_flagged(prediction, snapshot):
    calm = prediction.model_copy(update={
        "earnings_within_horizon": False, "agreement": 1.0, "confidence": 0.8,
        "baselines": {"always_up": "up", "momentum": "up"},
    })
    snapshot.daily = snapshot.daily.iloc[-300:]  # recent window without a deep drawdown
    risk = decision_risk(calm, snapshot)
    assert risk == {"level": "low", "flags": []}


def test_news_digest_takes_links_from_the_feed_not_the_model(snapshot, fake_llm):
    digest = asyncio.run(news_digest("TEST", snapshot.news, fake_llm))
    assert digest["summary"] == "Results beat."
    [item] = digest["items"]  # the model's made-up item 99 is ignored
    assert item["link"] == "https://finance.yahoo.com/news/test-corp-beats"
    assert (item["tldr"], item["relevance"]) == ("Beat on revenue.", "high")
    assert "1. Test Corp beats estimates -- Revenue topped forecasts." in fake_llm.digest_prompts[0]


def test_news_digest_without_news_makes_no_call(fake_llm):
    assert asyncio.run(news_digest("TEST", [], fake_llm)) is None
    assert fake_llm.digest_prompts == []


def test_audit_combines_all_parts(prediction, snapshot, fake_llm):
    audit = asyncio.run(audit_prediction(prediction, snapshot, fake_llm))
    assert set(audit) == {"company", "checks", "risk", "news", "warnings"}
    assert audit["news"]["items"][0]["tldr"] == "Beat on revenue."
    assert audit["warnings"] == []
    free = asyncio.run(audit_prediction(prediction, snapshot, fake_llm, news=False))
    assert free["news"] is None and len(fake_llm.digest_prompts) == 1


def test_a_failed_digest_is_a_warning_not_an_error(prediction, snapshot):
    class BrokenLLM:
        model = "broken"

        async def generate_json(self, *args, **kwargs):
            raise RuntimeError("quota")

    audit = asyncio.run(audit_prediction(prediction, snapshot, BrokenLLM()))
    assert audit["news"] is None and audit["warnings"] == ["news_digest: RuntimeError: quota"]
    assert audit["risk"]["level"] == "high"


def test_audit_round_trips_through_the_prediction(prediction, snapshot, fake_llm):
    prediction.audit = asyncio.run(audit_prediction(prediction, snapshot, fake_llm))
    reloaded = type(prediction).model_validate_json(prediction.model_dump_json())
    assert reloaded.audit["risk"]["level"] == "high"
