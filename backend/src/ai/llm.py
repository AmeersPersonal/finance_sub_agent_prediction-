"""Gemini access. The only module that talks to the LLM provider."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Protocol, TypeVar

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

DEFAULT_MODEL = "gemini-3.5-flash-lite"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

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
        self._client = genai.Client()
        self.model = model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_attempts = max_attempts

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
