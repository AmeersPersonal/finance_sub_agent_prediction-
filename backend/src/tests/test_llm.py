"""GeminiLLM retry behaviour, against a fake google-genai client (no network)."""

import asyncio
from types import SimpleNamespace

import pytest
from google.genai import errors
from pydantic import ValidationError

import ai.llm as llm_module
from ai.llm import RETRYABLE_STATUS, GeminiLLM
from ai.schemas import PersonaView

GOOD = '{"direction": "up", "conviction": 0.7, "rationale": "r", "key_factors": []}'


def api_error(code: int) -> errors.APIError:
    return errors.APIError(code, {"error": {"code": code, "message": f"HTTP {code}", "status": "X"}})


class FakeModels:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    async def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "temperature": config.temperature})
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)


@pytest.fixture
def make_llm(monkeypatch):
    """Builds a GeminiLLM whose client replays `script`; returns (llm, models, sleeps)."""
    sleeps = []

    async def no_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(llm_module.asyncio, "sleep", no_sleep)

    def build(script, **kwargs):
        models = FakeModels(script)

        def client(*, http_options):
            models.http_options = http_options
            return SimpleNamespace(aio=SimpleNamespace(models=models))

        monkeypatch.setattr(llm_module.genai, "Client", client)
        return GeminiLLM(**kwargs), models, sleeps

    return build


def run(llm, **kwargs):
    return asyncio.run(llm.generate_json("system", "prompt", PersonaView, **kwargs))


@pytest.mark.parametrize("code", sorted(RETRYABLE_STATUS))
def test_retryable_errors_are_retried_with_backoff(make_llm, code):
    llm, models, sleeps = make_llm([api_error(code), api_error(code), GOOD])
    assert run(llm).direction == "up"
    assert len(models.calls) == 3 and sleeps == [2, 4]


def test_other_errors_raise_immediately(make_llm):
    llm, models, sleeps = make_llm([api_error(400), GOOD])
    with pytest.raises(errors.APIError):
        run(llm)
    assert len(models.calls) == 1 and sleeps == []


def test_gives_up_after_max_attempts(make_llm):
    llm, models, sleeps = make_llm([api_error(429)] * 3, max_attempts=3)
    with pytest.raises(errors.APIError) as exc_info:
        run(llm)
    assert exc_info.value.code == 429
    assert len(models.calls) == 3 and sleeps == [2, 4]  # no sleep after the last attempt


def test_off_schema_json_is_retried_then_raised(make_llm):
    llm, models, _ = make_llm(["not json", GOOD])
    assert run(llm).conviction == 0.7 and len(models.calls) == 2
    llm, models, _ = make_llm(['{"direction": "sideways"}'] * 2, max_attempts=2)
    with pytest.raises(ValidationError):
        run(llm)


def test_per_call_model_and_temperature(make_llm, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "env-model")
    llm, models, _ = make_llm([GOOD, GOOD])
    run(llm)
    run(llm, model="other-model", temperature=0.2)
    assert models.calls == [
        {"model": "env-model", "temperature": None},
        {"model": "other-model", "temperature": 0.2},
    ]


def test_requests_time_out(make_llm):
    _, models, _ = make_llm([GOOD])
    assert models.http_options.timeout == 30_000  # milliseconds; a hung call can't stall a forecast


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiLLM()
