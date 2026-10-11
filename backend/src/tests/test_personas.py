import pytest

from ai.personas import Strategy, build_personas


def test_full_matrix_excludes_impossible_minor_personas():
    personas = build_personas()
    assert len(personas) == 13  # 3 strategies x 4 adult bands + long_term for 16-17
    minors = [p for p in personas if p.age_band.label == "16-17"]
    assert [p.strategy for p in minors] == [Strategy.LONG_TERM]


def test_filters():
    personas = build_personas([Strategy.DAY_TRADER], ["18-24", "55-65"])
    assert [p.id for p in personas] == ["day_trader:18-24", "day_trader:55-65"]


def test_selection_with_no_eligible_persona_raises():
    with pytest.raises(ValueError, match="16-17"):
        build_personas([Strategy.INDEX_OPTIONS], ["16-17"])
