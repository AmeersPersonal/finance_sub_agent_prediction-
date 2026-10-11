# Database setup

For short explanations of the schema, data flow, and cloud migration plan, see
the [database guides](docs/README.md).

## Local development instance on this computer

A separate PostgreSQL 18 instance is configured for this checkout:

- Database: `finance_dev`; application role: `finance_app`.
- Address: `127.0.0.1:55440` (only this computer can connect).
- Persistent cluster files: `backend/data/postgres/` (gitignored).
- Private connection: `backend/.env`, created with owner-only permissions.
- Python environment: `backend/.venv/`.
- User service: `hack-knight-postgres.service`, enabled to start at user login.

Ordinary migrations through `005_document_title_search.sql` were applied and
verified on this local application instance on October 10, 2026. The title GIN
index was valid and ready, and its migration-history checksum matched the file.
This status does not describe other developers' or cloud databases.
TimescaleDB is not installed/enabled in this instance. Existing system PostgreSQL
clusters are separate and unchanged.
The configured Gemini key has been verified with a real structured-output request and a saved Nvidia forecast.

Manage the running user service from a normal terminal:

```bash
systemctl --user status hack-knight-postgres.service
systemctl --user restart hack-knight-postgres.service
systemctl --user stop hack-knight-postgres.service
systemctl --user start hack-knight-postgres.service
```

From `backend/src/`, check the connection without Gemini requests:

```bash
../.venv/bin/python -m database.migrate
../.venv/bin/python main.py --score --database
```

Data survives server restarts and reboots; the service starts at login, rather
than guaranteeing availability before login. The generated service file lives
in `backend/data/hack-knight-postgres.service` and points to this checkout, so
moving/removing the checkout requires updating the service. `local_postgres.sh`
provides manual initialization/start/stop/status commands for a new checkout;
it does not create database users or credentials. Stop the user service before
managing its server manually. Cloud setup below is a separate later step.

The backend connects to Tiger Data through PostgreSQL, using a database
connection URL. A Tiger Cloud management API key is **not** required to insert
prices or save predictions. Snowflake credentials are needed only for the
optional vector retrieval (`RAG_BACKEND=snowflake`; see
[snowflake_rag/spec.md](../snowflake_rag/spec.md)). No Solana credentials are
required.

## 1. Create the database service

1. Sign in to [Tiger Console](https://console.cloud.tigerdata.com/) and create a
   development service using your team's credits.
2. Save the downloaded database configuration securely when the service is
   created; it includes the database password. Wait for the service to be ready.
3. Copy the PostgreSQL connection URL from that configuration. If copying it
   from the console instead, ensure that its password is included: the console
   connection string may omit it. This is the database password, not your Tiger
   Console login password.
4. Keep SSL enabled for the cloud connection (`sslmode=require`, or the stricter
   SSL configuration provided by Tiger). If manually composing a URL,
   percent-encode special characters in its username and password.

These steps follow Tiger Data's [service creation
guide](https://www.tigerdata.com/docs/get-started/quickstart/create-service) and
[connection details
guide](https://www.tigerdata.com/docs/use-timescale/latest/integrations/find-connection-details).

## 2. Configure backend secrets

Use the gitignored `backend/.env`, or your deployment's secret environment
variables. If `.env` already exists, edit it rather than replacing it. Otherwise,
copy `backend/.env.example` to `backend/.env` first.

```dotenv
# Placeholder examples only: put real values in the private .env.
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require
GEMINI_API_KEY=YOUR_PRIVATE_GEMINI_KEY
```

`DATABASE_URL` is required only when migrating or using database persistence.
`GEMINI_API_KEY` remains required for real persona predictions, but is not
needed for schema migration. `GEMINI_MODEL` is optional; use the existing
backend default unless your team intentionally changes it.

Get the Gemini key from [Google AI Studio](https://aistudio.google.com/app/apikey).
Choose or import the team's Google Cloud project and create a key in its API
Keys page. Google describes these steps in its [API key
guide](https://ai.google.dev/gemini-api/docs/api-key). Keep the key and database
URL in the backend; neither belongs in frontend code, screenshots, chat, or Git.

Current yfinance, Yahoo RSS, and keyless BLS ingestion needs no additional API
keys. These sources do not provide a guaranteed live feed or full-article
archive. A future article provider, live-feed provider, or embedding service may
have separate credentials; no placeholder integration is presented as working.

## 3. Install and migrate

From `backend/`, with your Python virtual environment active:

```bash
pip install -r src/requirements.txt
cd src
python -m database.migrate
```

The core schema uses ordinary PostgreSQL. On a service with TimescaleDB,
optionally enable the price-bar hypertable migration:

```bash
python -m database.migrate --timescale
```

Migration requires schema creation permissions; the TimescaleDB option also
requires the extension to be available. Migration tracking permits reruns
without rebuilding the database. The runner records each file's name and checksum
in `schema_migrations`, skips applied files, and rejects edits to applied files.
It applies all pending ordinary migrations, not just a named migration; inspect
pending files before running it against an existing database. Prediction startup
does not run migrations automatically.

`006_snowflake_sync.sql` adds `snowflake_synced_chunks`, which the optional
Snowflake sync job uses to track what it has indexed. It is an ordinary table
and needs no Snowflake account to apply.

`005_document_title_search.sql` adds a GIN index on stored document titles. It
covers existing rows and future inserts without re-ingesting documents or
rewriting immutable chunks or evidence. Retrieval searches those titles alongside
passage bodies. This ordinary PostgreSQL update does not require TimescaleDB or
transfer data to another server. Every separately configured database needs its
own migration check. Do not assume that running a migration populates historical
articles or prices: it creates the storage structures.

Run it again after pulling new code: it applies only what's new. Migration 005
indexes document titles for retrieval; 006 tracks what the optional Snowflake
index holds; 007 adds shared sign-in tables (used only with
`OAUTH_SESSION_STORE=database`); 008 archives every price-bar correction so past
datasets can be rebuilt exactly; 009 adds email/password accounts (`user_accounts`)
for `POST /signup` and `/login`. Run it before using the new code: title search
and the Snowflake sync need 005 and 006.

## 4. Save and evaluate predictions

From `backend/src/`:

```bash
python main.py NVDA --strategy long_term --age 18-24 --database
python main.py --score --database
```

The first command fetches and stores prices, company information, linked RSS evidence, and optional SEC filings. It retrieves source passages for the personas, then saves the forecast, numerical/headline input packets, source links, and provided excerpts. It makes external data and Gemini requests. The second scores
database-backed predictions whose horizons have elapsed and stores evaluation
results; outcomes are fetched through the existing market-data path. Without
`--database`, the existing JSONL workflow remains available.

For a faster trial, choose one strategy and one age band as above. Five trading
days is the default prediction horizon, not five minutes. Database configuration
does not change forecasting or calibrate agent confidence.

## 5. Backups and access roles

What is kept, the backup schedule, source-use rules and database roles are in
[retention-and-access.md](docs/retention-and-access.md). In short, from `backend/src/`:

```bash
python -m database.backup                           # pg_dump to backend/data/backups/, keeps 7 daily / 4 weekly / 12 monthly
psql "$ADMIN_DATABASE_URL" -f database/roles.sql    # once per shared database, and after each migration
```

On a shared or hosted database, point the API's `DATABASE_URL` at the
`finance_api` login that `roles.sql` creates, not at the owner. The local
development cluster above can keep its single application role.

## Scope and verification

This setup connects the CLI and local FastAPI dashboard routes to PostgreSQL. RSS excerpts and optional SEC filing text are stored and retrieved through keyword RAG, optionally fused with Snowflake vector search. Signed-in accounts can save preferences (`/me/preferences`). Full publisher article scraping and Reddit ingestion are not implemented. See [the API walkthrough](docs/dashboard-api.md).

Connection and migration success must be checked against your actual service
after private credentials are configured. Offline tests do not establish that
a live Tiger Cloud service or Gemini account is connected.

The default test suite uses fake models and synthetic data. Optional PostgreSQL
integration tests require an isolated local server reached by a Unix socket;
they refuse remote/cloud hosts and create a temporary schema for each test:

```bash
TEST_DATABASE_URL='postgresql:///TEST_DB?host=/LOCAL_SOCKET_DIRECTORY' pytest
```

Do not point integration tests at a shared application database. The optional
Timescale migration requires a Timescale-enabled server and is not covered by
the ordinary PostgreSQL checks.

## Optional full company filings

Set `SEC_USER_AGENT` in your private backend environment to an application name
and your real contact email, for example `FinanceLearningDemo contact@example.com`
(replace the example email). This identifies SEC requests; no SEC API key is
needed. Without it, linked news excerpts still work and the result states that
filings are disabled. Restart the API service after changing environment values.

## Local dashboard API

The `hack-knight-api.service` user service is enabled on this computer. It starts
at login and listens only on `127.0.0.1:8000`. Open
[interactive API docs](http://127.0.0.1:8000/docs) to inspect and try routes.
Both generated user-service definitions live under gitignored `backend/data/`
and point to this checkout. No service definitions are installed automatically
on teammates' computers or after a cloud deployment.

```bash
systemctl --user status hack-knight-api.service
systemctl --user restart hack-knight-api.service
```

Full route details are in [api/spec.md](../api/spec.md). The frontend still needs
to call these endpoints; starting the API does not build or merge the Frontend
branch. Database-backed requests create shared research forecasts, not trades.

Creating forecasts needs a signed-in user by default. Without OAuth
credentials on a development machine, set `API_REQUIRE_SIGN_IN=false` in
`backend/.env` and restart the service.

On a computer without these services, `docker compose up --build` from
`backend/` starts PostgreSQL, applies the migrations and serves the API on
`127.0.0.1:8000` (it needs `POSTGRES_PASSWORD` in `backend/.env`; see the
comments in `docker-compose.yml`).
