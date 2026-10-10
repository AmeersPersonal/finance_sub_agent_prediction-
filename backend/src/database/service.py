"""Fetch, persist, retrieve evidence, forecast, and save dashboard results."""

from __future__ import annotations

import asyncio
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

from ai.agents import DOC_QUERIES
from ai.evaluation import MARKET_TZ, fetch_closes, score
from ai.main import predict
from ai.llm import GeminiLLM
from ai.personas import Strategy, build_personas
from ai.rag_retrieval import Snippet
from ai.tool import MarketSnapshot, fetch_snapshot
from audit.media import source_digest
from audit.risk import learning_context
from database.connection import connect
from database.repository import DatabaseRepository
from database.datasets import DatasetStore
from sources import fetch_documents


def normalize_ticker(ticker: str) -> str:
    ticker = ticker.strip().upper()
    if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=\-]{0,14}", ticker):
        raise ValueError("Invalid ticker symbol.")
    return ticker


def _clean(value: Any) -> Any:
    """Provider numeric missing values become JSON null, not NaN/Infinity."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None:
        return None
    if hasattr(value, "item"):
        return _clean(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (str, int, bool)):
        return value
    return str(value)


def _statements(frame: pd.DataFrame | None) -> dict:
    return {} if frame is None else _clean(frame.to_dict())


def _bars(frame: pd.DataFrame, fetched_at: datetime):
    for timestamp, row in frame.iterrows():
        timestamp = pd.Timestamp(timestamp)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(MARKET_TZ)
        values = {name.lower(): _clean(row.get(name)) for name in ("Open", "High", "Low", "Close", "Volume")}
        if values["close"] is not None:
            yield {"bar_at": timestamp.to_pydatetime(), "fetched_at": fetched_at, **values}


def chunks(text: str, size: int = 1600, overlap: int = 200):
    """Bound index size while keeping full permitted text in the source record."""
    for start in range(0, min(len(text), 560_000), size - overlap):
        passage = text[start:start + size].strip()
        if passage:
            yield passage
        if start + size >= len(text):
            break


def _persist_snapshot(snapshot: MarketSnapshot, collection) -> dict:
    with connect() as connection:
        repo = DatabaseRepository(connection)
        daily = repo.save_price_bars(snapshot.ticker, _bars(snapshot.daily, snapshot.fetched_at),
                                    interval="1d", adjustment_basis="total_return")
        intraday = 0
        if snapshot.intraday is not None:
            intraday = repo.save_price_bars(snapshot.ticker, _bars(snapshot.intraday, snapshot.fetched_at),
                                           interval="5m", adjustment_basis="total_return")
        payload = {
            "company_info": _clean(snapshot.info),
            "income_statement": _statements(snapshot.income_stmt),
            "balance_sheet": _statements(snapshot.balance_sheet),
            "cashflow": _statements(snapshot.cashflow),
            "quarterly_income": _statements(snapshot.quarterly_income),
            "price_targets": _clean(snapshot.price_targets),
            "unavailable_sources": sorted(snapshot.errors),
        }
        repo.save_fundamental_snapshot(
            snapshot.ticker, payload, available_at=snapshot.fetched_at,
            fetched_at=snapshot.fetched_at,
            metadata={"availability_basis": "first_fetched; original publication dates unknown"},
        )
        saved_ids = []
        for document in collection.documents:
            document_id = repo.store_document(
                source_url=document.source_url, title=document.title,
                content_text=document.content_text, document_type=document.document_type,
                content_kind=document.content_kind, source_name=document.source_name,
                published_at=document.published_at, first_seen_at=document.first_seen_at,
                symbols=[snapshot.ticker], classification=document.classification,
                metadata=document.metadata,
            )
            repo.store_chunks(document_id, chunks(document.content_text))
            saved_ids.append(document_id)
    return {
        "ticker": snapshot.ticker, "new_daily_bars": daily,
        "new_intraday_bars": intraday, "document_ids": list(dict.fromkeys(saved_ids)),
        "documents_fetched": len(collection.documents),
        "warnings": [f"{source}: market source unavailable" for source in snapshot.errors] + collection.warnings,
    }


async def _prepare(ticker: str):
    snapshot = await asyncio.to_thread(fetch_snapshot, ticker)
    collection = await asyncio.to_thread(
        fetch_documents, ticker, company_name=snapshot.info.get("shortName", "")
    )
    if collection.documents:
        snapshot.headlines = [d.title for d in collection.documents if d.document_type == "news"][:10]
    result = await asyncio.to_thread(_persist_snapshot, snapshot, collection)
    return snapshot, result


async def refresh_market(ticker: str) -> dict:
    """Explicit on-demand refresh; no LLM call and no invented missing data."""
    _, result = await _prepare(normalize_ticker(ticker))
    return result


EVIDENCE_ROLES = ("company_info", "public_opinion", "product_event")
RECENCY_DAYS = {Strategy.DAY_TRADER: 7, Strategy.INDEX_OPTIONS: 90, Strategy.LONG_TERM: None}
# The latest 10-Q or press release stays the company's current word for a quarter or so.
COMPANY_INFO_DAYS = 140
PASSAGES_PER_STRATEGY = 6


def mix_roles(candidates: dict[str, list[dict]], limit: int) -> list[dict]:
    """Round-robin over roles so no single source type fills a strategy's packet.

    A role with too few passages leaves its slots to the others.
    """
    mixed, seen = [], set()
    for rank in range(max((len(v) for v in candidates.values()), default=0)):
        for role in EVIDENCE_ROLES:
            items = candidates.get(role, [])
            if rank < len(items) and items[rank]["chunk_id"] not in seen and len(mixed) < limit:
                seen.add(items[rank]["chunk_id"])
                mixed.append(items[rank])
    return mixed


def _retrieve(ticker: str, strategies: set[Strategy], cutoff: datetime):
    passages = {}
    with connect() as connection:
        repo = DatabaseRepository(connection)
        for strategy in strategies:
            candidates = {}
            for role in EVIDENCE_ROLES:
                days = RECENCY_DAYS[strategy]
                if role == "company_info" and days is not None:
                    days = max(days, COMPANY_INFO_DAYS)
                candidates[role] = repo.retrieve_passages(
                    ticker, DOC_QUERIES[strategy], cutoff=cutoff,
                    since=cutoff - timedelta(days=days) if days else None,
                    limit=PASSAGES_PER_STRATEGY, role=role, fill=True,
                )
            passages[strategy] = mix_roles(candidates, PASSAGES_PER_STRATEGY)
    return passages


async def predict_and_store(ticker: str, horizon_days: int = 5,
                            strategies: list[Strategy] | None = None,
                            age_bands: list[str] | None = None, *, llm=None):
    ticker = normalize_ticker(ticker)
    if not 1 <= horizon_days <= 252:
        raise ValueError("Horizon must be between 1 and 252 trading days.")
    personas = build_personas(strategies, age_bands)
    await asyncio.to_thread(_check_database)
    snapshot, ingest = await _prepare(ticker)
    cutoff = datetime.now(timezone.utc)
    regression_daily = await asyncio.to_thread(_model_prices, ticker, snapshot, cutoff)
    passages = await asyncio.to_thread(_retrieve, ticker, {p.strategy for p in personas}, cutoff)
    snippets = {
        strategy: [Snippet(
            source=p["source_url"], text=p["text"], document_id=p["document_id"],
            chunk_id=p["chunk_id"], url=p["source_url"], title=p["title"], content_kind=p["content_kind"],
            role=(p.get("classification") or {}).get("role"),
            unconfirmed=bool((p.get("classification") or {}).get("unconfirmed")),
        ) for p in items] for strategy, items in passages.items()
    }
    owns_llm = llm is None
    llm = llm or GeminiLLM()
    try:
        async with asyncio.timeout(150):
            prediction = await predict(ticker, horizon_days=horizon_days, strategies=strategies,
                                       age_bands=age_bands, snapshot=snapshot, llm=llm,
                                       documents_by_strategy=snippets, regression_daily=regression_daily)
    finally:
        if owns_llm:
            await llm.aclose()
    source_map = {}
    for strategy, items in passages.items():
        for passage in items:
            citation_id = f"doc-{passage['document_id']}-chunk-{passage['chunk_id']}"
            item = source_map.setdefault(citation_id, {
                "id": citation_id, "document_id": passage["document_id"],
                "url": passage["source_url"], "title": passage["title"],
                "content_kind": passage["content_kind"],
                "role": (passage.get("classification") or {}).get("role", "other"),
                "published_at": _clean(passage["published_at"]),
                "first_seen_at": _clean(passage["first_seen_at"]),
                "strategies": [], "cited_by": [],
            })
            item["strategies"].append(strategy.value)
    for persona in prediction.personas:
        if persona.view:
            for citation_id in persona.view.source_ids:
                if citation_id in source_map:
                    source_map[citation_id]["cited_by"].append(persona.persona_id)
    prediction.sources = list(source_map.values())
    prediction.learning = learning_context(prediction)
    prediction.learning["news"] = source_digest(prediction.sources)
    prediction.input_snapshot["evidence_cutoff_at"] = cutoff.isoformat()
    prediction.input_snapshot["regression_dataset"] = dict(regression_daily.attrs["regression_dataset"])
    prediction.data_warnings.extend(ingest["warnings"])
    if not prediction.sources:
        prediction.data_warnings.append("No online documents retrieved; forecast uses available numerical/headline data.")
    await asyncio.to_thread(_save_with_evidence, prediction, passages, cutoff)
    return prediction


def _model_prices(ticker: str, snapshot: MarketSnapshot, cutoff: datetime):
    with connect() as connection:
        store = DatasetStore(connection)
        dataset_id = store.capture(ticker, snapshot.daily, fetched_at=snapshot.fetched_at, cutoff=cutoff)
        frame = store.load(dataset_id)
    return frame


def _check_database():
    with connect() as connection:
        connection.execute("SELECT id FROM prediction_runs LIMIT 0")


def _save_with_evidence(prediction, passages, cutoff):
    with connect() as connection:
        repo = DatabaseRepository(connection)
        if repo.save_prediction(prediction):
            for strategy, items in passages.items():
                for passage in items:
                    citation_id = f"doc-{passage['document_id']}-chunk-{passage['chunk_id']}"
                    cited_by = [p.persona_id for p in prediction.personas
                                if p.strategy == strategy.value and p.view and citation_id in p.view.source_ids]
                    repo.save_evidence(prediction.id, passage, retrieved_at=cutoff,
                                       strategy=strategy.value, cited_by=cited_by)


async def evaluate_prediction(prediction_id: str) -> dict:
    def load():
        with connect() as connection:
            return DatabaseRepository(connection).get_prediction(prediction_id)
    prediction = await asyncio.to_thread(load)
    if prediction is None:
        raise LookupError("Prediction not found.")
    closes = await asyncio.to_thread(fetch_closes, [prediction.ticker], date.fromisoformat(prediction.data_as_of))
    report = score([prediction], closes, datetime.now(MARKET_TZ))
    def save():
        with connect() as connection:
            repo = DatabaseRepository(connection)
            repo.save_evaluations(report)
            return repo.get_evaluations(prediction_id)
    evaluations = await asyncio.to_thread(save)
    result = {"prediction_id": prediction_id, "pending": report.pending > 0,
              "scored": report.scored, "evaluations": evaluations}
    if report.pending_details:
        waiting = report.pending_details[0]
        result["pending_reason"] = waiting.reason
        result["pending_detail"] = waiting.detail
        result["retry_after"] = waiting.retry_after.isoformat() if waiting.retry_after else None
    return result
