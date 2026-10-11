"""LLM clients against fakes (no network): Gemini retries, the OpenAI-compatible
provider, routing between them, and the reasoning modes built from the environment."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors
from pydantic import ValidationError

import ai.llm as llm_module
from ai.llm import ALT_PREFIX, RETRYABLE_STATUS, GeminiLLM, OpenAICompatibleLLM, RoutingLLM, build_llm
from ai.modes import DEFAULT_STRONG_MODEL, catalog, resolve_modes
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


# --- the second, OpenAI-compatible provider (MockTransport, no network) -----------

def compat(responses, **kwargs):
    """An OpenAICompatibleLLM whose HTTP calls replay `responses` (status, body)."""
    requests = []

    def handle(request):
        requests.append(request)
        status, body = responses.pop(0)
        return httpx.Response(status, json=body)

    llm = OpenAICompatibleLLM(base_url="http://alt.test/v1/", model="small-model",
                              transport=httpx.MockTransport(handle), **kwargs)
    return llm, requests


def chat(content):
    return {"choices": [{"message": {"content": content}}]}


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(llm_module.asyncio, "sleep", sleep)
    return sleeps


def test_compatible_provider_sends_a_json_schema_request(no_sleep):
    llm, requests = compat([(200, chat(GOOD))], api_key="alt-key")
    assert run(llm, temperature=0.3).direction == "up"
    request = requests[0]
    assert str(request.url) == "http://alt.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer alt-key"
    body = json.loads(request.content)
    assert body["model"] == "small-model" and body["temperature"] == 0.3
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"]["properties"]["direction"]


def test_compatible_provider_without_a_key_sends_no_auth_header(no_sleep, monkeypatch):
    monkeypatch.delenv("ALT_LLM_API_KEY", raising=False)
    llm, requests = compat([(200, chat(GOOD))])  # a local Ollama server needs no key
    run(llm)
    assert "authorization" not in requests[0].headers
    assert "temperature" not in json.loads(requests[0].content)


def test_compatible_provider_retries_rate_limits_and_bad_json(no_sleep):
    llm, requests = compat([(429, {}), (200, chat("not json")), (200, chat(GOOD))])
    assert run(llm).conviction == 0.7
    assert len(requests) == 3 and no_sleep == [2, 4]
    llm, requests = compat([(400, {"error": "bad request"})])
    with pytest.raises(httpx.HTTPStatusError):
        run(llm)
    assert len(requests) == 1


def test_compatible_provider_needs_its_settings(monkeypatch):
    monkeypatch.delenv("ALT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("ALT_LLM_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="ALT_LLM_BASE_URL"):
        OpenAICompatibleLLM()


class Recorder:
    def __init__(self, model):
        self.model, self.calls = model, []

    async def generate_json(self, system, prompt, schema, *, temperature=None, model=None):
        self.calls.append((model, temperature))
        return schema.model_validate_json(GOOD)


def test_routing_sends_alt_models_to_the_second_provider():
    primary, alt = Recorder("gemini"), Recorder("small-model")
    router = RoutingLLM(primary, alt)
    assert router.model == "gemini"
    run(router)
    run(router, model="gemini-strong", temperature=1.0)
    run(router, model=ALT_PREFIX + "llama3.1", temperature=0.2)
    assert primary.calls == [(None, None), ("gemini-strong", 1.0)]
    assert alt.calls == [("llama3.1", 0.2)]


def test_build_llm_adds_the_second_provider_only_when_configured(monkeypatch):
    monkeypatch.setattr(llm_module, "GeminiLLM", lambda: Recorder("gemini"))
    monkeypatch.delenv("ALT_LLM_BASE_URL", raising=False)
    assert isinstance(build_llm(), Recorder)
    monkeypatch.setenv("ALT_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ALT_LLM_MODEL", "llama3.1")
    assert isinstance(build_llm(), RoutingLLM)


# --- reasoning modes read the environment ------------------------------------------

def test_strong_model_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL_STRONG", raising=False)
    assert catalog()["strong"].model == DEFAULT_STRONG_MODEL
    monkeypatch.setenv("GEMINI_MODEL_STRONG", "gemini-env-strong")
    modes = {m.name: m for m in resolve_modes("full,models")}
    assert modes["strong"].model == modes["strong-t1.0"].model == "gemini-env-strong"
    assert modes["base-t0.2"].model is None and modes["strong-t0.2"].temperature == 0.2


def test_alt_mode_exists_only_with_a_second_provider(monkeypatch):
    monkeypatch.delenv("ALT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("ALT_LLM_MODEL", raising=False)
    assert "alt" not in catalog()
    for spec in ("alt", "providers", "default,alt"):
        with pytest.raises(ValueError, match="ALT_LLM_BASE_URL"):
            resolve_modes(spec)
    monkeypatch.setenv("ALT_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ALT_LLM_MODEL", "llama3.1")
    assert [(m.name, m.model) for m in resolve_modes("providers")] == [
        ("default", None), ("alt", "alt:llama3.1")]
