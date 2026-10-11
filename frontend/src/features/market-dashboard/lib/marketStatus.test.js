import { afterEach, describe, expect, it, vi } from 'vitest';
import { marketStatus } from './marketStatus.js';

const stock = { symbol: 'NVDA', type: 'Stock' };
const at = (iso) => vi.useFakeTimers({ now: new Date(iso), toFake: ['Date'] });

afterEach(() => vi.useRealTimers());

describe('marketStatus (New York time)', () => {
  it.each([
    ['2026-10-12T07:30:00Z', 'closed'], // 3:30 AM Monday
    ['2026-10-12T12:00:00Z', 'pre-market'], // 8:00 AM
    ['2026-10-12T13:30:00Z', 'open'], // 9:30 AM
    ['2026-10-12T19:59:00Z', 'open'], // 3:59 PM
    ['2026-10-12T20:00:00Z', 'after-hours'], // 4:00 PM
    ['2026-10-13T00:30:00Z', 'closed'], // 8:30 PM
  ])('%s is %s', (iso, expected) => {
    at(iso);
    expect(marketStatus(stock, null, 'normal')).toBe(expected);
  });

  it('calls weekends the weekend, not a holiday', () => {
    at('2026-10-10T15:00:00Z'); // Saturday
    expect(marketStatus(stock, null, 'normal')).toBe('weekend');
    at('2026-10-11T15:00:00Z'); // Sunday
    expect(marketStatus(stock, null, 'normal')).toBe('weekend');
  });

  it('knows fixed holidays and half days', () => {
    at('2025-12-25T15:00:00Z'); // Thursday
    expect(marketStatus(stock, null, 'normal')).toBe('holiday');
    at('2026-11-27T15:00:00Z'); // Friday after Thanksgiving, 10 AM
    expect(marketStatus(stock, null, 'normal')).toBe('half-day');
  });

  it('applies the preview overrides', () => {
    at('2026-10-12T15:00:00Z');
    expect(marketStatus(stock, null, 'market_closed')).toBe('closed');
    expect(marketStatus(stock, null, 'halted')).toBe('halted');
    expect(marketStatus({ symbol: 'SPY', type: 'ETF' }, null, 'halted')).toBe('open');
  });
});
