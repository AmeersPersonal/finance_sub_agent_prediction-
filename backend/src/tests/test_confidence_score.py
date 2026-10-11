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


def moded(persona: str, mode: str, direction: str, conviction: float) -> PersonaResult:
    return PersonaResult(
        persona_id=persona,
        strategy=persona.split(":")[0],
        age_band="x",
        mode=mode,
        view=PersonaView(direction=direction, conviction=conviction, rationale="", key_factors=[]),
    )


def test_extra_modes_do_not_add_weight():
    # Strategy a is sampled under three modes, b under one: still one vote each.
    results = [moded("a:1", m, "up", 0.6) for m in ("m1", "m2", "m3")] + [
        moded("b:1", "m1", "down", 0.6)
    ]
    agg = aggregate(results)
    assert agg.net_score == 0.0 and agg.direction == "unclear"
    assert agg.by_strategy == {"a": 0.6, "b": -0.6}


def test_modes_are_averaged_inside_a_persona():
    agg = aggregate([moded("a:1", "m1", "up", 0.8), moded("a:1", "m2", "down", 0.4)])
    assert agg.net_score == pytest.approx(0.2)  # (0.8 - 0.4) / 2
    assert agg.direction == "up"
    assert agg.stability == 0.5
    assert agg.by_mode == {"m1": 0.8, "m2": -0.4}


def test_a_failed_mode_is_skipped():
    failed = PersonaResult(persona_id="a:1", strategy="a", age_band="x", mode="m2", error="boom")
    agg = aggregate([moded("a:1", "m1", "up", 0.5), failed])
    assert agg.direction == "up" and agg.stability == 1.0 and list(agg.by_mode) == ["m1"]
