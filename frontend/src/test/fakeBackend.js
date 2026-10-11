// An in-memory stand-in for the backend API, installed as `fetch`. Tests seed it with
// bars, documents and forecasts in the same shapes the real API returns
// (backend/src/api/main.py; pinned by backend/src/tests/test_frontend_contract.py).
import { vi } from 'vitest';

export const json = (body, status = 200, headers = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });

/** Daily bars ending on `lastDay` (YYYY-MM-DD), one per weekday, as the API sends them (NY midnight). */
export function dailyBars(closes, lastDay = '2026-10-09') {
  const days = [];
  const date = new Date(`${lastDay}T04:00:00Z`);
  while (days.length < closes.length) {
    const weekday = date.getUTCDay();
    if (weekday !== 0 && weekday !== 6) days.unshift(new Date(date));
    date.setUTCDate(date.getUTCDate() - 1);
  }
  return closes.map((close, i) => bar(days[i].toISOString().replace('.000Z', '+00:00'), close, '1d'));
}

/** 5-minute bars starting at `start` (ISO, UTC). */
export function intradayBars(closes, start = '2026-10-09T13:30:00Z') {
  const at = new Date(start).getTime();
  return closes.map((close, i) => bar(new Date(at + i * 300000).toISOString().replace('.000Z', '+00:00'), close, '5m'));
}

function bar(barAt, close, interval) {
  return {
    bar_at: barAt, open: close - 1, high: close + 1, low: close - 2, close, volume: 1000,
    interval, provider: 'yfinance', adjustment_basis: 'total_return', fetched_at: '2026-10-10T01:00:00+00:00',
  };
}

export function document(id, title, overrides = {}) {
  return {
    id, title, source_url: `https://news.example/${id}`, source_name: 'Example News', document_type: 'news',
    content_kind: 'excerpt', excerpt: `${title} excerpt`, published_at: '2026-10-09T15:00:00+00:00',
    first_seen_at: '2026-10-10T01:00:00+00:00', classification: { role: 'public_opinion', method: 'keyword' },
    ...overrides,
  };
}

const persona = (strategy, ageBand, direction, conviction, rationale) => ({
  persona_id: `${strategy}:${ageBand}`, strategy, age_band: ageBand, mode: 'default', model: 'test', temperature: 0.4,
  view: { direction, conviction, rationale, key_factors: [], source_ids: [] }, error: null,
});

/** A saved forecast (backend `Prediction`), with only the fields the dashboard reads overridden. */
export function prediction(overrides = {}) {
  return {
    id: 'p1', ticker: 'NVDA', horizon_days: 5, direction: 'up', confidence: 0.63, net_score: 0.6, agreement: 0.75,
    by_strategy: { long_term: 0.56, day_trader: 0.67, index_options: -0.1 },
    flat_band_pct: 1.1, last_price: 110, data_as_of: '2026-10-09', generated_at: '2026-10-10T03:03:00Z',
    next_earnings_date: '2026-10-28', earnings_within_horizon: false,
    baselines: { always_up: 'up', momentum: 'down', linear_regression: 'flat' },
    headline_sentiment: { overall: 0.4, summary: 'Chip demand headlines are upbeat.' },
    personas: [
      persona('long_term', '25-39', 'up', 0.75, 'Strong cloud growth.'),
      persona('day_trader', '18-24', 'up', 0.8, 'Momentum is strong.'),
      persona('index_options', '40-54', 'down', 0.55, 'Volatility is rising.'),
      { ...persona('day_trader', '55-65', 'up', 0.5, ''), view: null, error: 'Model call failed' },
    ],
    data_warnings: [],
    ...overrides,
  };
}

/**
 * Installs the fake as `fetch` and returns its state. Tests edit `state.bars[ticker]`,
 * `state.news[ticker]`, `state.predictions[ticker]`; set `state.down` to refuse connections,
 * `state.respond(method, path, url)` to answer a request differently, and
 * `state.jobs` (a list of job views) for what each poll of a forecast job returns.
 */
export function installFakeBackend() {
  const state = {
    bars: {}, news: {}, predictions: {}, calls: [], down: false, respond: null, jobs: [],
    onRefresh: null, user: null,
  };
  const handle = async (input, init = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, 'http://localhost');
    const method = (init.method || 'GET').toUpperCase();
    const path = url.pathname.replace(/^\/api/, '');
    state.calls.push({ method, path, query: Object.fromEntries(url.searchParams), body: init.body ? JSON.parse(init.body) : undefined, init });
    if (state.down) throw new TypeError('Failed to fetch');
    const custom = state.respond?.(method, path, url);
    if (custom) return custom;

    let match;
    if ((match = path.match(/^\/stocks\/([^/]+)\/history$/)) && method === 'GET') {
      const ticker = decodeURIComponent(match[1]);
      const interval = url.searchParams.get('interval');
      const limit = Number(url.searchParams.get('limit'));
      const bars = (state.bars[ticker]?.[interval] || []).slice(-limit);
      return json({ ticker, interval, bars });
    }
    if ((match = path.match(/^\/stocks\/([^/]+)\/news$/)) && method === 'GET') {
      const ticker = decodeURIComponent(match[1]);
      return json({ ticker, documents: (state.news[ticker] || []).slice(0, Number(url.searchParams.get('limit'))) });
    }
    if ((match = path.match(/^\/stocks\/([^/]+)\/refresh$/)) && method === 'POST') {
      const ticker = decodeURIComponent(match[1]);
      state.onRefresh?.(ticker);
      return json({ ticker, new_daily_bars: 0, new_intraday_bars: 0, document_ids: [], warnings: [] });
    }
    if (path === '/predictions' && method === 'GET') {
      const saved = state.predictions[url.searchParams.get('ticker')];
      return json({ predictions: saved ? [saved] : [] });
    }
    if (path === '/prediction-jobs' && method === 'POST') {
      return json({ job_id: 'job-1', status: 'queued', poll: '/prediction-jobs/job-1', prediction: null, error: null }, 202);
    }
    if (path.startsWith('/prediction-jobs/') && method === 'GET') {
      const view = state.jobs.length > 1 ? state.jobs.shift() : state.jobs[0];
      if (view?.status === 'succeeded' && view.prediction) state.predictions[view.prediction.ticker] = view.prediction;
      return json({ job_id: 'job-1', prediction: null, error: null, ...view });
    }
    if (path === '/oauth/me' && method === 'GET') {
      return state.user ? json({ user: state.user }) : json({ detail: 'Not signed in' }, 401);
    }
    return json({ detail: 'Not Found' }, 404);
  };
  vi.stubGlobal('fetch', vi.fn(handle));
  return state;
}

/** Requests the dashboard made, as "METHOD /path?query". */
export const requested = (state) => state.calls.map((c) => {
  const query = new URLSearchParams(c.query).toString();
  return `${c.method} ${c.path}${query ? `?${query}` : ''}`;
});
