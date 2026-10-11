# Market Move Dashboard

An educational market dashboard that explains *why* prices moved. It is
rendered at `/Dashboard` by [`src/pages/Dashboard.jsx`](../../pages/Dashboard.jsx).
All data is illustrative mock data, not exchange prices, and not financial advice.

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
├── data/       mockData.js (data shapes documented in comments)
├── context/    UIContext.js (open toggletip, learning mode, theme)
├── hooks/      useResource.js (mock fetching), useRoving.js (tab keyboard nav)
├── lib/        format, marketStatus, preferences (localStorage),
│               tickStore + MockWebSocket (live ticks), calculateMoves
└── components/
    ├── ui/       AvatarMenu, PanelBoundary, PriceCell, Search, StatePanel, Term, VirtualList
    ├── layout/   Header, Hero, MarketPulse, DevStateControls, AccessibilityNotes, SkipLinks, Footer
    └── panels/   Story, Chart (+ ChartGraphic), Why, Forecast, Calendar, News, Watchlist
```

## Connecting real data

1. Replace the `make` functions in `hooks/useResource.js` with real `fetch`
   calls, keeping the `{ data, status, refetch, isStale }` shape. The backend
   already serves `/stocks/{ticker}/history`, `/stocks/{ticker}/news`, and
   `/predictions`.
2. Replace `MockWebSocket` with a real WebSocket client that calls
   `publishTick({ symbol, price, at })`.

## Before launch

- The forecast disclaimer in `ForecastPanel.jsx` is draft copy and needs legal review.
- Hide `DevStateControls` behind an environment flag.
- The watchlist links to `/paper-trading`, the simulated-trading page in `features/paper-trading/`. It uses the real backend (`/paper/*`), not the mock data here.
- `App.jsx` renders a "Testing" line under every page, including this one.
- Run the manual screen-reader audit listed in the on-page accessibility notes
  (NVDA, JAWS, VoiceOver).
