"""The Snowflake vector index: a ranked copy of PostgreSQL document chunks.

Tiger Data / PostgreSQL stays the system of record. Snowflake stores each
chunk once per ticker with a Cortex embedding of its title and text, and
answers one question: which chunk IDs are most similar to a query, among
chunks that were available at the forecast cutoff. Callers reload the winning
chunks from PostgreSQL, which re-applies every point-in-time rule.

Embeddings are computed inside Snowflake (AI_EMBED, which replaced the
deprecated EMBED_TEXT_1024 and returns the same vectors), so no vectors cross
the network and no separate embedding key is needed. The model must produce
1024-dimension vectors to fit the table. Search is
exact cosine similarity over the filtered rows, which is fast at this scale.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from snowflake_rag.connection import SnowflakeError, driver_errors

TABLE = "RAG_CHUNKS"
STAGE = "RAG_CHUNKS_STAGE"
DIMENSIONS = 1024

CREATE_TABLE = f"""CREATE TABLE IF NOT EXISTS {TABLE} (
    CHUNK_ID NUMBER(38, 0) NOT NULL,
    DOCUMENT_ID NUMBER(38, 0) NOT NULL,
    TICKER VARCHAR NOT NULL,
    EVIDENCE_ROLE VARCHAR NOT NULL,
    PUBLISHED_AT TIMESTAMP_TZ,
    FIRST_SEEN_AT TIMESTAMP_TZ NOT NULL,
    TITLE VARCHAR,
    CONTENT_TEXT VARCHAR NOT NULL,
    EMBEDDING_MODEL VARCHAR NOT NULL,
    EMBEDDING VECTOR(FLOAT, {DIMENSIONS}) NOT NULL,
    SYNCED_AT TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (CHUNK_ID, TICKER, EMBEDDING_MODEL)
)"""

CREATE_STAGE = f"""CREATE TEMPORARY TABLE IF NOT EXISTS {STAGE} (
    CHUNK_ID NUMBER(38, 0), DOCUMENT_ID NUMBER(38, 0), TICKER VARCHAR, EVIDENCE_ROLE VARCHAR,
    PUBLISHED_AT VARCHAR, FIRST_SEEN_AT VARCHAR, TITLE VARCHAR, CONTENT_TEXT VARCHAR
)"""

# Snowflake primary keys are informational, so MERGE is what keeps re-runs idempotent.
MERGE = f"""MERGE INTO {TABLE} t USING (
    SELECT CHUNK_ID, DOCUMENT_ID, TICKER, EVIDENCE_ROLE,
           TO_TIMESTAMP_TZ(PUBLISHED_AT) AS PUBLISHED_AT,
           TO_TIMESTAMP_TZ(FIRST_SEEN_AT) AS FIRST_SEEN_AT, TITLE, CONTENT_TEXT,
           AI_EMBED(%(model)s, COALESCE(TITLE || CHR(10), '') || CONTENT_TEXT) AS EMBEDDING
    FROM {STAGE}
) s ON t.CHUNK_ID = s.CHUNK_ID AND t.TICKER = s.TICKER AND t.EMBEDDING_MODEL = %(model)s
WHEN NOT MATCHED THEN INSERT
    (CHUNK_ID, DOCUMENT_ID, TICKER, EVIDENCE_ROLE, PUBLISHED_AT, FIRST_SEEN_AT,
     TITLE, CONTENT_TEXT, EMBEDDING_MODEL, EMBEDDING)
VALUES (s.CHUNK_ID, s.DOCUMENT_ID, s.TICKER, s.EVIDENCE_ROLE, s.PUBLISHED_AT, s.FIRST_SEEN_AT,
        s.TITLE, s.CONTENT_TEXT, %(model)s, s.EMBEDDING)"""


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("Chunk timestamps must be timezone-aware")
    return value.isoformat()


class VectorIndex:
    """Search and load the index through an open Snowflake connection."""

    def __init__(self, connection: Any, embed_model: str):
        self.connection = connection
        self.embed_model = embed_model

    def _run(self, statement: str, params: Mapping[str, Any] | None = None,
             many: Sequence[Sequence[Any]] | None = None) -> list[tuple]:
        try:
            cursor = self.connection.cursor()
            try:
                if many is not None:
                    cursor.executemany(statement, many)
                    return []
                cursor.execute(statement, params)
                return list(cursor.fetchall() or []) if cursor.description else []
            finally:
                cursor.close()
        except driver_errors():
            raise SnowflakeError(
                "Snowflake query failed. Check the warehouse, role grants, and Cortex availability."
            ) from None

    def setup(self) -> None:
        self._run(CREATE_TABLE)

    def search(self, ticker: str, query: str, *, cutoff: datetime, since: datetime | None = None,
               role: str | None = None, k: int = 24) -> list[tuple[int, float]]:
        """Chunk IDs most similar to `query`, best first, with cosine similarity.

        Pre-filters by ticker, embedding model, availability at `cutoff` and the
        lookback window, mirroring `DatabaseRepository.retrieve_passages`.
        """
        if k <= 0 or not query.strip():
            return []
        where = ["c.TICKER = %(ticker)s", "c.EMBEDDING_MODEL = %(model)s",
                 "c.FIRST_SEEN_AT <= TO_TIMESTAMP_TZ(%(cutoff)s)",
                 "(c.PUBLISHED_AT IS NULL OR c.PUBLISHED_AT <= TO_TIMESTAMP_TZ(%(cutoff)s))"]
        params: dict[str, Any] = {"ticker": ticker.strip().upper(), "model": self.embed_model,
                                  "cutoff": _timestamp(cutoff), "query": query, "k": int(k)}
        if since is not None:
            where.append("COALESCE(c.PUBLISHED_AT, c.FIRST_SEEN_AT) >= TO_TIMESTAMP_TZ(%(since)s)")
            params["since"] = _timestamp(since)
        if role is not None:
            where.append("c.EVIDENCE_ROLE = %(role)s")
            params["role"] = role
        rows = self._run(
            f"""WITH q AS (SELECT AI_EMBED(%(model)s, %(query)s) AS V)
            SELECT c.CHUNK_ID, VECTOR_COSINE_SIMILARITY(c.EMBEDDING, q.V) AS SCORE
            FROM {TABLE} c CROSS JOIN q
            WHERE {' AND '.join(where)}
            ORDER BY SCORE DESC, c.CHUNK_ID
            LIMIT %(k)s""",
            params,
        )
        return [(int(chunk_id), float(score)) for chunk_id, score in rows]

    def upsert(self, rows: Iterable[Mapping[str, Any]]) -> int:
        """Embed and add chunks not already indexed for this model; returns rows staged."""
        staged = [
            (row["chunk_id"], row["document_id"], row["ticker"].strip().upper(),
             row.get("evidence_role") or "other", _timestamp(row.get("published_at")),
             _timestamp(row["first_seen_at"]), row.get("title"), row["content_text"])
            for row in rows
        ]
        if not staged:
            return 0
        self._run(CREATE_STAGE)
        self._run(f"TRUNCATE TABLE {STAGE}")
        self._run(f"INSERT INTO {STAGE} VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", many=staged)
        self._run(MERGE, {"model": self.embed_model})
        return len(staged)
