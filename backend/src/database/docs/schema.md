# What the schema stores

A schema is the database's blueprint: tables, their fields, and the rules that
connect them. A table contains records, like rows in a spreadsheet.

## Tables

| Table | Simple explanation |
|---|---|
| `instruments` | The assets we discuss, such as Nvidia stock or an ETF. |
| `price_bars` | Prices and volume for a time interval; includes provider and price-adjustment basis. |
| `documents` | An article, report, announcement, or post, with its title, text, URL, dates, version hash, and a title keyword-search index. |
| `document_instruments` | Connects a document to each asset it mentions. |
| `document_chunks` | Smaller passages from a document, with a keyword-search index. |
| `fundamental_snapshots` | Company financial information saved with availability and collection dates. |
| `prediction_runs` | A forecast request: asset, time horizon, model version, frozen persona input packets, and result. |
| `prediction_outputs` | Each persona answer, the combined answer, regression, and baseline forecasts. |
| `prediction_evidence` | Source excerpts linked to a forecast and optionally an individual output. |
| `evaluations` | What actually happened later and whether an output's direction was correct. |
| `user_preferences` | A user's selected strategy, age band, experience, and preferences. No account passwords. |
| `user_accounts` | Email/password sign-in accounts: email, first and last name, and a one-way hash of the password (never the password itself). |

`prediction_jobs` holds short-lived background forecast jobs when the API runs on AWS
Lambda (`JOBS_BACKEND=lambda`): who started one, its status and the finished forecast.
Rows are deleted an hour after they finish; the forecast itself lives in `predictions`.

`schema_migrations` is an additional bookkeeping table recording which schema
updates have already been applied, with checksums to detect changed migration files.

Migration `005_document_title_search.sql` adds `documents_title_search_idx`, a
GIN index on `to_tsvector('english', title)`. It indexes both existing titles
and future inserts. The existing `document_chunks_search_idx` indexes passage
bodies. Searching both lets a title keyword find a summary that does not repeat
that word, without changing immutable document/chunk text or saved evidence.
Apply pending migrations explicitly to each database; see [setup](../SETUP.md).

## Example relationships

One Nvidia instrument has many price records and prediction runs. Each run has
many outputs and later evaluations. One article may mention Nvidia and another
company, so a linking table connects it to both instruments.

Records use IDs to make these connections. Foreign keys prevent links to records
that do not exist. Numbers and dates use regular columns; long text uses text
columns; flexible information packets use `JSONB`, PostgreSQL's JSON format.

## Why preserve history?

Source text versions, financial snapshots, forecasts, outputs, and evidence
cannot be edited in place. New versions are inserted instead. This keeps an
old forecast understandable after the market or an article changes.

Evidence must have been published and collected by the forecast cutoff. A
later article cannot be attached as if the agent had seen it earlier.

These tables describe what we can store. Database-backed forecasts now populate price history, financial snapshots, source documents and passages, forecast records, outputs, and evidence. Scoring populates evaluations. User preferences still await authentication and frontend integration.
