// The largest moves in the shown price history, each paired with any saved
// headlines published in the same New York trading session.
import { sessionDate } from './assets.js';

/** Move: { id, t, change (percent vs the previous point), headlines: NewsItem[] }, largest first. */
export function biggestMoves(points, news, count = 3) {
  if (!points || points.length < 2) return [];
  const moves = [];
  for (let i = 1; i < points.length; i += 1) {
    const previous = points[i - 1].value;
    if (previous) moves.push({ t: points[i].t, change: ((points[i].value - previous) / previous) * 100 });
  }
  return moves
    .sort((a, b) => Math.abs(b.change) - Math.abs(a.change))
    .slice(0, count)
    .map(({ t, change }) => {
      const day = sessionDate(t);
      const headlines = (news || []).filter((n) => n.publishedAt && sessionDate(n.publishedAt) === day);
      return { id: `move-${t}`, t, change, headlines };
    });
}
