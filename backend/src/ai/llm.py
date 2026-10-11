"""LLM access. The only module that talks to model providers.

Gemini is the default provider. A second, OpenAI-compatible provider (OpenAI,
Groq, OpenRouter, or a local Ollama server) adds real model diversity: set
`ALT_LLM_BASE_URL` and `ALT_LLM_MODEL` (plus `ALT_LLM_API_KEY` unless the server
is local and keyless), and `build_llm()` routes any model named `alt:<model>`
to it. The `alt` reasoning mode (`ai/modes.py`) uses that prefix.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Protocol, TypeVar

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

DEFAULT_MODEL = "gemini-3.5-flash-lite"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
ALT_PREFIX = "alt:"
ALT_TIMEOUT_SECONDS = 60  # local models on a laptop are slower than a hosted API

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class JsonLLM(Protocol):
    model: str

    async def generate_json(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        *,
        temperature: float | None = None,
        model: str | None = None,
    ) -> T: ...


class GeminiLLM:
    """Structured-output calls with a concurrency cap and backoff on rate limits.

    The free tier allows only a handful of requests per minute, so a full
    13-persona run will spend time in backoff; lower `max_concurrency` or run a
    subset of personas if that's too slow.
    """

    def __init__(
        self, model: str | None = None, max_concurrency: int = 4, max_attempts: int = 4
    ) -> None:
        if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
            raise RuntimeError("GEMINI_API_KEY is not set; add it to backend/.env")
        self._client = genai.Client(http_options=types.HttpOptions(timeout=30_000))
        self.model = model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_attempts = max_attempts

    async def aclose(self) -> None:
        await self._client.aio.aclose()

    async def generate_json(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        *,
        temperature: float | None = None,
        model: str | None = None,
    ) -> T:
        """`model` and `temperature` override this client's defaults for one call."""
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
            temperature=temperature,
        )
        model_name = model or self.model
        async with self._semaphore:
            for attempt in range(1, self._max_attempts + 1):
                try:
                    response = await self._client.aio.models.generate_content(
                        model=model_name, contents=prompt, config=config
                    )
                    return schema.model_validate_json(response.text or "")
                except errors.APIError as exc:
                    if exc.code not in RETRYABLE_STATUS or attempt == self._max_attempts:
                        raise
                    log.info("Gemini %s, retrying (attempt %d)", exc.code, attempt)
                except ValidationError:
                    if attempt == self._max_attempts:
                        raise
                    log.info("Gemini returned off-schema JSON, retrying (attempt %d)", attempt)
                await asyncio.sleep(2**attempt)
        raise AssertionError("unreachable")


def alt_configured() -> bool:
    return bool(os.getenv("ALT_LLM_BASE_URL") and os.getenv("ALT_LLM_MODEL"))


class OpenAICompatibleLLM:
    """Structured output over the OpenAI chat-completions API (`response_format`
    with a JSON schema), which OpenAI, Groq, OpenRouter and Ollama all serve.
    Same retries and concurrency cap as `GeminiLLM`. The API key is sent only
    in the Authorization header and never logged."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        max_concurrency: int = 4,
        max_attempts: int = 4,
        transport: httpx.AsyncBaseTransport | None = None,  # tests pass a MockTransport
    ) -> None:
        base_url = base_url or os.getenv("ALT_LLM_BASE_URL")
        model = model or os.getenv("ALT_LLM_MODEL")
        if not (base_url and model):
            raise RuntimeError("ALT_LLM_BASE_URL and ALT_LLM_MODEL are not set; add them to backend/.env")
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key if api_key is not None else os.getenv("ALT_LLM_API_KEY")
        self.model = model
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_attempts = max_attempts
        self._transport = transport

    async def aclose(self) -> None:
        pass  # one client per call: nothing held open between calls

    async def generate_json(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        *,
        temperature: float | None = None,
        model: str | None = None,
    ) -> T:
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
            },
        }
        if temperature is not None:
            body["temperature"] = temperature
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        async with self._semaphore:
            for attempt in range(1, self._max_attempts + 1):
                try:
                    async with httpx.AsyncClient(timeout=ALT_TIMEOUT_SECONDS, transport=self._transport) as client:
                        response = await client.post(self._url, json=body, headers=headers)
                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"]
                    return schema.model_validate_json(content or "")
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in RETRYABLE_STATUS or attempt == self._max_attempts:
                        raise
                    log.info("alt LLM %s, retrying (attempt %d)", exc.response.status_code, attempt)
                except (httpx.TransportError, ValidationError, KeyError, IndexError, TypeError) as exc:
                    if attempt == self._max_attempts:
                        raise
                    log.info("alt LLM %s, retrying (attempt %d)", type(exc).__name__, attempt)
                await asyncio.sleep(2**attempt)
        raise AssertionError("unreachable")


class RoutingLLM:
    """The primary client, plus a second provider for models named `alt:<model>`."""

    def __init__(self, primary: JsonLLM, alt: JsonLLM) -> None:
        self._primary, self._alt = primary, alt
        self.model = primary.model

    async def aclose(self) -> None:
        for client in (self._primary, self._alt):
            if hasattr(client, "aclose"):
                await client.aclose()

    async def generate_json(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        *,
        temperature: float | None = None,
        model: str | None = None,
    ) -> T:
        if model and model.startswith(ALT_PREFIX):
            return await self._alt.generate_json(
                system, prompt, schema, temperature=temperature, model=model.removeprefix(ALT_PREFIX) or None
            )
        return await self._primary.generate_json(system, prompt, schema, temperature=temperature, model=model)


def build_llm() -> JsonLLM:
    """Gemini, routed together with the OpenAI-compatible provider when that is configured.
    Raises RuntimeError when GEMINI_API_KEY is missing."""
    gemini = GeminiLLM()
    return RoutingLLM(gemini, OpenAICompatibleLLM()) if alt_configured() else gemini
