// Data hooks backed by the API (lib/api.js). Each returns { data, status, refetch, isStale, asOf }
// where status is 'loading' | 'success' | 'empty' | 'error'. `override` comes from the
// dev preview-state control; `reload` is bumped after a data refresh to refetch everything.
import { useState, useEffect, useEffectEvent, useCallback, useRef } from 'react';
import { getBars, getNews, getLatestPrediction, startForecast, getJob } from '../lib/api.js';
import { sessionDate } from '../lib/assets.js';
import { publishTick } from '../lib/tickStore.js';

const isEmptyList = (d) => Array.isArray(d) && d.length === 0;

export function useResource(load, key, override, isEmpty = isEmptyList) {
  const [revision, setRevision] = useState(0);
  const request = `${key}|${revision}|${override}`;
  // A result belongs to the request that produced it; anything older reads as loading.
  const [state, setState] = useState({ request: null, data: null, status: 'loading', error: null });
  const run = useEffectEvent((signal) => load(signal));
  const empty = useEffectEvent((data) => isEmpty(data));

  useEffect(() => {
    if (override === 'loading') return undefined;
    const controller = new AbortController();
    Promise.resolve()
      .then(() => {
        if (override === 'error') throw new Error('Preview error');
        return override === 'empty' ? null : run(controller.signal);
      })
      .then((data) => {
        if (controller.signal.aborted) return;
        const none = data == null || empty(data);
        setState({ request, data: none ? null : data, status: none ? 'empty' : 'success', error: null });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setState({ request, data: null, status: 'error', error });
      });
    return () => controller.abort();
  }, [request, override]);

  const current = state.request === request ? state : { data: null, status: 'loading', error: null };
  const refetch = useCallback(() => setRevision((n) => n + 1), []);
  return { data: current.data, status: current.status, error: current.error, refetch, isStale: override === 'stale' };
}

/**
 * Quote: { symbol, price, previousClose, asOf } from the saved bars. The latest 5-minute bar
 * is fresher than the daily bar saved with it, so it sets the price when it's newer.
 */
export function useQuote(symbol, o, reload = 0) {
  const resource = useResource(async (signal) => {
    const [daily, intraday] = await Promise.all([getBars(symbol, '1d', 3, signal), getBars(symbol, '5m', 1, signal)]);
    if (!daily.length) return null;
    const lastDaily = daily.at(-1);
    const lastIntraday = intraday.at(-1);
    let price = lastDaily.close;
    let asOf = lastDaily.bar_at;
    let previousClose = daily.at(-2)?.close ?? lastDaily.open;
    if (lastIntraday) {
      const intradayDay = sessionDate(lastIntraday.bar_at);
      const dailyDay = sessionDate(lastDaily.bar_at);
      if (intradayDay >= dailyDay) {
        price = lastIntraday.close;
        asOf = lastIntraday.bar_at;
        if (intradayDay > dailyDay) previousClose = lastDaily.close;
      }
    }
    publishTick({ symbol, price, at: asOf });
    return { symbol, price, previousClose, asOf };
  }, `${symbol}|${reload}`, o);
  const stale = o === 'stale' || o === 'market_closed';
  return { ...resource, isStale: stale, asOf: resource.data?.asOf };
}

// Timeframe -> which saved bars to show. 5-minute bars cover the last few sessions.
const RANGES = {
  '1D': ['5m', 100], '1W': ['5m', 400], '1M': ['1d', 22], '1Y': ['1d', 252], '5Y': ['1d', 1260],
};

/** HistoryPoint: { t, value, open, high, low, volume }, oldest first. */
export function useHistory(symbol, tf, o, reload = 0) {
  return useResource(async (signal) => {
    const [interval, limit] = RANGES[tf] || RANGES['1M'];
    let bars = await getBars(symbol, interval, limit, signal);
    if (tf === '1D' && bars.length) {
      const last = sessionDate(bars.at(-1).bar_at);
      bars = bars.filter((b) => sessionDate(b.bar_at) === last);
    }
    return bars.map((b) => ({ t: b.bar_at, value: b.close, open: b.open, high: b.high, low: b.low, volume: b.volume }));
  }, `${symbol}|${tf}|${reload}`, o);
}

/** NewsItem: { id, headline, source, url, excerpt, publishedAt, role, kind } */
export function useNews(symbol, o, reload = 0) {
  return useResource(async (signal) => (await getNews(symbol, 40, signal)).map((d) => ({
    id: String(d.id),
    headline: d.title,
    source: d.source_name,
    url: d.source_url,
    excerpt: d.excerpt,
    publishedAt: d.published_at || d.first_seen_at,
    role: d.classification?.role || 'other',
    kind: d.document_type,
  })), `${symbol}|${reload}`, o);
}

/** { prediction }: the latest saved forecast (backend `Prediction`), or null before the first one. */
export function useForecast(symbol, o, reload = 0) {
  return useResource(
    async (signal) => ({ prediction: await getLatestPrediction(symbol, signal) }),
    `${symbol}|${reload}`, o, () => false,
  );
}

const POLL_MS = 3000;

/**
 * Runs a background forecast and polls it. `run.status`: idle | starting | queued | running | failed.
 * Calls `onDone` once the forecast is saved. Leaving the ticker stops polling; the backend
 * still finishes and saves the forecast.
 */
export function useForecastJob(symbol, onDone) {
  const [job, setJob] = useState({ symbol, status: 'idle', error: null, startedAt: null });
  const active = useRef(null);
  const onDoneRef = useRef(onDone);
  useEffect(() => { onDoneRef.current = onDone; });

  useEffect(() => () => { active.current?.abort(); active.current = null; }, [symbol]);

  const start = useCallback(async (horizonDays = 5) => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const startedAt = Date.now();
    setJob({ symbol, status: 'starting', error: null, startedAt });
    try {
      let view = await startForecast(symbol, horizonDays);
      while (!controller.signal.aborted && (view.status === 'queued' || view.status === 'running')) {
        setJob({ symbol, status: view.status, error: null, startedAt });
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        if (controller.signal.aborted) return;
        view = await getJob(view.job_id, controller.signal);
      }
      if (controller.signal.aborted) return;
      if (view.status === 'succeeded') {
        setJob({ symbol, status: 'idle', error: null, startedAt: null });
        onDoneRef.current();
      } else {
        setJob({ symbol, status: 'failed', error: view.error || 'The forecast failed.', startedAt });
      }
    } catch (error) {
      if (error.name !== 'AbortError') setJob({ symbol, status: 'failed', error: error.message, startedAt });
    }
  }, [symbol]);

  // A job started for another ticker doesn't belong to this one.
  return { ...(job.symbol === symbol ? job : { status: 'idle', error: null, startedAt: null }), start };
}
