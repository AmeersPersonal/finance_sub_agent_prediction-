// Mock data fetching. Each hook returns { data, status, refetch, isStale }
// where status is 'loading' | 'success' | 'empty' | 'error'.
// The `override` argument comes from the dev preview-state control.
// To connect a real API, replace the `make` function in each hook with a fetch call.
import { useState, useEffect, useEffectEvent, useCallback } from 'react';
import { seedQuotes, historyFor, newsData, forecastData, calendarData } from '../data/mockData.js';

export function useResource(make, key, override, emptyValue = null) {
  const [revision, setRevision] = useState(0);
  const request = `${key}|${revision}|${override}`;
  // A result belongs to the request that produced it; anything older reads as loading.
  const [state, setState] = useState({ request: null, data: null, status: 'loading' });

  const resolve = useEffectEvent(() => {
    if (override === 'error') return { data: null, status: 'error' };
    if (override === 'empty') return { data: emptyValue, status: 'empty' };
    return { data: make(), status: 'success' };
  });

  useEffect(() => {
    const timer = setTimeout(() => setState({ request, ...resolve() }), override === 'loading' ? 60000 : 170);
    return () => clearTimeout(timer);
  }, [request, override]);

  const current = state.request === request ? state : { data: null, status: 'loading' };
  const refetch = useCallback(() => setRevision((n) => n + 1), []);
  return { data: current.data, status: current.status, refetch, isStale: override === 'stale' || override === 'market_closed' };
}

export function useQuote(symbol, o) {
  return useResource(() => ({ ...seedQuotes[symbol], status: o === 'halted' ? 'halted' : seedQuotes[symbol].status }), symbol, o);
}

export function useHistory(symbol, tf, o) {
  return useResource(() => historyFor(symbol, tf), symbol + tf, o, []);
}

export function useNews(symbol, o) {
  return useResource(() => newsData, symbol, o, []);
}

export function useForecast(symbol, o) {
  return useResource(() => ({
    ...forecastData(symbol),
    status: o === 'insufficient_data' ? 'insufficient_data' : o === 'model_unavailable' ? 'model_unavailable' : forecastData(symbol).status,
  }), symbol, o);
}

export function useCalendar(symbol, o) {
  return useResource(() => calendarData, symbol, o, []);
}
