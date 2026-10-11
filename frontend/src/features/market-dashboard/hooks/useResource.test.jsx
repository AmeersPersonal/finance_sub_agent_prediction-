import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useForecast, useForecastJob, useHistory, useNews, useQuote, useResource } from './useResource.js';
import { tickValues } from '../lib/tickStore.js';
import { dailyBars, document, installFakeBackend, intradayBars, json, prediction, requested } from '../../../test/fakeBackend.js';

describe('useResource', () => {
  it('goes from loading to success', async () => {
    const { result } = renderHook(() => useResource(async () => ['a'], 'k', 'normal'));
    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current.status).toBe('success'));
    expect(result.current.data).toEqual(['a']);
  });

  it('treats an empty list or null as empty', async () => {
    const list = renderHook(() => useResource(async () => [], 'k', 'normal'));
    const none = renderHook(() => useResource(async () => null, 'k', 'normal'));
    await waitFor(() => expect(list.result.current.status).toBe('empty'));
    await waitFor(() => expect(none.result.current.status).toBe('empty'));
    expect(list.result.current.data).toBeNull();
  });

  it('keeps the error for the panel to show', async () => {
    const { result } = renderHook(() => useResource(async () => { throw new Error('backend down'); }, 'k', 'normal'));
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error.message).toBe('backend down');
  });

  it('refetches on demand', async () => {
    let n = 0;
    const { result } = renderHook(() => useResource(async () => [++n], 'k', 'normal'));
    await waitFor(() => expect(result.current.data).toEqual([1]));
    act(() => result.current.refetch());
    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current.data).toEqual([2]));
  });

  it('never shows an older key’s late answer, and aborts it', async () => {
    const signals = [];
    let release;
    const slow = new Promise((resolve) => { release = resolve; });
    const load = (key) => async (signal) => {
      signals.push(signal);
      if (key === 'old') { await slow; return ['old data']; }
      return ['new data'];
    };
    const { result, rerender } = renderHook(({ key }) => useResource(load(key), key, 'normal'), { initialProps: { key: 'old' } });
    rerender({ key: 'new' });
    await waitFor(() => expect(result.current.data).toEqual(['new data']));
    expect(signals[0].aborted).toBe(true);
    await act(async () => { release(); await slow; });
    expect(result.current.data).toEqual(['new data']);
  });

  it('applies the dev preview states without calling the backend', async () => {
    const load = vi.fn(async () => ['x']);
    const loading = renderHook(() => useResource(load, 'k', 'loading'));
    const error = renderHook(() => useResource(load, 'k', 'error'));
    const empty = renderHook(() => useResource(load, 'k', 'empty'));
    const stale = renderHook(() => useResource(load, 'k', 'stale'));
    await waitFor(() => expect(error.result.current.status).toBe('error'));
    await waitFor(() => expect(empty.result.current.status).toBe('empty'));
    await waitFor(() => expect(stale.result.current.isStale).toBe(true));
    expect(loading.result.current.status).toBe('loading');
    expect(load).toHaveBeenCalledTimes(1); // only the 'stale' preview loads
  });
});

describe('useQuote', () => {
  const quote = async (bars) => {
    const backend = installFakeBackend();
    backend.bars.NVDA = bars;
    const { result } = renderHook(() => useQuote('NVDA', 'normal'));
    await waitFor(() => expect(result.current.status).not.toBe('loading'));
    return result.current;
  };

  it('uses the latest 5-minute bar of the same session, against the previous day’s close', async () => {
    const q = await quote({ '1d': dailyBars([100, 110]), '5m': intradayBars([111], '2026-10-09T19:55:00Z') });
    expect(q.data).toMatchObject({ price: 111, previousClose: 100, asOf: '2026-10-09T19:55:00+00:00' });
    expect(q.asOf).toBe(q.data.asOf);
  });

  it('uses a 5-minute bar from a newer session than the last daily bar', async () => {
    const q = await quote({ '1d': dailyBars([100, 110]), '5m': intradayBars([120], '2026-10-12T14:00:00Z') });
    expect(q.data).toMatchObject({ price: 120, previousClose: 110 });
  });

  it('ignores 5-minute bars older than the last daily bar', async () => {
    const q = await quote({ '1d': dailyBars([100, 110]), '5m': intradayBars([90], '2026-10-07T14:00:00Z') });
    expect(q.data).toMatchObject({ price: 110, previousClose: 100 });
  });

  it('falls back to the open with a single daily bar', async () => {
    const q = await quote({ '1d': dailyBars([50]) });
    expect(q.data).toMatchObject({ price: 50, previousClose: 49 });
  });

  it('is empty when the ticker has no saved prices', async () => {
    expect((await quote({})).status).toBe('empty');
  });

  it('shares the price with every price cell', async () => {
    await quote({ '1d': dailyBars([100, 110]) });
    await waitFor(() => expect(tickValues.NVDA?.price).toBe(110));
  });

  it('marks the closed-market preview as stale', async () => {
    installFakeBackend().bars.NVDA = { '1d': dailyBars([1, 2]) };
    const { result } = renderHook(() => useQuote('NVDA', 'market_closed'));
    await waitFor(() => expect(result.current.status).toBe('success'));
    expect(result.current.isStale).toBe(true);
  });
});

describe('useHistory', () => {
  it.each([
    ['1D', '5m', '100'], ['1W', '5m', '400'], ['1M', '1d', '22'], ['1Y', '1d', '252'], ['5Y', '1d', '1260'],
  ])('%s asks for %s bars, limit %s', async (tf, interval, limit) => {
    const backend = installFakeBackend();
    const { result } = renderHook(() => useHistory('NVDA', tf, 'normal'));
    await waitFor(() => expect(result.current.status).toBe('empty'));
    expect(backend.calls[0].query).toEqual({ interval, limit });
  });

  it('maps bars to chart points, oldest first', async () => {
    installFakeBackend().bars.NVDA = { '1d': dailyBars([10, 11]) };
    const { result } = renderHook(() => useHistory('NVDA', '1M', 'normal'));
    await waitFor(() => expect(result.current.status).toBe('success'));
    expect(result.current.data).toEqual([
      { t: '2026-10-08T04:00:00+00:00', value: 10, open: 9, high: 11, low: 8, volume: 1000 },
      { t: '2026-10-09T04:00:00+00:00', value: 11, open: 10, high: 12, low: 9, volume: 1000 },
    ]);
  });

  it('shows only the last session on 1D, including bars after midnight UTC', async () => {
    installFakeBackend().bars.NVDA = {
      '5m': [...intradayBars([1, 2], '2026-10-08T19:50:00Z'), ...intradayBars([3, 4], '2026-10-09T19:55:00Z')],
    };
    const { result } = renderHook(() => useHistory('NVDA', '1D', 'normal'));
    await waitFor(() => expect(result.current.status).toBe('success'));
    expect(result.current.data.map((p) => p.value)).toEqual([3, 4]);
  });

  it('refetches when the timeframe, ticker or reload changes', async () => {
    const backend = installFakeBackend();
    const { rerender } = renderHook(({ s, tf, r }) => useHistory(s, tf, 'normal', r), { initialProps: { s: 'NVDA', tf: '1M', r: 0 } });
    await waitFor(() => expect(backend.calls).toHaveLength(1));
    rerender({ s: 'NVDA', tf: '1Y', r: 0 });
    rerender({ s: 'AAPL', tf: '1Y', r: 0 });
    rerender({ s: 'AAPL', tf: '1Y', r: 1 });
    await waitFor(() => expect(backend.calls).toHaveLength(4));
    expect(requested(backend).at(-1)).toBe('GET /stocks/AAPL/history?interval=1d&limit=252');
  });
});

describe('useNews', () => {
  it('maps documents, falling back to when we first saw an undated one', async () => {
    installFakeBackend().news.NVDA = [
      document(7, 'Dated', { classification: { role: 'company_info' } }),
      document(8, 'Undated', { published_at: null, classification: null }),
    ];
    const { result } = renderHook(() => useNews('NVDA', 'normal'));
    await waitFor(() => expect(result.current.status).toBe('success'));
    expect(result.current.data).toEqual([
      { id: '7', headline: 'Dated', source: 'Example News', url: 'https://news.example/7', excerpt: 'Dated excerpt',
        publishedAt: '2026-10-09T15:00:00+00:00', role: 'company_info', kind: 'news' },
      expect.objectContaining({ id: '8', publishedAt: '2026-10-10T01:00:00+00:00', role: 'other' }),
    ]);
  });
});

describe('useForecast', () => {
  it('succeeds with no forecast, so the panel can offer to run one', async () => {
    installFakeBackend();
    const { result } = renderHook(() => useForecast('NVDA', 'normal'));
    await waitFor(() => expect(result.current.status).toBe('success'));
    expect(result.current.data).toEqual({ prediction: null });
  });

  it('returns the latest forecast', async () => {
    installFakeBackend().predictions.NVDA = prediction();
    const { result } = renderHook(() => useForecast('NVDA', 'normal'));
    await waitFor(() => expect(result.current.data?.prediction?.id).toBe('p1'));
  });

  it('reports a backend failure', async () => {
    installFakeBackend().respond = () => json({ detail: 'Database unavailable. Check its connection and migrations.' }, 503);
    const { result } = renderHook(() => useForecast('NVDA', 'normal'));
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error.message).toMatch(/Database unavailable/);
  });
});

describe('useForecastJob', () => {
  const setup = (symbol = 'NVDA') => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    const backend = installFakeBackend();
    const onDone = vi.fn();
    const hook = renderHook(({ s }) => useForecastJob(s, onDone), { initialProps: { s: symbol } });
    return { backend, onDone, ...hook };
  };
  const poll = () => act(() => vi.advanceTimersByTimeAsync(3000));

  it('polls every 3 s until the forecast is saved, then reports done once', async () => {
    const { backend, onDone, result } = setup();
    backend.jobs = [{ status: 'running' }, { status: 'running' }, { status: 'succeeded', prediction: prediction() }];
    expect(result.current.status).toBe('idle');
    await act(async () => { result.current.start(); });
    expect(result.current.status).toBe('queued');
    expect(result.current.startedAt).toEqual(expect.any(Number));
    await poll();
    expect(result.current.status).toBe('running');
    await poll();
    await poll();
    expect(result.current.status).toBe('idle');
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(requested(backend)).toEqual([
      'POST /prediction-jobs', 'GET /prediction-jobs/job-1', 'GET /prediction-jobs/job-1', 'GET /prediction-jobs/job-1',
    ]);
  });

  it('shows a failed job’s detail, not the error object', async () => {
    const { backend, onDone, result } = setup();
    backend.jobs = [{ status: 'failed', error: { status_code: 502, detail: 'Market data provider unavailable.' } }];
    await act(async () => { result.current.start(); });
    await poll();
    expect(result.current).toMatchObject({ status: 'failed', error: 'Market data provider unavailable.' });
    expect(typeof result.current.error).toBe('string');
    expect(onDone).not.toHaveBeenCalled();
  });

  it('has a fallback message for a failed job without detail', async () => {
    const { backend, result } = setup();
    backend.jobs = [{ status: 'failed', error: null }];
    await act(async () => { result.current.start(); });
    await poll();
    expect(result.current.error).toBe('The forecast failed. Try again later.');
  });

  it.each([
    [429, { detail: 'Forecast limit reached (10 an hour). Try again in 12 min.' }, 'Forecast limit reached (10 an hour). Try again in 12 min.'],
    [401, { detail: 'Not signed in' }, 'Not signed in'],
    [503, { detail: 'GEMINI_API_KEY is not configured.' }, 'GEMINI_API_KEY is not configured.'],
  ])('reports a %i when starting', async (status, body, message) => {
    const { backend, result } = setup();
    backend.respond = (method, path) => (method === 'POST' && path === '/prediction-jobs' ? json(body, status) : null);
    await act(async () => { await result.current.start(); });
    expect(result.current).toMatchObject({ status: 'failed', error: message });
  });

  it('reports losing the backend while polling', async () => {
    const { backend, result } = setup();
    backend.jobs = [{ status: 'running' }];
    await act(async () => { result.current.start(); });
    backend.down = true;
    await poll();
    expect(result.current).toMatchObject({ status: 'failed', error: expect.stringContaining('Can’t reach the backend') });
  });

  it('stops polling when the ticker changes, and the new ticker starts idle', async () => {
    const { backend, onDone, result, rerender } = setup();
    backend.jobs = [{ status: 'running' }];
    await act(async () => { result.current.start(); });
    await poll();
    rerender({ s: 'AAPL' });
    expect(result.current.status).toBe('idle');
    const callsAfterSwitch = backend.calls.length;
    await poll();
    await poll();
    expect(backend.calls).toHaveLength(callsAfterSwitch);
    expect(onDone).not.toHaveBeenCalled();
  });

  it('stops polling when the dashboard unmounts', async () => {
    const { backend, result, unmount } = setup();
    backend.jobs = [{ status: 'running' }];
    await act(async () => { result.current.start(); });
    unmount();
    const calls = backend.calls.length;
    await act(() => vi.advanceTimersByTimeAsync(10000));
    expect(backend.calls).toHaveLength(calls);
  });
});
