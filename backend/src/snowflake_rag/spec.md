# spec: backend/src/snowflake_rag/

## TODOS

- [x] Run `python -m snowflake_rag setup` and `sync` against the team's Snowflake account (HACK_KNIGHT.RAG, Oct 2026).
- [x] Keep the index current: every forecast syncs pending chunks (up to `SYNC_BATCHES_PER_FORECAST` batches) before it searches, so it sees the documents its own refresh just stored. Run `sync` by hand after bulk imports.
- [x] Move from the deprecated `EMBED_TEXT_1024` to `AI_EMBED` (same vectors; no re-embed needed).
- [ ] Compare retrieval quality with and without `RAG_BACKEND=snowflake` using `prediction_evidence.metadata->>'retrieval'` and `cited_by`, before treating vector search as an improvement.
- [ ] If `RAG_CHUNKS` grows past a few million rows, cluster it by `TICKER` or move to a Cortex Search Service.

## Purpose

Optional semantic retrieval for persona evidence. Tiger Data / PostgreSQL
stays the system of record: documents, chunks, forecasts and evidence live
there, and its triggers enforce point-in-time availability. Snowflake holds a
ranked copy of the chunks with Cortex embeddings and returns chunk IDs only.

## Files

| File | Role |
|---|---|
| `connection.py` | `enabled()` (`RAG_BACKEND=snowflake`), `SnowflakeSettings.from_env()`, key-pair `connect()`, user-safe `SnowflakeError` |
| `index.py` | `VectorIndex`: `setup()` creates `RAG_CHUNKS`, `upsert()` stages rows and MERGEs them with `AI_EMBED`, `search()` ranks by `VECTOR_COSINE_SIMILARITY` with ticker/cutoff/window/role filters |
| `retrieval.py` | `hybrid_passages()`: Snowflake hits reloaded from PostgreSQL, fused with keyword matches by reciprocal rank fusion (`fuse()`) |
| `sync.py` | `sync()`: batch copy of chunk/ticker pairs not yet in `snowflake_synced_chunks` |
| `__main__.py` | `python -m snowflake_rag setup | sync | search TICKER "query"` |

## Data flow

```
sources -> database.service -> PostgreSQL documents + document_chunks
python -m snowflake_rag sync:  chunks_to_sync -> RAG_CHUNKS_STAGE -> MERGE + AI_EMBED -> RAG_CHUNKS
                               -> mark_chunks_synced (PostgreSQL)
database.service._retrieve (RAG_BACKEND=snowflake):
  sync (up to 5 batches)      index the chunks this forecast's refresh just stored
per strategy and evidence role:
  VectorIndex.search          top 4 x limit chunk IDs, pre-filtered by ticker, cutoff, window, role
  passages_by_chunk_ids       reload from PostgreSQL; superseded/late/other-role chunks dropped
  retrieve_passages(fill)     keyword matches, including chunks not synced yet
  fuse                        reciprocal rank fusion, 2 passages per document, recency fill last
```

## Design rules

- Snowflake never decides what a persona may see. Every hit is reloaded through
  `DatabaseRepository.passages_by_chunk_ids`, which applies the same
  availability CTE as keyword retrieval, and `prediction_evidence` triggers
  reject anything published or first seen after the cutoff.
- Any Snowflake failure (configuration, connection, query) falls back to
  PostgreSQL keyword retrieval for the rest of that forecast and adds one
  `data_warnings` entry. A forecast never fails because Snowflake is down.
- Sync is batch only, so keyword matches always take part in fusion: fresh
  news must not lose its slots to older, already-indexed passages.
- Upsert before marking: a crash re-sends the batch and MERGE skips rows that
  are already indexed. The PostgreSQL tracking key includes the embedding
  model, so changing `SNOWFLAKE_EMBED_MODEL` re-embeds everything.
- Embeddings are computed inside Snowflake; no vectors or extra API keys leave it.
- Key-pair auth only. The `.p8` key lives outside the repo (`*.p8` is
  gitignored); errors never echo account, user, key path or driver messages.
- Tests use fake connections (`tests/test_snowflake_rag.py`) and never reach Snowflake.
- Each persona's evidence records which retriever chose it in
  `prediction_evidence.metadata.retrieval`: `snowflake_vector`,
  `postgres_fulltext`, `hybrid` or `recency_fill`.

## Setup

1. In Snowflake, create a warehouse (X-Small, `AUTO_SUSPEND = 60`), a database
   and schema, and a service user with an RSA public key
   (`ALTER USER ... SET RSA_PUBLIC_KEY = '...'`). Grant its role `USAGE` on the
   warehouse, database and schema, `CREATE TABLE` on the schema, and the
   `SNOWFLAKE.CORTEX_USER` database role.
2. Fill the `SNOWFLAKE_*` variables in `backend/.env` (names in `.env.example`).
3. From `backend/src/`: `python -m database.migrate` (adds
   `snowflake_synced_chunks`), `python -m snowflake_rag setup`, then
   `python -m snowflake_rag sync`.
4. Set `RAG_BACKEND=snowflake` and restart the API.

Costs: warehouse credits while setup, sync and searches run (each forecast
makes one search per strategy and evidence role, up to nine), plus Cortex
embedding tokens for every synced chunk and every query.
