import { describe, expect, it, vi } from 'vitest';
import { ApiError, detailText, getBars, getJob, getLatestPrediction, getNews, refreshTicker, startForecast } from './api.js';
import { installFakeBackend, json } from '../../../test/fakeBackend.js';

describe('requests', () => {
  it('reads saved bars through the /api proxy, with the cookie, oldest first as sent', async () => {
    const backend = installFakeBackend();
    backend.bars.NVDA = { '1d': [{ bar_at: 'a', close: 1 }, { bar_at: 'b', close: 2 }, { bar_at: 'c', close: 3 }] };
    expect(await getBars('NVDA', '1d', 2)).toEqual([{ bar_at: 'b', close: 2 }, { bar_at: 'c', close: 3 }]);
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe('/api/stocks/NVDA/history?interval=1d&limit=2');
    expect(init).toMatchObject({ method: 'GET', credentials: 'include' });
    expect(init.body).toBeUndefined();
  });

  it('escapes tickers with special characters', async () => {
    installFakeBackend();
    await getBars('^GSPC', '1d', 1);
    await getNews('BRK.B', 5);
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      '/api/stocks/%5EGSPC/history?interval=1d&limit=1',
      '/api/stocks/BRK.B/news?limit=5',
    ]);
  });

  it('returns null when a ticker has no saved forecast, and the newest one otherwise', async () => {
    const backend = installFakeBackend();
    expect(await getLatestPrediction('AAPL')).toBeNull();
    backend.predictions.AAPL = { id: 'p9', ticker: 'AAPL' };
    expect(await getLatestPrediction('AAPL')).toEqual({ id: 'p9', ticker: 'AAPL' });
    expect(fetch.mock.calls[0][0]).toBe('/api/predictions?ticker=AAPL&limit=1');
  });

  it('starts forecasts with the body the API expects (one default mode, five days)', async () => {
    installFakeBackend();
    const job = await startForecast('MSFT');
    expect(job).toMatchObject({ job_id: 'job-1', status: 'queued' });
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe('/api/prediction-jobs');
    expect(init.method).toBe('POST');
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' });
    expect(JSON.parse(init.body)).toEqual({ ticker: 'MSFT', horizon_days: 5, modes: 'default' });
  });

  it('refreshes with a POST and polls jobs by id', async () => {
    const backend = installFakeBackend();
    backend.jobs = [{ status: 'running' }];
    await refreshTicker('COST');
    expect(await getJob('job/1')).toMatchObject({ status: 'running' });
    expect(fetch.mock.calls.map(([url, init]) => `${init.method} ${url}`)).toEqual([
      'POST /api/stocks/COST/refresh', 'GET /api/prediction-jobs/job%2F1',
    ]);
  });

  it('uses VITE_API_BASE instead of the proxy when it is set', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://api.example:8000/');
    vi.resetModules();
    const fresh = await import('./api.js');
    installFakeBackend();
    await fresh.getNews('AAPL', 1);
    expect(fetch.mock.calls[0][0]).toBe('http://api.example:8000/stocks/AAPL/news?limit=1');
  });
});

describe('errors', () => {
  const failWith = (response) => {
    const backend = installFakeBackend();
    backend.respond = () => response;
  };

  it('shows the backend detail message', async () => {
    failWith(json({ detail: 'Unknown ticker ZZZZ.' }, 422));
    const error = await getBars('ZZZZ', '1d', 1).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, message: 'Unknown ticker ZZZZ.' });
  });

  it('joins validation errors', async () => {
    failWith(json({ detail: [{ loc: ['query', 'limit'], msg: 'Input should be less than 2000' }, { msg: 'bad interval' }] }, 422));
    await expect(getBars('NVDA', '1d', 5000)).rejects.toThrow('Input should be less than 2000; bad interval');
  });

  it('keeps Retry-After from a 429', async () => {
    failWith(json({ detail: 'Forecast limit reached (10 an hour). Try again in 5 min.' }, 429, { 'Retry-After': '300' }));
    const error = await startForecast('NVDA').catch((e) => e);
    expect(error).toMatchObject({ status: 429, retryAfter: 300, message: expect.stringContaining('Forecast limit') });
  });

  it.each([502, 503, 504])('explains a %i without a detail', async (status) => {
    failWith(new Response('<html>Bad gateway</html>', { status }));
    await expect(getNews('NVDA', 1)).rejects.toThrow('The backend is unavailable right now');
  });

  it('falls back to the status for other bodies it can’t read', async () => {
    failWith(new Response('', { status: 404 }));
    await expect(getNews('NVDA', 1)).rejects.toThrow('Request failed (404).');
  });

  it('says the backend is unreachable when the connection fails', async () => {
    installFakeBackend().down = true;
    const error = await getBars('NVDA', '1d', 1).catch((e) => e);
    expect(error).toMatchObject({ status: 0, message: expect.stringContaining('port 8000') });
  });

  it('lets an aborted request stay an AbortError', async () => {
    const backend = installFakeBackend();
    backend.respond = () => { throw new DOMException('aborted', 'AbortError'); };
    await expect(getBars('NVDA', '1d', 1)).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('formats a failed job’s error the same way', () => {
    expect(detailText('No eligible personas.', 422)).toBe('No eligible personas.');
    expect(detailText(undefined, 503)).toMatch(/unavailable/);
  });
});
