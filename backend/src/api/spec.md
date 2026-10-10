# spec: backend/src/api/

## TODOS

- [ ] Require `oauth.routes.current_user` on `POST /predict` before exposing the API publicly (each call spends Gemini quota), then rate-limit per user.
- [ ] `POST /predict` holds the request open for the whole run (10-60 s on the free tier). If a frontend needs it, return a job id and poll instead.
- [ ] `GET /score` refetches closes for every logged ticker on each call; cache the report for a few minutes if it gets called often.

## Purpose

The CLI's prediction pipeline over HTTP, plus the OAuth sign-in routes.

```
uvicorn api.app:app --reload        # from backend/src; interactive docs at /docs
```

## Files

| File | Role |
|---|---|
| `app.py` | FastAPI app. `POST /predict` (same options as the CLI: horizon, strategies, age bands, weights or `"auto"`, modes, `live`, `audit`, `log`), `GET /score` (the `--score` report without per-outcome detail), `GET /health`; mounts `oauth/` routes |

## Design rules

- Same pipeline as `main.py`: fetch the snapshot, `predict()`, optional
  `audit_prediction()`, append to the same log. Don't fork the logic.
- The LLM, the snapshot fetcher and the log path are FastAPI dependencies
  (`get_llm`, `get_fetcher`, `get_log_path`); tests override them, so no test
  touches the network or Gemini.
- One shared `GeminiLLM`, so its concurrency cap and backoff cover all requests.
- Bad input (ticker format, unknown strategy, age band or mode, no eligible
  personas, unknown ticker) is a 422; every persona failing is a 502; a missing
  `GEMINI_API_KEY` is a 503.
- `.env` is loaded at startup (lifespan), not at import, so importing the app in
  tests doesn't read it.
