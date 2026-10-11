# spec: backend/src/database/

## TODOS

- [ ] Connect to a private Tiger Cloud development service and run migrations;
  offline verification does not validate cloud credentials. Blocked: needs the
  team's Tiger account and credentials (`SETUP.md`, steps 1-3).
- [x] Collect linked RSS excerpts and optional SEC primary filing text through `sources/`.
- [x] Retrieve dated passages and save exactly what was provided, with cited-by metadata.
- [x] Add an embedding provider and vector index: optional Snowflake Cortex
  embeddings in `snowflake_rag/`, fused with this full-text index (`RAG_BACKEND=snowflake`).
- [ ] Measure retrieval quality with and without Snowflake before relying on it
  (see `snowflake_rag/spec.md`).
- [x] Add local dashboard HTTP routes in `api/`.
- [x] Authenticated account integration: `/me/preferences` (`api/`) reads and writes `user_preferences` for the signed-in user only, keyed by provider and subject id (`get_user_preferences`, `save_user_preferences`, `delete_user_preferences`).
- [x] Refresh corrected price bars from equally/newer fetches; skip unchanged or older data.
- [x] Archive price revisions: migration 008 copies every corrected or deleted bar to `price_bar_revisions` (append-only); `get_price_history_as_of` and `model_data.load_daily_prices_as_known` rebuild prices exactly as known at any moment.
- [x] Don't archive float noise: Yahoo's adjusted history jitters by up to ~5e-7 between fetches, so every refresh rewrote and archived ~780 old bars per ticker. `save_price_bars` now treats prices within `PRICE_TOLERANCE` (1e-5 relative) as unchanged. The ~3,800 noise revisions already in the team database stay (the table is append-only).
- [x] Retention, source usage permissions and access roles: `docs/retention-and-access.md`, `backup.py` (pg_dump with a 7/4/12 schedule) and `roles.sql` (least-privilege `finance_api` writer and `finance_analyst` reader logins).
- [x] Shared sign-in sessions for several API workers: migration 007 (`oauth_pending_logins`, `oauth_sessions`, hashes only), used with `OAUTH_SESSION_STORE=database`.

## Purpose

One PostgreSQL database stores market data, source documents, immutable forecast
inputs, persona and baseline outputs, and later outcomes. It works on ordinary
PostgreSQL; Tiger Data adds an optional TimescaleDB hypertable for price bars.
No separate NoSQL store or blockchain is required. Snowflake is optional: with
`RAG_BACKEND=snowflake` it ranks chunk IDs by vector similarity
(`snowflake_rag/`), but this database stays the system of record.

Database-backed forecasts persist market data, source documents, retrieved
evidence, predictions, and scores. The API exposes these records to a future
frontend. Account integration remains separate work.

## Files

| File | Role |
|---|---|
| `connection.py` | Connect using `DATABASE_URL`; provide a database-specific error boundary |
| `migrate.py` | Apply tracked SQL migrations; `--timescale` explicitly opts into the extension migration |
| `repository.py` | Save/read market records, documents, passages, forecasts, evidence, and evaluations |
| `service.py` | Coordinate ingestion, retrieval, database-loaded regression inputs, forecasting, and persistence |
| `model_data.py` | Read full stored daily Close/Volume history, validate it, and record dataset provenance |
| `datasets.py` | Freeze the exact daily rows a forecast's regression used into immutable `model_datasets` and replay them |
| `migrations/001_initial.sql` | Portable PostgreSQL tables, indexes, constraints, and immutable record triggers |
| `migrations/002_timescale.sql` | Optional TimescaleDB extension and time partitioning for `price_bars` |
| `migrations/003_dataset.sql` | Immutable per-forecast regression datasets (`model_datasets`) |
| `migrations/004_evaluations_immutable.sql` | Append-only trigger for `evaluations` |
| `migrations/005_document_title_search.sql` | English full-text GIN index on stored titles, covering existing and future documents without rewriting evidence |
| `migrations/006_snowflake_sync.sql` | `snowflake_synced_chunks`: which chunk/instrument pairs the Snowflake index holds, per embedding model |
| `migrations/007_oauth_sessions.sql` | Shared OAuth pending logins and sessions (hashed ids), for `OAUTH_SESSION_STORE=database` |
| `migrations/008_price_bar_revisions.sql` | Append-only archive of every price-bar version a refresh overwrote or a delete removed |
| `migrations/009_user_accounts.sql` | Email/password accounts (`user_accounts`): unique lower-cased email, names, scrypt hash only |
| `migrations/010_prediction_jobs.sql` | `prediction_jobs`: forecast job state for `JOBS_BACKEND=lambda` (status, owner, result JSON) |
| `migrations/011_paper_trading.sql` | Simulated trading: `paper_accounts`, `paper_positions`, `paper_orders` (per account; no real money) |
| `backup.py` | `python -m database.backup`: pg_dump to `backend/data/backups/`, prune by the retention schedule |
| `roles.sql` | Least-privilege group and login roles; an administrator runs it with psql after migrations |
| `SETUP.md` | Cloud connection, private environment configuration, and CLI commands |
| `local_postgres.sh` | Initialize and manage a separate persistent local PostgreSQL cluster in gitignored `backend/data/` |
| `docs/README.md` | Short beginner guides to the schema, data flow, and future Tiger Cloud migration |
| `docs/retention-and-access.md` | What is kept and for how long, backups, source-use rules, database roles |

## Tables

| Table | Stores |
|---|---|
| `instruments` | A stock/ETF/bond/index identifier and its metadata; types do not imply corresponding forecasting support |
| `price_bars` | Timestamped OHLCV records with interval, provider, adjustment basis, and fetch time |
| `documents` | Versioned source content: headline, excerpt, or full text, with URL, dates, content hash, and an English full-text title index |
| `document_instruments` | Which instruments a document mentions |
| `document_chunks` | Ordered text passages and an English full-text search index; no embeddings yet |
| `fundamental_snapshots` | Company metrics as JSONB, with their availability and fetch times |
| `prediction_runs` | Existing prediction ID, time cutoff, trading-day horizon, model/prompt version, frozen input packet, and complete prediction JSON |
| `prediction_outputs` | Individual persona answers, aggregate direction, regression, and other baselines |
| `prediction_evidence` | Exact supplied excerpts, source/chunk links, strategy, and cited-by metadata |
| `evaluations` | Later observed price/return/direction, data basis, and evaluation payload |
| `user_preferences` | External account reference, adult age band, strategy, experience, and optional preferences; no credentials. Written only through `/me/preferences` |
| `snowflake_synced_chunks` | Chunk, instrument and embedding model already copied to the optional Snowflake index |
| `price_bar_revisions` | Superseded price-bar versions with when they were fetched and superseded (append-only) |
| `paper_accounts`, `paper_positions`, `paper_orders` | Virtual cash, long-only holdings and the order log per account; orders may reference the forecast they came from. Mutable by design; written only through `/paper/*` |
| `oauth_pending_logins`, `oauth_sessions` | Shared sign-in state for several API workers; SHA-256 hashes of state values and session ids |
| `user_accounts` | Email/password accounts for `POST /signup` and `/login`: email, names, salted scrypt password hash (never the password) |
| `prediction_jobs` | Background forecast jobs when the API runs on Lambda (`JOBS_BACKEND=lambda`); owner, status and the stored forecast JSON, purged an hour after finishing |

The migration runner records names and checksums in `schema_migrations`, skips
applied files, and rejects changes to their contents. Run it explicitly for each
configured database; prediction startup does not apply migrations. Ordinary
PostgreSQL migrations include `005`; `002_timescale.sql` runs only with
`--timescale`. Foreign keys connect records, and composite keys prevent evidence
from attaching a chunk to the wrong document or an output to the wrong
prediction run.

## Data flow

1. `database.service` checks the connection, then fetches prices/company data
   and online source documents before opening persistence transactions.
2. It saves daily/five-minute bars, company snapshots, immutable source
   versions, and document chunks. Original financial publication dates are
   not inferred from the reporting period.
3. The model loader reads saved daily Close/Volume data within the snapshot range and fetch cutoff. Retrieval selects point-in-time passages for each chosen strategy.
   `ai.main.predict` receives those passages and a fetched market snapshot.
4. Gemini personas return direction, conviction, rationale, factors, and valid
   source IDs. The regression runs separately on price/volume history.
5. The service atomically saves forecast/output records and supplied evidence.
   It attaches source links, cited-by metadata, and educational explanations.
6. CLI scoring or API evaluation loads saved forecasts and appends outcomes
   without rerunning personas or modifying forecasts.

CLI `--database` enables this service unless `--no-log` is set. Without it,
JSONL logging remains the default. API reads return stored data; refresh and
prediction creation explicitly fetch online sources. See [SETUP.md](SETUP.md).

## Design rules

- Required secret for persistence: `DATABASE_URL`. Load it from the private
  backend environment; never print or commit credentials or connection URLs.
- Forecast inputs, model datasets, source versions, chunks, outputs, evidence, and evaluations are immutable
  through database triggers. Insert new records instead of replacing history.
- A source's publication date and our first-seen date are different facts.
  Retrospective retrieval must enforce availability at the forecast cutoff.
- Do not label today's fundamental snapshot as historically available. Store
  actual availability dates when known; record missing provenance explicitly.
- Prices carry a provider and adjustment basis. Never silently mix raw closes,
  split-adjusted prices, and total-return prices in evaluations.
- Preserve `flat` versus `unclear` and trading-day horizons. Agent confidence is
  signal strength, not calibrated probability.
- Store only supplied permitted source content and sanitized packets. Keep
  private documents, secrets, OAuth tokens, and brokerage credentials out of
  automatic logging and committed fixtures.
- SQL values use parameters. Dependencies stay pinned in `src/requirements.txt`.
- Core schema requires no extensions. Full-text indexing is not semantic vector
  search, and creating document tables does not automatically run RAG.
- Tests use synthetic data and mocks; real service verification is a separate
  step after configuration.

## Current retrieval policy

Long-term personas search the stored archive; day traders search the previous
7 days; index/options personas search 90 days. Company info (filings, press
releases) uses at least 140 days for every strategy, since the latest 10-Q stays
the company's current word for about a quarter. These are prototype settings,
not validated optimal lookbacks. Retrieval uses the latest eligible version per
source URL, respects first-seen and known publication cutoffs, and filters by
instrument, lookback, and requested evidence role.

Strategy keywords are ORed and matched against both the stored document title
and passage body using English full-text search. Relevance is the sum of their
`ts_rank_cd` scores; ties use first-seen recency and chunk ID. This makes a
headline-only keyword searchable for historical summary-only chunks and future
ingestion without re-ingesting sources. The title remains separate metadata;
returned excerpt text, chunk IDs, content hashes, and saved evidence are not
rewritten to include it. Migration `005` indexes `documents.title` alongside the
existing passage-body index.

Each strategy receives up to six passages mixed across three evidence roles.
Each role is retrieved separately (`retrieve_passages(role=..., fill=True)`),
and `service.mix_roles` takes them round-robin (company info, public opinion,
product event), so a role with fewer passages leaves slots to the others.
When nothing matches, or with `fill=True` when fewer than the limit match,
recent eligible passages fill the remaining slots with relevance 0. Keyword
matches stay first. The two-passages-per-document cap applies across the
combined keyword and fallback results: fallback excludes selected chunks and
subtracts each document's selected count from its remaining allowance before
applying the limit, so other documents can fill available slots.

With `RAG_BACKEND=snowflake`, each strategy/role list instead fuses Snowflake's
vector ranking with these keyword matches (`snowflake_rag.retrieval`). Snowflake
hits are reloaded through `passages_by_chunk_ids`, which applies the same
availability rules and two-per-document cap, and any Snowflake failure falls
back to keyword retrieval with a data warning. Evidence metadata records the
retriever (`retrieval`).

Chunks are 1,600 characters with overlap; passage start offsets are capped at
560,000 characters per document while source text remains stored. These
retrieval rules do not establish an improvement in prediction accuracy.

## Numerical model input

Database-backed forecasts copy the fetched daily snapshot (the one the personas
see) into an immutable `model_datasets` row, reload it, and pass that frame to
`ai.main.predict(regression_daily=...)`. Personas and the regression therefore
share one input even if another refresh rewrites `price_bars` concurrently, and
`regression_dataset.dataset_id` lets the exact rows be replayed with
`DatasetStore.load`. Direct/non-database predictions retain
the fetched snapshot fallback. The loader uses all matching rows, not the chart
endpoint's 500-row default. It selects one provider/adjustment basis, checks
market-session dates and finite numeric values, and records dataset metadata
and a fingerprint in `Prediction.input_snapshot.regression_dataset`.

`price_bars` holds the latest corrected values; since migration 008 every
superseded version is kept in `price_bar_revisions`. The standalone
`load_daily_prices` reads the latest values fetched by its cutoff;
`load_daily_prices_as_known` rebuilds the bars exactly as known at a moment. Forecast reproducibility comes from
`model_datasets`, whose sha256 is verified on load.
Online refresh is still required by the full persona workflow. Numerical models
can use the standalone loader without refresh or Gemini.
