import asyncio

import pytest

import main
from ai.main import predict
from ai.policy import apply_policy, from_dict, load_policy, save_policy
from database.repository import same_forecast

CURVE = [[0.0, 0.3], [0.5, 0.4], [1.0, 0.6]]


def _policy(min_strength=0.3, enabled=True, curve=CURVE):
    return from_dict({
        "abstain": {"5": {"enabled": enabled, "min_strength": min_strength},
                    "1": {"enabled": False, "reason": "too few"}},
        "calibration": {"enabled": curve is not None, "curve": curve},
    })


def test_only_rules_that_passed_are_used():
    policy = _policy()
    assert policy.abstain == {5: 0.3}
    assert policy.p_correct(0.25) == pytest.approx(0.35)
    off = _policy(enabled=False, curve=None)
    assert off.abstain == {} and off.p_correct(0.9) is None


def test_policy_round_trips_and_is_optional(tmp_path):
    path = tmp_path / "call_policy.json"
    assert load_policy(path) is None
    save_policy({"abstain": {"5": {"enabled": True, "min_strength": 0.4}}}, path)
    assert load_policy(path).abstain == {5: 0.4}


def test_predict_withholds_a_weak_call_and_keeps_its_numbers(snapshot, fake_llm):
    # The fake personas call up at strength 0.2 (see test_pipeline).
    prediction = asyncio.run(predict("TEST", llm=fake_llm, snapshot=snapshot, policy=_policy(0.3)))
    assert prediction.direction == "unclear" and prediction.withheld_call == "up"
    assert prediction.confidence == pytest.approx(0.2) and prediction.net_score == pytest.approx(0.2)
    assert prediction.p_correct is None  # no probability for a withheld call
    assert any(w.startswith("policy: up call withheld") for w in prediction.data_warnings)
    assert "a up call at strength 0.20 was withheld" in main.render(prediction)


def test_predict_adds_p_correct_to_a_call_that_stands(snapshot, fake_llm):
    prediction = asyncio.run(predict("TEST", llm=fake_llm, snapshot=snapshot, policy=_policy(0.1)))
    assert prediction.direction == "up" and prediction.withheld_call is None
    assert prediction.p_correct == pytest.approx(0.34)
    assert "Calibrated chance this call is right: 34%" in main.render(prediction)


def test_policy_ignores_other_horizons(snapshot, fake_llm):
    prediction = asyncio.run(
        predict("TEST", horizon_days=1, llm=fake_llm, snapshot=snapshot, policy=_policy(0.9, curve=None))
    )
    assert prediction.direction == "up"


def test_price_signal_is_logged_and_never_fails_the_prediction(snapshot, fake_llm):
    seen = []

    def signal(daily):
        seen.append(len(daily))
        return {"name": "price-logistic-5d-absolute", "p_up": 0.5, "p_flat": 0.2, "p_down": 0.3,
                "passes_gate": False}

    prediction = asyncio.run(predict("TEST", llm=fake_llm, snapshot=snapshot, price_signal=signal))
    assert seen == [len(snapshot.daily)] and prediction.price_model["p_up"] == 0.5
    assert "model A (price-logistic-5d-absolute, logged only, failed its gate)" in main.render(prediction)
    for _, prompt in fake_llm.calls:
        assert "p_flat" not in prompt  # never shown to the personas

    def broken(daily):
        raise RuntimeError("boom")

    prediction = asyncio.run(predict("TEST", llm=fake_llm, snapshot=snapshot, price_signal=broken))
    assert prediction.price_model is None
    assert "price_model: RuntimeError: unavailable" in prediction.data_warnings


def test_forecasts_saved_before_new_fields_still_match(snapshot, fake_llm):
    prediction = asyncio.run(predict("TEST", llm=fake_llm, snapshot=snapshot))
    stored = prediction.model_dump(mode="json")
    older = {k: v for k, v in stored.items() if k not in ("withheld_call", "p_correct", "price_model")}
    assert same_forecast(stored, prediction) and same_forecast(older, prediction)
    assert not same_forecast({**stored, "direction": "down"}, prediction)
    changed = prediction.model_copy(update={"p_correct": 0.5})
    assert not same_forecast(older, changed)  # a new field with a value is a real difference


def test_cli_flags_load_the_policy_and_model_a(monkeypatch, capsys):
    args = main.parse_args(["AAPL", "--policy", "--price-model", "--horizon", "7"])
    monkeypatch.setattr(main, "load_policy", lambda: None)
    assert main.load_extras(args) == (None, None)
    err = capsys.readouterr().err
    assert "python -m ml coverage --save" in err and "--horizon 7 --save" in err
    monkeypatch.setattr(main, "load_policy", lambda: _policy())
    policy, _ = main.load_extras(main.parse_args(["AAPL", "--policy"]))
    assert policy.abstain == {5: 0.3}
    assert "abstain below 0.30 at 5d, calibrated P(right)" in capsys.readouterr().err
