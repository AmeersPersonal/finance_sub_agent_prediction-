# spec: backend/src/oauth/

## TODOS

- [ ] `routes.py` has `import fast_api`, which is not a real module. The package is `fastapi`.
- [ ] Add `fastapi` (and `uvicorn`) to `../requirements.txt`, pinned.
- [ ] Choose the provider and flow, and write the scopes here.
- [ ] Define where tokens are stored; they must never be committed (`*.json`, `token.pickle`, `*.pem` are gitignored).
- [ ] Add a `state` check for the callback route (CSRF).
- [ ] Tests with a fake provider; no network.

## Purpose (intended)

HTTP routes for OAuth login/callback so the API can act for a user. Not
connected to the prediction pipeline yet.

## Files

| File | Role | State |
|---|---|---|
| `routes.py` | FastAPI router for OAuth | one broken import line |
| `.gitkeep` | keeps the folder tracked | |

## Rules

- Client secrets, tokens and keys stay out of git; load them from environment variables.
- Do not weaken the OAuth patterns in the root `.gitignore`.
