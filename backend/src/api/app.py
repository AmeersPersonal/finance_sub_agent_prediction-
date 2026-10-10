"""HTTP API: the CLI's prediction pipeline over HTTP, plus the OAuth routes.

    uvicorn api.app:app --reload        # from backend/src; docs at /docs

POST /predict runs the same steps as `python main.py TICKER` (fetch, personas,
aggregate, optional live quote and audit) and appends to the same log. GET
/score reads that log. The LLM, the snapshot fetcher and the log path are
dependencies, so tests swap them for fakes.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from ai.evaluation import DEFAULT_LOG, log_prediction, score_log
from ai.live import YahooLiveFeed
from ai.llm import GeminiLLM, JsonLLM
from ai.main import predict
from ai.modes import resolve_modes
from ai.personas import AGE_BANDS, Strategy
from ai.schemas import Prediction
from ai.tool import MarketSnapshot, fetch_snapshot
from audit.analysis import audit_prediction
from oauth.routes import router as oauth_router

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
TICKER = re.compile(r"^[A-Za-z0-9.^=\-]{1,15}$")  # AAPL, BRK-B, ^GSPC, EURUSD=X


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    load_dotenv(ENV_FILE)
    yield


app = FastAPI(title="Finance persona predictions", lifespan=lifespan)
app.include_router(oauth_router)


class PredictRequest(BaseModel):
    ticker: str
    horizon_days: int = Field(5, ge=1, le=60)
    strategies: list[Strategy] | None = None
    age_bands: list[str] | None = None
    strategy_weights: dict[Strategy, float] | Literal["auto"] | None = Field(
        None, description="Per-strategy weights (missing ones weigh 1), or 'auto' from the scored log"
    )
    modes: str = Field("default", description="Preset (default, temps, models, full) or mode names")
    live: bool = Field(False, description="Take the last price from Yahoo's live websocket")
    audit: bool = Field(False, description="Add company overview, checks, risk and news digest")
    log: bool = Field(True, description="Append the prediction to the log that /score reads")

    @field_validator("ticker")
    @classmethod
    def _ticker(cls, value: str) -> str:
        if not TICKER.match(value):
            raise ValueError("ticker must be 1-15 letters, digits or . ^ = -")
        return value.upper()

    @field_validator("age_bands")
    @classmethod
    def _age_bands(cls, value: list[str] | None) -> list[str] | None:
        known = [b.label for b in AGE_BANDS]
        unknown = [v for v in value or [] if v not in known]
        if unknown:
            raise ValueError(f"unknown age bands {unknown}; choose from {known}")
        return value

    @field_validator("strategy_weights")
    @classmethod
    def _weights(cls, value: Any) -> Any:
        if isinstance(value, dict):
            if any(w < 0 for w in value.values()) or not any(value.values()):
                raise ValueError("weights must be zero or more, with at least one above zero")
        return value


@lru_cache(maxsize=1)
def _gemini() -> GeminiLLM:
    return GeminiLLM()  # one client, so its concurrency cap covers every request


def get_llm() -> JsonLLM:
    try:
        return _gemini()
    except RuntimeError as exc:  # missing API key
        raise HTTPException(503, str(exc)) from None


def get_fetcher() -> Callable[[str], MarketSnapshot]:
    return fetch_snapshot


def get_log_path() -> Path:
    return DEFAULT_LOG


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/predict", response_model=Prediction)
async def predict_endpoint(
    request: PredictRequest,
    llm: JsonLLM = Depends(get_llm),
    fetch: Callable[[str], MarketSnapshot] = Depends(get_fetcher),
    log_path: Path = Depends(get_log_path),
) -> Prediction:
    weights = request.strategy_weights
    if weights == "auto":
        weights = (await asyncio.to_thread(score_log, log_path)).strategy_weights or None
    elif weights is not None:
        weights = {s.value: w for s, w in weights.items()}
    try:
        modes = resolve_modes(request.modes)
        snapshot = await asyncio.to_thread(fetch, request.ticker)
        prediction = await predict(
            request.ticker,
            horizon_days=request.horizon_days,
            strategies=request.strategies,
            age_bands=request.age_bands,
            strategy_weights=weights,
            modes=modes,
            llm=llm,
            snapshot=snapshot,
            live_feed=YahooLiveFeed() if request.live else None,
        )
        if request.audit:
            prediction.audit = await audit_prediction(prediction, snapshot, llm)
    except ValueError as exc:  # unknown ticker or mode, no eligible personas
        raise HTTPException(422, str(exc)) from None
    except RuntimeError as exc:  # every persona failed (quota, outage)
        raise HTTPException(502, str(exc)) from None
    if request.log:
        await asyncio.to_thread(log_prediction, prediction, log_path)
    return prediction


@app.get("/score")
def score_endpoint(log_path: Path = Depends(get_log_path)) -> dict[str, Any]:
    """Accuracy of logged predictions vs the baselines (what `python main.py --score` prints).
    Sync, so FastAPI runs it in a worker thread while it fetches closes."""
    report = score_log(log_path)
    return {k: v for k, v in vars(report).items() if k != "outcomes"}
