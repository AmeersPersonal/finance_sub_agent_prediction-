# Trying the dashboard backend

The local API connects the frontend to PostgreSQL and the prediction service.
It has interactive documentation at <http://127.0.0.1:8000/docs> when running.

From `backend/src/`, start it manually if no API service is running:

```bash
../.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

On this computer, the configured user service can instead be managed with:

```bash
systemctl --user status hack-knight-api.service
systemctl --user restart hack-knight-api.service
```

## Example workflow

1. Open `/health` to check that the backend can reach the database.
2. `POST /stocks/NVDA/refresh` fetches and stores prices, company information,
   and available online documents. It does not call Gemini.
3. Read `/stocks/NVDA/history` for the chart and `/stocks/NVDA/news` for links.
4. `POST /predictions` creates and saves a forecast. Example request body:

```json
{
  "ticker": "NVDA",
  "horizon_days": 5,
  "strategies": ["long_term"],
  "age_bands": ["18-24"]
}
```

5. Read `/predictions?ticker=NVDA` or `/predictions/{id}` to retrieve it. The
   result includes persona rationales, the regression benchmark, source links,
   learning explanations, and missing-data warnings.
6. `POST /predictions/{id}/evaluate` checks real outcomes. Before the horizon
   ends, the forecast remains pending. Read `/predictions/{id}/evaluation` for
   saved evaluations.

News ingestion collects Yahoo feed excerpts, Google News headlines and Hacker
News threads (top comments on stories naming the company). Full
SEC filing text and 8-K press releases are optional: configure
`SEC_USER_AGENT` with your application name and real contact email. This is
not an API key. Reddit is not collected (its API policy requires approval and
forbids sharing its data). Publisher articles are never scraped. Each source in a
prediction carries its `role` (company_info, public_opinion, product_event).

The service uses keyword RAG: retrieve relevant saved passages, provide them to
Gemini, and preserve the evidence. Source IDs actually cited by personas are
recorded separately from passages merely supplied. Forecast strength is not a
probability of success.

Keep the API bound to localhost for this demo. Authentication and frontend
integration are separate work; no real trades are executed.
