# Market Move Dashboard

An educational market dashboard that explains *why* prices moved. It is
rendered at `/Dashboard` by [`src/pages/Dashboard.jsx`](../../pages/Dashboard.jsx).
Everything shown comes from the backend API (`backend/src/api/spec.md`): prices saved from
Yahoo Finance, linked news and filings, and the AI trader personas' saved forecasts.
It is not real-time and not financial advice.

Plain JavaScript and React, styled with Tailwind 4 utilities plus a scoped
stylesheet. The chart uses TradingView Lightweight Charts (`lightweight-charts`
4.2.3), lazy-loaded, with an accessible SVG fallback.

## Running it

From `frontend/`:

```bash
npm install
npm run dev       # then open http://localhost:5173/Dashboard
npm run build
```

The dashboard needs the API on port 8000 (from `backend/src/`:
`uvicorn api.main:app`, with `API_REQUIRE_SIGN_IN=false` in `backend/.env` to run
forecasts without Google sign-in). The Vite dev server proxies `/api` to it, so there
is no CORS setup; set `API_TARGET` to proxy elsewhere, or `VITE_API_BASE` to call an
API URL directly. Add `?dev` to the URL to show the preview-state control.

## How it is wired into the app

- `pages/Dashboard.jsx` lazy-loads `MarketDashboard.jsx`, so the dashboard code,
  its CSS, and the chart library load only when `/Dashboard` is visited.
- `vite.config.js` enables the `@tailwindcss/vite` plugin.
- Nothing else in the app was changed: `main.jsx`, `App.jsx`, `index.css`,
  `App.css`, and `index.html` are untouched.

## Style isolation

The rest of the app has its own global styles (`src/index.css`), so the
dashboard is kept self-contained:

- Everything lives under a `.mmd` wrapper. Design tokens (`--bg`, `--accent`,
  ...) are declared on `.mmd`, shadowing the app's `:root` variables of the same
  name only inside the dashboard. Selectors use `:where(.mmd)` so they keep
  their original specificity and Tailwind utilities can still override them.
- Tailwind's global preflight is **not** imported. A scoped reset in
  `styles/market-dashboard.css` covers the parts the dashboard relies on.
- The light/dark theme is a `data-theme` attribute on the `.mmd` wrapper, not on
  `<html>`.
- While the dashboard is mounted, `html:has(.mmd)` rules reset the root font
  size to 16px and release `#root` from its fixed 1126px centered column. They
  stop matching as soon as you navigate away.
- URL state (`?symbol=NVDA&timeframe=1M&news=All`) goes through React Router's
  `navigate(..., { replace: true })`, so router history state is preserved.

## Structure

```
features/market-dashboard/
├── MarketDashboard.jsx        # app state + page layout (was App.jsx)
├── styles/market-dashboard.css
├── constants/  strings.js (all user-facing copy), options.js
├── context/    UIContext.js (open toggletip, learning mode, theme)
├── hooks/      useResource.js (API data hooks + background forecast job), useRoving.js (tab keyboard nav)
├── lib/        api (backend client), assets (search list, ticker rule), moves (biggest moves + headlines),
│               format, marketStatus, preferences (localStorage), tickStore (shared latest prices)
└── components/
    ├── ui/       AvatarMenu, PanelBoundary, PriceCell, Search, StatePanel, Term, VirtualList
    ├── layout/   Header, Hero, MarketPulse, DevStateControls, AccessibilityNotes, SkipLinks, Footer
    └── panels/   Story, Chart (+ ChartGraphic), Why, Forecast, Personas, News, Watchlist
```

## Where each panel's data comes from

| Panel | API | Notes |
|---|---|---|
| Price, story, watchlist, market pulse | `GET /stocks/{t}/history` (`1d` and `5m`) | Latest saved 5-minute bar, else the daily close; change vs the previous daily close |
| Chart, why it moved | `GET /stocks/{t}/history` | 1D/1W use 5-minute bars, longer timeframes daily bars. The three biggest moves are matched to headlines saved that New York session |
| News | `GET /stocks/{t}/news` | Filtered by the role the backend assigned (company info, opinion, product & events); links open the source |
| Forecast, personas, story summary | `GET /predictions?ticker=&limit=1` | The latest saved forecast. "Run a forecast" posts `/prediction-jobs` and polls every 3 s (10–60 s, longer on a rate-limited Gemini key) |
| Refresh data / Fetch data | `POST /stocks/{t}/refresh` | Stores prices, company data and documents for any ticker (~30 s, no model calls), then every panel refetches |

## Tests

`npm test` (Vitest, jsdom) runs in a few seconds with no backend: `src/test/fakeBackend.js`
answers every `/api` request with data in the API's real shapes. Unit tests sit next to
`lib/` and `hooks/` (API client errors, latest-price rules, New York session dates, job
polling with fake timers); `MarketDashboard.test.jsx` renders the whole page for saved data,
missing data, backend outages, refreshes and forecast jobs. The backend side of the same
contract is `backend/src/tests/test_frontend_contract.py`: change both together.

There is no live price feed: prices are as of the last refresh. A real feed would
call `publishTick({ symbol, price, at })` from `lib/tickStore.js`.

## Before launch

- The forecast disclaimer in `ForecastPanel.jsx` is draft copy and needs legal review.
- The watchlist links to `/paper-trading`, the simulated-trading page in `features/paper-trading/`. It uses the real backend (`/paper/*`), not the mock data here.
- Run the manual screen-reader audit listed in the on-page accessibility notes
  (NVDA, JAWS, VoiceOver).
