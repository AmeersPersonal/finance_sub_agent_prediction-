"""The one HTTP API: database-backed forecasts and dashboard reads, plus OAuth sign-in.

    uvicorn api.main:app --reload       # from backend/src; docs at /docs

Credentials and database queries stay on the backend. Forecasts go through
`database.service.predict_and_store`, so every prediction is stored with its
evidence; there is no JSONL path here. The Gemini client is a dependency
(`get_llm`), so tests swap in a fake.

Creating a forecast spends model quota, so it needs a signed-in user
(`API_REQUIRE_SIGN_IN=false` turns that off for local development) and is
rate-limited per caller (`API_PREDICTIONS_PER_HOUR`). Rate limits, background
jobs and the score cache are in-process (`api/state.py`): run one worker. On AWS
Lambda, `JOBS_BACKEND=lambda` keeps jobs in PostgreSQL instead (`api/lambda_jobs.py`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from ai.live import live_feed_from_env
from ai.llm import JsonLLM, build_llm
from ai.modes import resolve_modes
from ai.personas import Strategy
from api import lambda_jobs
from api.state import JobStore, RateLimiter, ScoreCache
from charts import backtest_charts, prediction_charts, price_charts, score_charts
from database.connection import DatabaseError, connect
from database.repository import DatabaseRepository
from oauth.provider import OAuthSettings
from oauth.routes import current_user, get_settings, get_store
from oauth.routes import router as oauth_router
from api.accounts import router as accounts_router
from oauth.sessions import SessionStore

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
log = logging.getLogger(__name__)

AgeBand = Literal["18-24", "25-39", "40-54", "55-65"]
PriceInterval = Literal["1d", "5m"]
ADULT_BANDS = ["18-24", "25-39", "40-54", "55-65"]
MAX_PREFERENCES_BYTES = 4096


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name) or default))
    except ValueError:
        return default


prediction_limiter = RateLimiter(_int_env("API_PREDICTIONS_PER_HOUR", 10), window=3600)
jobs = JobStore()
score_cache = ScoreCache(_int_env("API_SCORE_CACHE_SECONDS", 300))


@lru_cache(maxsize=1)
def durable_jobs() -> lambda_jobs.DatabaseJobStore | None:
    """The PostgreSQL-backed job store when `JOBS_BACKEND=lambda`, else None (use `jobs`)."""
    return lambda_jobs.from_env()


def normalize_ticker(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=\-]{0,14}", value):
        raise ValueError("Use a valid ticker symbol, for example AAPL or BRK-B.")
    return value


class PredictionRequest(BaseModel):
    ticker: str
    horizon_days: int = Field(default=5, ge=1, le=252)
    strategies: list[Strategy] | None = Field(default=None, min_length=1, max_length=3)
    age_bands: list[AgeBand] = Field(default_factory=lambda: ADULT_BANDS.copy(), min_length=1, max_length=4)
    strategy_weights: dict[Strategy, float] | Literal["auto"] | None = Field(
        default=None,
        description="Per-strategy weights (missing ones weigh 1), or 'auto' from saved evaluations",
    )
    modes: str = Field(default="default", description="Preset (default, temps, models, full) or mode names")
    live: bool = Field(default=False, description="Take the last price from Yahoo's live websocket")
    audit: bool = Field(default=False, description="Add company overview, checks, risk flags and news digest")

    @field_validator("ticker")
    @classmethod
    def ticker_symbol(cls, value: str) -> str:
        return normalize_ticker(value)

    @field_validator("strategies", "age_bands")
    @classmethod
    def unique_choices(cls, value):
        if value is not None and len(value) != len(set(value)):
            raise ValueError("Choices must be unique.")
        return value

    @field_validator("strategy_weights")
    @classmethod
    def usable_weights(cls, value):
        if isinstance(value, dict) and (any(w < 0 for w in value.values()) or not any(value.values())):
            raise ValueError("Weights must be zero or more, with at least one above zero.")
        return value

    @field_validator("modes")
    @classmethod
    def known_modes(cls, value: str) -> str:
        resolve_modes(value)  # raises ValueError for an unknown preset or mode
        return value


def _ticker(value: str) -> str:
    try:
        return normalize_ticker(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid ticker symbol.") from None


def _prediction_id(value: str) -> str:
    try:
        UUID(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid prediction identifier.") from None
    return value


def _read(method: str, *args, **kwargs):
    with connect() as connection:
        return getattr(DatabaseRepository(connection), method)(*args, **kwargs)


async def _service(method: str, *args, **kwargs):
    # Import late so importing this module never makes a network request.
    try:
        from database import service
        return await getattr(service, method)(*args, **kwargs)
    except (DatabaseError, HTTPException):
        raise
    except ValueError as exc:  # our own messages: unknown ticker, no eligible personas, bad mode
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception:
        raise HTTPException(status_code=502, detail="Market or prediction service unavailable. Try again later.") from None


@lru_cache(maxsize=1)
def _gemini() -> JsonLLM:
    return build_llm()  # one client, so its concurrency cap and backoff cover every request


def get_llm() -> JsonLLM:
    try:
        return _gemini()
    except RuntimeError:  # missing API key
        raise HTTPException(status_code=503, detail="Prediction model is not configured (GEMINI_API_KEY).") from None


def sign_in_required() -> bool:
    """Read on every request, so the setting can change without a code change."""
    return (os.environ.get("API_REQUIRE_SIGN_IN") or "true").strip().lower() not in {"false", "0", "no"}


def prediction_caller(request: Request, store: SessionStore = Depends(get_store)) -> str:
    """Who is spending model quota: the signed-in user, or with sign-in turned off,
    the client address. Raises 401 when sign-in is required and missing."""
    if sign_in_required():
        return "user:" + current_user(request, store)["sub"]
    return "client:" + (request.client.host if request.client else "unknown")


def _spend_quota(caller: str) -> None:
    wait = prediction_limiter.acquire(caller)
    if wait is not None:
        raise HTTPException(
            status_code=429, headers={"Retry-After": str(math.ceil(wait))},
            detail=f"Forecast limit reached ({prediction_limiter.limit} an hour). "
                   f"Try again in {math.ceil(wait / 60)} min.",
        )


def _prediction_kwargs(body: PredictionRequest, llm: JsonLLM) -> dict[str, Any]:
    if body.live:
        try:
            live_feed_from_env()  # fail now, not after spending quota, if the feed isn't configured
        except (RuntimeError, ValueError):
            raise HTTPException(status_code=503, detail="The live price feed is not configured (LIVE_FEED).") from None
    weights = body.strategy_weights
    if isinstance(weights, dict):
        weights = {s.value: w for s, w in weights.items()}
    return dict(horizon_days=body.horizon_days, strategies=body.strategies, age_bands=body.age_bands,
                llm=llm, strategy_weights=weights, modes=resolve_modes(body.modes),
                live=body.live, audit=body.audit)


app = FastAPI(title="Finance learning dashboard", version="0.2.0")
origins = os.environ.get("API_CORS_ORIGINS") or "http://localhost:5173,http://localhost:3000"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in origins.split(",") if origin.strip()],
    allow_credentials=True,  # the OAuth session cookie; origins are an explicit list, never "*"
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)
app.include_router(oauth_router)
app.include_router(accounts_router)


@app.exception_handler(DatabaseError)
async def database_failure(request, error):
    return JSONResponse(status_code=503, content={"detail": "Database unavailable. Check its connection and migrations."})


@app.get("/health")
async def health():
    def check():
        with connect() as connection:
            connection.execute("SELECT 1")
    await asyncio.to_thread(check)
    return {"status": "ok", "database": "connected"}


@app.get("/stocks/{ticker}/history")
async def history(ticker: str, interval: PriceInterval = "1d", limit: Annotated[int, Query(ge=1, le=2000)] = 500):
    ticker = _ticker(ticker)
    bars = await asyncio.to_thread(_read, "get_price_history", ticker, interval=interval, limit=limit)
    return {"ticker": ticker, "interval": interval, "bars": bars}


@app.get("/stocks/{ticker}/news")
async def news(ticker: str, limit: Annotated[int, Query(ge=1, le=100)] = 20):
    ticker = _ticker(ticker)
    documents = await asyncio.to_thread(_read, "list_documents", ticker, limit=limit)
    return {"ticker": ticker, "documents": documents}


@app.post("/stocks/{ticker}/refresh")
async def refresh(ticker: str):
    return await _service("refresh_market", _ticker(ticker))


@app.post("/predictions", status_code=201)
async def predict(body: PredictionRequest, llm: JsonLLM = Depends(get_llm),
                  caller: str = Depends(prediction_caller)):
    """Generate and store a forecast, holding the request open for the whole run
    (10-60 s). `POST /prediction-jobs` returns at once instead."""
    kwargs = _prediction_kwargs(body, llm)
    _spend_quota(caller)
    return await _service("predict_and_store", body.ticker, **kwargs)


@app.post("/prediction-jobs", status_code=202)
async def create_prediction_job(body: PredictionRequest, llm: JsonLLM = Depends(get_llm),
                                caller: str = Depends(prediction_caller)):
    """Start a forecast in the background; poll `GET /prediction-jobs/{job_id}`."""
    kwargs = _prediction_kwargs(body, llm)
    _spend_quota(caller)
    durable = durable_jobs()
    if durable is not None:  # Lambda: the job lives in PostgreSQL and runs in a second invocation
        view = await asyncio.to_thread(durable.submit, caller, body.model_dump(mode="json"))
        return {**view, "poll": f"/prediction-jobs/{view['job_id']}"}
    job = jobs.submit(caller, lambda: _service("predict_and_store", body.ticker, **kwargs))
    return {**job.view(), "poll": f"/prediction-jobs/{job.id}"}


@app.get("/prediction-jobs/{job_id}")
async def prediction_job(job_id: str, caller: str = Depends(prediction_caller)):
    """`status`: queued, running, succeeded (with `prediction`) or failed (with `error`).
    Only the caller who started a job can see it; finished jobs are kept for an hour."""
    durable = durable_jobs()
    if durable is not None:
        view = await asyncio.to_thread(durable.get, job_id, caller)
    else:
        job = jobs.get(job_id, caller)
        view = job.view() if job is not None else None
    if view is None:
        raise HTTPException(status_code=404, detail="Job not found (or it finished over an hour ago).")
    return view


@app.post("/internal/lambda-events", include_in_schema=False)
async def run_lambda_job(request: Request):
    """The worker half of a durable job: the Lambda Web Adapter posts the signed
    event here (`AWS_LWA_PASS_THROUGH_PATH`). Anything unsigned is refused."""
    durable = durable_jobs()
    try:
        event = await request.json()
    except ValueError:
        event = None
    if durable is None or not durable.verify(event):
        raise HTTPException(status_code=403, detail="Forbidden.")
    job_id = str(event.get("job_id", ""))
    if not await asyncio.to_thread(durable.claim, job_id):
        return {"status": "ignored"}  # a retry or replay: the job isn't queued
    try:
        body = PredictionRequest(**event["request"])
        kwargs = _prediction_kwargs(body, get_llm())
        result = await _service("predict_and_store", body.ticker, **kwargs)
        await asyncio.to_thread(durable.finish, job_id, result=result)
    except HTTPException as exc:  # already a sanitized, user-facing error
        await asyncio.to_thread(durable.finish, job_id, error={"status_code": exc.status_code, "detail": exc.detail})
    except Exception as exc:  # never leak provider or database details
        log.warning("prediction job %s failed: %s", job_id, type(exc).__name__)
        await asyncio.to_thread(durable.finish, job_id, error={
            "status_code": 500, "detail": "The forecast failed. Try again later."})
    return {"status": "done"}


def _report_json(report) -> dict[str, Any]:
    return {
        "scored": report.scored, "pending": report.pending, "accuracy": report.accuracy,
        "coverage": report.coverage, "accuracy_when_called": report.accuracy_when_called,
        "by_confidence": {k: {"n": n, "accuracy": a} for k, (n, a) in report.by_confidence.items()},
        "by_stability": {k: {"n": n, "accuracy": a} for k, (n, a) in report.by_stability.items()},
        "relative": report.relative,
        "by_strategy": report.by_strategy, "by_age_band": report.by_age_band,
        "by_mode": report.by_mode, "by_model": report.by_model,
        "strategy_weights": report.strategy_weights,
        "pending_details": [{
            "prediction_id": p.prediction.id, "ticker": p.prediction.ticker,
            "data_as_of": p.prediction.data_as_of, "horizon_days": p.prediction.horizon_days,
            "reason": p.reason, "detail": p.detail,
            "retry_after": p.retry_after.isoformat() if p.retry_after else None,
        } for p in report.pending_details],
    }


async def _score_report(fresh: bool = False):
    """The score report and when it was computed, from `score_cache` unless `fresh`."""
    from database import service
    try:
        return await asyncio.to_thread(score_cache.get, lambda: service.score_database(), fresh)
    except DatabaseError:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="Price provider unavailable. Try again later.") from None


@app.get("/score")
async def score(refresh: bool = False):
    """Accuracy of saved forecasts vs the baselines (`python main.py --score --database`).

    Fetches closes and appends any newly available outcomes (idempotent), then
    reports why each remaining forecast is still pending. The report is cached
    for `API_SCORE_CACHE_SECONDS` (default 5 min); `?refresh=true` recomputes it.
    """
    report, computed_at = await _score_report(refresh)
    return {**_report_json(report), "computed_at": computed_at.isoformat()}


@app.get("/score/charts")
async def score_chart_data(refresh: bool = False):
    """The `/score` report as chart-ready series (`charts/base.py` for the shape)."""
    report, computed_at = await _score_report(refresh)
    return {"charts": score_charts(_report_json(report), report.outcomes),
            "computed_at": computed_at.isoformat()}


@app.get("/stocks/{ticker}/charts")
async def price_chart_data(ticker: str, interval: PriceInterval = "1d",
                           limit: Annotated[int, Query(ge=2, le=2000)] = 250):
    """Candles, moving averages, volume, RSI, MACD and drawdown from saved bars; `5m`
    bars add the session VWAP and a volume profile."""
    ticker = _ticker(ticker)
    bars = await asyncio.to_thread(_read, "get_price_history", ticker, interval=interval, limit=limit)
    return {"ticker": ticker, "interval": interval, "charts": price_charts(bars, ticker, interval)}


@app.get("/stocks/{ticker}/charts/backtest")
async def backtest_chart_data(ticker: str, horizon_days: Annotated[int, Query(ge=1, le=252)] = 5):
    """Walk-forward regression vs buy and hold from the saved daily bars. Empty
    `charts` when fewer than about 1.5 years of bars are saved (refresh the ticker)."""
    ticker = _ticker(ticker)
    bars = await asyncio.to_thread(_read, "get_price_history", ticker, interval="1d", limit=2000)
    charts = await asyncio.to_thread(backtest_charts, bars, ticker, horizon_days)
    return {"ticker": ticker, "horizon_days": horizon_days, "charts": charts}


@app.get("/predictions")
async def predictions(ticker: str | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 20):
    rows = await asyncio.to_thread(_read, "load_predictions", ticker=_ticker(ticker) if ticker else None, limit=limit)
    return {"predictions": rows}


async def _get_prediction(prediction_id: str):
    prediction_id = _prediction_id(prediction_id)
    prediction = await asyncio.to_thread(_read, "get_prediction", prediction_id)
    if prediction is None:
        raise HTTPException(status_code=404, detail="Prediction not found.")
    return prediction


@app.get("/predictions/{prediction_id}")
async def prediction(prediction_id: str):
    return await _get_prediction(prediction_id)


@app.get("/predictions/{prediction_id}/charts")
async def prediction_chart_data(prediction_id: str):
    """Votes, conviction, strategy scores, flat band and baselines for one forecast."""
    found = await _get_prediction(prediction_id)
    return {"prediction_id": prediction_id, "charts": prediction_charts(found)}


@app.get("/predictions/{prediction_id}/evaluation")
async def evaluation(prediction_id: str):
    await _get_prediction(prediction_id)
    rows = await asyncio.to_thread(_read, "get_evaluations", prediction_id)
    return {"prediction_id": prediction_id, "status": "evaluated" if rows else "pending", "evaluations": rows}


@app.post("/predictions/{prediction_id}/evaluate")
async def evaluate(prediction_id: str):
    await _get_prediction(prediction_id)
    result = await _service("evaluate_prediction", prediction_id)
    score_cache.clear()  # a new outcome may have been saved
    return result


# --- Signed-in account preferences ------------------------------------------------


class PreferencesRequest(BaseModel):
    """What a signed-in user tells the dashboard about themselves. Adult bands only,
    as for forecasts; nothing here is a suitability assessment."""

    age_band: AgeBand | None = None
    strategy: Strategy | None = None
    experience_level: Literal["beginner", "intermediate", "advanced"] | None = None
    preferences: dict[str, Any] = Field(default_factory=dict, description="Free-form UI settings, up to 4 KB")

    @field_validator("preferences")
    @classmethod
    def small(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value)) > MAX_PREFERENCES_BYTES:
            raise ValueError(f"Preferences must be at most {MAX_PREFERENCES_BYTES} bytes of JSON.")
        return value


def account_reference(user: dict[str, Any], settings: OAuthSettings) -> str:
    """The provider's stable subject id, namespaced by provider host. Never the email,
    which can change hands. Email/password accounts are already namespaced (`password:<id>`)."""
    if user.get("provider") == "password":
        return user["sub"]
    return f"{urlsplit(settings.userinfo_url).hostname}:{user['sub']}"


def _account(user: dict[str, Any] = Depends(current_user),
             settings: OAuthSettings = Depends(get_settings)) -> str:
    return account_reference(user, settings)


@app.get("/me/preferences")
async def read_preferences(account: str = Depends(_account)):
    """The signed-in user's saved preferences, or `null` before they save any."""
    return {"preferences": await asyncio.to_thread(_read, "get_user_preferences", account)}


@app.put("/me/preferences")
async def save_preferences(body: PreferencesRequest, account: str = Depends(_account)):
    saved = await asyncio.to_thread(
        _read, "save_user_preferences", account, age_band=body.age_band,
        strategy=body.strategy.value if body.strategy else None,
        experience_level=body.experience_level, preferences=body.preferences,
    )
    return {"preferences": saved}


@app.delete("/me/preferences")
async def delete_preferences(account: str = Depends(_account)):
    """Forget the signed-in user's preferences."""
    return {"deleted": await asyncio.to_thread(_read, "delete_user_preferences", account)}
