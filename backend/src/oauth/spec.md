# spec: backend/src/oauth/

## TODOS

- [x] `routes.py` imported the non-existent `fast_api`; now uses `fastapi`.
- [x] `fastapi==0.143.0` pinned in `../requirements.txt`; `uvicorn==0.54.0` added for serving (`api/`).
- [x] Choose the provider and flow, and write the scopes here: see Provider and flow.
- [x] Define where tokens are stored: see Token storage.
- [x] Add a `state` check for the callback route (CSRF): state cookie + server-side single-use state, plus PKCE.
- [x] Tests with a fake provider; no network (`tests/test_oauth.py`).
- [ ] Before running more than one worker process, move `MemoryStore` to a shared server-side cache (Redis). Never to files in the repo.
- [ ] If the API ever trusts the ID token instead of calling userinfo, verify its signature (JWKS), `aud`, `iss`, `exp` and a `nonce`.
- [ ] Delete the now-unneeded `.gitkeep`.

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
- The server maps session id -> `{sub, email, name}` in process memory
  (`sessions.py`) for 8 hours. A restart signs everyone out.
- Client id and secret come from the environment only.

## Files

| File | Role |
|---|---|
| `provider.py` | `OAuthSettings.from_env()` (Google defaults), `pkce_challenge`, `Provider` protocol, `HttpProvider` (token exchange + userinfo via httpx) |
| `sessions.py` | `MemoryStore`: pending logins (state -> verifier) and sessions, with expiry; thread-safe |
| `routes.py` | The four routes above, plus `current_user` for other routes to require sign-in. Settings, store and provider are dependencies tests override |
| `.gitkeep` | no longer needed |

## Rules

- Client secrets, tokens and keys stay out of git; load them from environment variables.
- Do not weaken the OAuth patterns in the root `.gitignore`.
- Never log tokens or the authorization code; log only the error type.
