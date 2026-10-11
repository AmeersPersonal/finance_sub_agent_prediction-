import { describe, expect, it } from 'vitest';
import { biggestMoves } from './moves.js';

const points = (values, start = '2026-10-05') =>
  values.map((value, i) => ({ t: `${start.slice(0, 8)}${String(Number(start.slice(8)) + i).padStart(2, '0')}T04:00:00+00:00`, value }));

describe('biggestMoves', () => {
  it('needs at least two points', () => {
    expect(biggestMoves(null, [])).toEqual([]);
    expect(biggestMoves([], [])).toEqual([]);
    expect(biggestMoves(points([100]), [])).toEqual([]);
  });

  it('returns the three largest moves by size, largest first, with their sign', () => {
    // Day-to-day changes: +1%, -5%, +2%, +10%, -0.5%
    const moves = biggestMoves(points([100, 101, 95.95, 97.869, 107.6559, 107.117]), []);
    expect(moves.map((m) => Math.round(m.change * 10) / 10)).toEqual([10, -5, 2]);
    expect(moves[0].t).toBe('2026-10-09T04:00:00+00:00');
    expect(moves.every((m) => m.id === `move-${m.t}`)).toBe(true);
  });

  it('honours a different count and handles fewer moves than asked', () => {
    expect(biggestMoves(points([100, 110, 99]), [], 1)).toHaveLength(1);
    expect(biggestMoves(points([100, 110]), [], 3)).toHaveLength(1);
  });

  it('skips a zero previous price instead of producing Infinity', () => {
    const moves = biggestMoves(points([0, 5, 6]), []);
    expect(moves).toHaveLength(1);
    expect(Number.isFinite(moves[0].change)).toBe(true);
  });

  it('pairs each move with headlines from the same New York trading session', () => {
    const moves = biggestMoves(points([100, 110]), [
      { headline: 'Same session, 10 PM New York (next day in UTC)', publishedAt: '2026-10-07T02:00:00Z' },
      { headline: 'Same session, morning', publishedAt: '2026-10-06T13:00:00Z' },
      { headline: 'Next session', publishedAt: '2026-10-07T13:00:00Z' },
      { headline: 'No date' },
    ]);
    expect(moves[0].headlines.map((h) => h.headline)).toEqual([
      'Same session, 10 PM New York (next day in UTC)', 'Same session, morning',
    ]);
  });

  it('works without news', () => {
    expect(biggestMoves(points([100, 90]), null)[0].headlines).toEqual([]);
  });
});
