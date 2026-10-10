# Finance prediction backend

Python backend for a financial learning dashboard. It fetches market information,
asks Gemini investor personas for directional forecasts, compares them with a
separate regression, and saves forecasts for later evaluation.

Start with the [simple database guides](src/database/docs/README.md) and
[setup instructions](src/database/SETUP.md).

| Reference | Purpose |
|---|---|
| [Source architecture](src/spec.md) | Packages and prediction flow |
| [Database spec](src/database/spec.md) | Tables, persistence, and retrieval rules |
| [Dashboard API](src/api/spec.md) | Routes and request formats |
| [Online sources](src/sources/spec.md) | What documents are actually collected |
| [Cloud migration](src/database/docs/tiger-cloud-migration.md) | Explicit move to Tiger Cloud later |

The local setup uses PostgreSQL, not TimescaleDB. The API runs on localhost;
frontend integration and authentication remain separate work. News ingestion
uses linked feed excerpts and headlines plus Hacker News threads; SEC filings and 8-K press
releases are optional. Retrieval is
keyword-based RAG, not semantic vector search.
