"""Local demo API. Credentials and database queries remain on the backend."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from ai.personas import Strategy
from database.connection import DatabaseError, connect
from database.repository import DatabaseRepository

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

AgeBand = Literal["18-24", "25-39", "40-54", "55-65"]
PriceInterval = Literal["1d", "5m"]
ADULT_BANDS = ["18-24", "25-39", "40-54", "55-65"]


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
    except Exception:
        raise HTTPException(status_code=502, detail="Market or prediction service unavailable. Try again later.") from None


app = FastAPI(title="Finance learning dashboard", version="0.1.0")
origins = os.environ.get("API_CORS_ORIGINS") or "http://localhost:5173,http://localhost:3000"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in origins.split(",") if origin.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


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
async def predict(body: PredictionRequest):
    return await _service("predict_and_store", body.ticker, horizon_days=body.horizon_days,
                          strategies=body.strategies, age_bands=body.age_bands)


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


@app.get("/predictions/{prediction_id}/evaluation")
async def evaluation(prediction_id: str):
    await _get_prediction(prediction_id)
    rows = await asyncio.to_thread(_read, "get_evaluations", prediction_id)
    return {"prediction_id": prediction_id, "status": "evaluated" if rows else "pending", "evaluations": rows}


@app.post("/predictions/{prediction_id}/evaluate")
async def evaluate(prediction_id: str):
    await _get_prediction(prediction_id)
    return await _service("evaluate_prediction", prediction_id)
