# Frontend

React 19 + Vite + React Router + Tailwind 4. Repo-wide setup, the after-pull checklist
and the frontend/backend contract are in the root [`AGENTS.md`](../AGENTS.md).

## Commands

```bash
npm install
npm run dev       # http://localhost:5173 — proxies /api to the backend on port 8000
npm test          # Vitest against a fake backend; no server needed
npm run build
```

The dashboard and sign-in pages need the backend API running for real data
(`uvicorn api.main:app` from `backend/src/`). Set `API_TARGET` to proxy somewhere other
than `http://127.0.0.1:8000`, or `VITE_API_BASE` to call an API URL directly.

## Layout

| Path | What it is |
|---|---|
| `src/App.jsx` | Routes: `/`, `/Signin`, `/Signup`, `/Dashboard`, `/scenarios` |
| `src/pages/` | Landing, sign-in, sign-up, and the lazy-loaded dashboard and scenarios pages |
| `src/features/market-dashboard/` | The dashboard: panels, data hooks and API client ([README](src/features/market-dashboard/README.md) lists which API route feeds each panel) |
| `src/lib/auth.js` | Email/password sign-up, sign-in, current user and sign-out (`/signup`, `/login`, `/oauth/me`, `/oauth/logout`) |
| `src/test/` | Test setup and `fakeBackend.js`, which answers `/api` requests in the real API's shapes |

## Tests and lint

Tests sit next to the code (`*.test.js`, `*.test.jsx`). `fakeBackend.js` mirrors the API's
response shapes; when a backend field changes, update it together with
`backend/src/tests/test_frontend_contract.py`.

CI lints `src/features src/lib src/test src/pages/auth-pages.test.jsx vite.config.js`.
`npm run lint` on everything still reports the unrendered `LearningMode` and `Honesty`
sections in `src/pages/Landing.jsx`; once they're rendered or removed, widen the CI step.
