import { describe, expect, it } from 'vitest';
import { assetFor, assets, sessionDate, TICKER_PATTERN } from './assets.js';

describe('tickers', () => {
  it.each(['AAPL', 'BRK.B', '^GSPC', 'BTC-USD', 'ES=F', 'A', 'X'.repeat(15)])('accepts %s like the backend does', (t) => {
    expect(TICKER_PATTERN.test(t)).toBe(true);
  });

  it.each(['', 'aapl', 'AAPL MSFT', '<script>', '../etc', '.AAPL', 'X'.repeat(16), 'AAPL/'])('rejects %j', (t) => {
    expect(TICKER_PATTERN.test(t)).toBe(false);
  });

  it('describes listed tickers and falls back for others', () => {
    expect(assetFor('NVDA')).toMatchObject({ name: 'Nvidia', type: 'Stock' });
    expect(assetFor('SPY').type).toBe('ETF');
    expect(assetFor('COST')).toEqual({ symbol: 'COST', name: 'COST', type: 'Stock', sector: '' });
    expect(assetFor('^GSPC').type).toBe('Index');
  });

  it('lists every ticker once, all valid', () => {
    const symbols = assets.map((a) => a.symbol);
    expect(new Set(symbols).size).toBe(symbols.length);
    expect(symbols.every((s) => TICKER_PATTERN.test(s))).toBe(true);
  });
});

describe('sessionDate', () => {
  it('uses the New York date, not UTC or the viewer’s', () => {
    expect(sessionDate('2026-10-09T04:00:00+00:00')).toBe('2026-10-09'); // daily bar: NY midnight
    expect(sessionDate('2026-10-10T01:30:00Z')).toBe('2026-10-09'); // 9:30 PM New York
    expect(sessionDate('2026-10-09T03:59:00Z')).toBe('2026-10-08');
  });

  it('follows daylight saving changes', () => {
    expect(sessionDate('2026-01-15T04:30:00Z')).toBe('2026-01-14'); // EST: 11:30 PM the day before
    expect(sessionDate('2026-07-15T04:30:00Z')).toBe('2026-07-15'); // EDT: 12:30 AM
  });
});
