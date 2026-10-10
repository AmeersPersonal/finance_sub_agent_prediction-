# How the database works

## Connecting

The Python backend uses Psycopg, a PostgreSQL driver. `DATABASE_URL` in the
private environment gives it the database address and login details.

Today the server runs on this computer. Later it can run in Tiger Cloud with
TLS encryption. The frontend calls backend routes; the database password stays
on the backend.

## Writing and reading

**Write:** Python sends SQL such as `INSERT` with the values to store.
PostgreSQL saves records when the transaction commits. Related forecast and
evidence writes succeed together, or roll back together on failure.

**Read:** Python sends SQL such as `SELECT`. PostgreSQL returns matching rows,
which Psycopg turns into Python dictionaries. The backend returns JSON to the
frontend. It does not download the entire database.

## Current database-backed workflow

1. Check the database connection before spending Gemini requests.
2. Fetch market prices, company information, and online documents.
3. Save price records, a dated company snapshot, document versions, and passages.
4. Read saved daily prices/volume back from PostgreSQL for the regression, and
   retrieve relevant passages for each strategy, excluding future evidence.
5. Give the strategy metrics and retrieved passages to Gemini personas. Run the
   separate price/volume regression benchmark.
6. Save the forecast, individual outputs, input packets, source links, learning
   explanations, and the exact passages supplied. Record which sources agents
   actually cited separately from those merely provided.
7. Later, fetch actual outcomes and save evaluations after the horizon ends.

The CLI uses this path with `--database`, unless `--no-log` is set. API forecast
creation uses the same service. A market refresh stores sources without calling
Gemini. Reading saved charts/news/forecasts does not refresh online sources.

Without `--database`, the CLI retains the original JSONL workflow. Input packets
are not a complete historical dataset for retraining every model; private local
source text is not automatically copied into database logging.

## Documents and RAG

Yahoo RSS provides linked headlines and available excerpts, not whole publisher
articles. Optional SEC collection downloads primary company filing text when
`SEC_USER_AGENT` supplies an application name and contact email.

Documents are stored, split into passages, and searched by keywords (any keyword matches; more matches rank higher). Selected
passages become evidence in Gemini's prompt: this is keyword RAG. Semantic
vector search and general publisher scraping are future work. Each strategy
gets a mix of company info, public opinion and product-event passages.

Keeping the supplied text and dates preserves what the agent saw even if the
original page changes. Missing sources produce warnings rather than invented
coverage.

## TimescaleDB

TimescaleDB would organize the price table into time-based chunks under one
hypertable. SQL and the other tables remain usable. It improves time-series
management; it does not collect data, predict prices, or move records to cloud.

[Model data loader](model-data.md) explains the PostgreSQL-to-model adapter and its reuse for a future neural network.
