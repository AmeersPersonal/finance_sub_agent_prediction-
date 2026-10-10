import pytest

from ai.confidence_score import aggregate
from ai.schemas import PersonaResult, PersonaView


def result(strategy: str, direction: str, conviction: float) -> PersonaResult:
    return PersonaResult(
        persona_id=f"{strategy}:x",
        strategy=strategy,
        age_band="x",
        view=PersonaView(direction=direction, conviction=conviction, rationale="", key_factors=[]),
    )


def test_unanimous_view_keeps_its_conviction():
    agg = aggregate([result("a", "up", 0.8), result("b", "up", 0.8)])
    assert agg.direction == "up"
    assert agg.confidence == pytest.approx(0.8)
    assert agg.agreement == 1.0


def test_opposing_views_are_unclear_not_flat():
    agg = aggregate([result("a", "up", 0.7), result("b", "down", 0.7)])
    assert agg.direction == "unclear"
    assert agg.confidence == 0.0
    assert agg.agreement == 0.0


def test_personas_expecting_no_move_are_flat():
    agg = aggregate([result("a", "flat", 0.6), result("b", "flat", 0.4), result("c", "up", 0.2)])
    assert agg.direction == "flat"
    assert agg.confidence == pytest.approx((0.6 + 0.4) / 3, abs=1e-4)  # rounded to 4 dp


def test_disagreement_lowers_confidence():
    split = aggregate([result("a", "down", 0.9), result("b", "down", 0.9), result("c", "up", 0.9)])
    assert split.direction == "down"
    assert split.confidence == pytest.approx(0.3)
    assert split.agreement == pytest.approx(2 / 3, abs=1e-3)


def test_strategies_count_equally_regardless_of_persona_count():
    # Three bullish personas in one strategy vs one bearish in another: one vote each.
    views = [result("a", "up", 0.6)] * 3 + [result("b", "down", 0.6)]
    agg = aggregate(views)
    assert agg.net_score == 0.0
    assert agg.direction == "unclear"
    assert agg.by_strategy == {"a": 0.6, "b": -0.6}


def test_failed_personas_are_skipped():
    failed = PersonaResult(persona_id="c:x", strategy="c", age_band="x", error="boom")
    agg = aggregate([result("a", "up", 0.5), failed])
    assert agg.direction == "up"
    assert agg.by_strategy == {"a": 0.5}


def test_strategy_weights_shift_the_call():
    views = [result("a", "up", 0.6), result("b", "down", 0.6)]
    assert aggregate(views, {"a": 3.0}).direction == "up"
    assert aggregate(views, {"b": 3.0}).direction == "down"


def test_no_views_raises():
    with pytest.raises(ValueError):
        aggregate([PersonaResult(persona_id="a", strategy="a", age_band="x", error="boom")])
