"""Hybrid retrieval: Snowflake vector ranking fused with PostgreSQL keyword search.

The batch sync means chunks ingested during this request aren't in Snowflake
yet, so keyword matches from PostgreSQL always take part. The two rankings are
combined with reciprocal rank fusion (each list contributes 1 / (RRF_K + rank)),
so a chunk both retrievers like rises, and fresh news can still win slots.
Recency-fill rows (relevance 0, no keyword match) only fill what's left.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

RRF_K = 60  # the standard constant; larger flattens the difference between ranks
CANDIDATES_PER_SLOT = 4  # Snowflake candidates per passage slot, before PostgreSQL drops any
PER_DOCUMENT = 2  # matches DatabaseRepository.retrieve_passages


def fuse(semantic: list[dict], keyword: list[dict], limit: int,
         per_document: int = PER_DOCUMENT) -> list[dict]:
    """Reciprocal rank fusion of two passage lists, deduplicated by chunk, at most
    `per_document` passages per document. Each passage gets a `retrieval` label."""
    matches = [p for p in keyword if p.get("relevance")]
    fill = [p for p in keyword if not p.get("relevance")]
    scores: dict[int, float] = {}
    rows: dict[int, dict] = {}
    sources: dict[int, set[str]] = {}
    for name, ranking in (("snowflake_vector", semantic), ("postgres_fulltext", matches)):
        for rank, passage in enumerate(ranking, 1):
            chunk_id = passage["chunk_id"]
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (RRF_K + rank)
            rows.setdefault(chunk_id, passage)
            sources.setdefault(chunk_id, set()).add(name)
    ordered = sorted(scores, key=lambda chunk_id: -scores[chunk_id])
    labelled = [
        {**rows[c], "retrieval": "hybrid" if len(sources[c]) > 1 else next(iter(sources[c])),
         "fused_score": round(scores[c], 6)}
        for c in ordered
    ] + [{**p, "retrieval": "recency_fill"} for p in fill if p["chunk_id"] not in scores]

    kept: list[dict] = []
    per_doc: dict[Any, int] = {}
    for passage in labelled:
        if len(kept) >= limit:
            break
        count = per_doc.get(passage["document_id"], 0)
        if count >= per_document:
            continue
        per_doc[passage["document_id"]] = count + 1
        kept.append(passage)
    return kept


def hybrid_passages(repo: Any, index: Any, ticker: str, query: str, *, cutoff: datetime,
                    since: datetime | None, role: str | None, limit: int) -> list[dict]:
    """Up to `limit` passages for one strategy and evidence role.

    Raises `SnowflakeError` if the index can't be queried; the caller falls back
    to `repo.retrieve_passages` alone.
    """
    hits = index.search(ticker, query, cutoff=cutoff, since=since, role=role,
                        k=limit * CANDIDATES_PER_SLOT)
    similarity = dict(hits)
    semantic = [
        {**row, "relevance": similarity[row["chunk_id"]]}
        for row in repo.passages_by_chunk_ids(ticker, [chunk_id for chunk_id, _ in hits],
                                              cutoff=cutoff, since=since, role=role)
    ]
    keyword = repo.retrieve_passages(ticker, query, cutoff=cutoff, since=since,
                                     limit=limit, role=role, fill=True)
    return fuse(semantic, keyword, limit)
