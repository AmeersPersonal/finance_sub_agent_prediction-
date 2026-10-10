# spec: backend/src/oauth/

## TODOS

- [x] `routes.py` imported the non-existent `fast_api`; now uses `fastapi`.
- [x] `fastapi==0.143.0` pinned in `../requirements.txt`; `uvicorn==0.54.0` added for serving (`api/`).
- [x] Choose the provider and flow, and write the scopes here: see Provider and flow.
- [x] Define where tokens are stored: see Token storage.
- [x] Add a `state` check for the callback route (CSRF): state cookie + server-side single-use state, plus PKCE.
- [x] Tests with a fake provider; no network (`tests/test_oauth.py`).
- [x] Shared store for several workers: `DatabaseStore` keeps pending logins and sessions in PostgreSQL (migration 007), storing only SHA-256 hashes of the state values and session ids. `OAUTH_SESSION_STORE=database` selects it; memory stays the default. PostgreSQL rather than Redis: the API already needs it, so no new service or dependency.
- [x] ID tokens: the API calls userinfo and never trusts the ID token; that's now a rule below, not a task.
- [x] Deleted the `.gitkeep`.

## Purpose

Sign users in so the API can tell who is calling. Not yet required by any
pipeline route (see `api/spec.md`).

## Provider and flow

- **Provider:** Google, as OpenID Connect sign-in. The authorize, token and
  userinfo URLs and the scopes are environment variables (`OAUTH_*`, see
  `backend/.env.example`), so another OIDC provider is a config change.
- **Flow:** Authorization Code with PKCE (S256) and a `state` parameter.
- **Scopes:** `openid email profile`, identity only. The API never calls Google
  for the user, so it asks for nothing more.

```
GET  /oauth/login     -> 302 to the provider; sets the HttpOnly oauth_state cookie (10 min)
GET  /oauth/callback  -> checks state (query == cookie, issued here, unused), exchanges the
                         code with the PKCE verifier, reads userinfo, sets the session cookie
GET  /oauth/me        -> the signed-in user, or 401
POST /oauth/logout    -> ends the session
```

## Token storage

- Provider access and ID tokens are used once in the callback to read the
  profile, then dropped. They're never stored, logged or written to disk.
- The browser holds only an opaque random session id (HttpOnly, SameSite=Lax,
  Secure unless `OAUTH_COOKIE_SECURE=false`).
- The server maps session id -> `{sub, email, name}` for 8 hours: in process
  memory by default (a restart signs everyone out), or in PostgreSQL with
  `OAUTH_SESSION_STORE=database`, where only a hash of the id is stored.
- Client id and secret come from the environment only.

## Files

| File | Role |
|---|---|
| `provider.py` | `OAuthSettings.from_env()` (Google defaults), `pkce_challenge`, `Provider` protocol, `HttpProvider` (token exchange + userinfo via httpx) |
| `sessions.py` | `SessionStore` protocol; `MemoryStore` (default, one process, thread-safe) and `DatabaseStore` (shared through PostgreSQL); `store_from_env` picks one from `OAUTH_SESSION_STORE` |
| `routes.py` | The four routes above, plus `current_user` for other routes to require sign-in. Settings, store and provider are dependencies tests override; the store is created on first use, after `.env` is loaded |

## Rules

- Client secrets, tokens and keys stay out of git; load them from environment variables.
- Do not weaken the OAuth patterns in the root `.gitignore`.
- Never log tokens or the authorization code; log only the error type.
- Identity comes from the userinfo endpoint over TLS. If the API ever trusts the
  ID token instead, verify its signature (JWKS), `aud`, `iss`, `exp` and a
  `nonce` first.
- Account data is keyed by `<userinfo host>:<sub>`, never the email, which can
  change hands (`api.main.account_reference`).
