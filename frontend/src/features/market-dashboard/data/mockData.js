// Illustrative mock data. Replace these with real API calls when wiring up a backend
// (see src/hooks/useResource.js for where each data set is loaded).
import { LAST_CLOSE } from '../constants/options.js';

/**
 * Asset: { symbol, name, type: 'Stock'|'ETF'|'Crypto'|'Index', sector, marketCap }
 */
export const assets = [
  { symbol: 'AAPL', name: 'Apple', type: 'Stock', sector: 'Technology', marketCap: 3200000000000 },
  { symbol: 'NVDA', name: 'Nvidia', type: 'Stock', sector: 'Semiconductors', marketCap: 2900000000000 },
  { symbol: 'KO', name: 'Coca-Cola', type: 'Stock', sector: 'Consumer goods', marketCap: 285000000000 },
  { symbol: 'VOO', name: 'Vanguard S&P 500 ETF', type: 'ETF', sector: 'Broad market', marketCap: 1250000000000 },
  { symbol: 'QQQ', name: 'Invesco QQQ Trust', type: 'ETF', sector: 'Technology', marketCap: 340000000000 },
  { symbol: 'BTC', name: 'Bitcoin', type: 'Crypto', sector: 'Crypto', marketCap: 1350000000000 },
  { symbol: 'ETH', name: 'Ethereum', type: 'Crypto', sector: 'Crypto', marketCap: 370000000000 },
  { symbol: 'OTLK', name: 'Outlook Therapeutics · small-cap', type: 'Stock', sector: 'Biotechnology', marketCap: 64000000 },
  { symbol: 'SPX', name: 'S&P 500', type: 'Index', sector: 'Broad market', marketCap: 48000000000000 },
  { symbol: 'DJI', name: 'Dow Jones', type: 'Index', sector: 'Broad market', marketCap: 16000000000000 },
];

/** symbol -> [current price, previous close] */
export const base = {
  AAPL: [227.85, 232.12], NVDA: [871.34, 908.61], KO: [66.82, 66.15], VOO: [549.16, 553.01],
  QQQ: [487.43, 495.20], BTC: [68472.128451, 67291.28], ETH: [3142.276841, 3101.15],
  OTLK: [0.842731, 0.204546], SPX: [5762.44, 5790.14], DJI: [42680.52, 42801.20],
};

/**
 * Quote: { symbol, price, previousClose, asOf, status, lastClose }
 * status: 'open'|'closed'|'pre-market'|'after-hours'|'holiday'|'half-day'|'halted'
 */
export const seedQuotes = Object.fromEntries(assets.map((a) => [a.symbol, {
  symbol: a.symbol,
  price: base[a.symbol][0],
  previousClose: base[a.symbol][1],
  asOf: new Date().toISOString(),
  status: a.type === 'Crypto' ? 'open' : 'closed',
  lastClose: LAST_CLOSE,
}]));

/**
 * MarketEvent: { id, symbol, t, category, change, explanation }
 * category: 'Earnings'|'Interest rates'|'Company news'|'Sector-wide'|'Economy data'|'Crypto-specific'
 */
export const events = [
  { id: 'n1', symbol: 'NVDA', t: '2026-03-04', category: 'Company news', change: -4.1, explanation: 'Investors worried that large technology companies may slow spending on AI chips.' },
  { id: 'n2', symbol: 'NVDA', t: '2026-05-28', category: 'Earnings', change: 5.2, explanation: 'Quarterly sales beat expectations as demand for AI equipment remained strong.' },
  { id: 'n3', symbol: 'NVDA', t: '2026-07-16', category: 'Sector-wide', change: -3.3, explanation: 'Chipmakers fell together after new export restrictions were discussed.' },
  { id: 'a1', symbol: 'AAPL', t: '2026-09-10', category: 'Company news', change: -1.8, explanation: 'Investors weighed a new phone launch against concerns about upgrade demand.' },
  { id: 'v1', symbol: 'VOO', t: '2026-08-12', category: 'Economy data', change: 1.2, explanation: 'Slower inflation raised hopes that borrowing costs could ease.' },
  { id: 'q1', symbol: 'QQQ', t: '2026-09-17', category: 'Interest rates', change: -2.1, explanation: 'A change in rate expectations weighed on growth-focused funds.' },
  { id: 'b1', symbol: 'BTC', t: '2026-10-06', category: 'Crypto-specific', change: 3.1, explanation: 'Digital-asset prices rose as demand for spot bitcoin funds increased.' },
  { id: 'e1', symbol: 'ETH', t: '2026-10-07', category: 'Crypto-specific', change: -2.0, explanation: 'Network activity cooled and traders reduced exposure to digital assets.' },
  { id: 'k1', symbol: 'KO', t: '2026-07-22', category: 'Earnings', change: 1.1, explanation: 'Steady beverage sales helped offset higher distribution costs.' },
  { id: 'o1', symbol: 'OTLK', t: '2026-09-29', category: 'Company news', change: 12.4, explanation: 'A small clinical update moved this thinly traded stock sharply.' },
];

/**
 * NewsItem: { id, headline, source, publishedAt, tickers[], category, sentiment, eventId? }
 * category: 'asset'|'economy'|'crypto'|'sector'; sentiment: 'Positive'|'Negative'|'Mixed'
 */
export const newsData = [
  { id: '1', headline: 'Nvidia shares slip as investors question the pace of future AI-chip spending', source: 'Market Desk', publishedAt: '2026-10-10T15:40:00Z', tickers: ['NVDA', 'QQQ'], category: 'asset', sentiment: 'Negative', eventId: 'n1' },
  { id: '2', headline: 'Inflation report puts the next Federal Reserve decision in focus', source: 'Economy Wire', publishedAt: '2026-10-10T13:20:00Z', tickers: ['VOO', 'QQQ'], category: 'economy', sentiment: 'Mixed', eventId: 'v1' },
  { id: '3', headline: 'Bitcoin gains as digital-asset fund inflows pick up', source: 'Digital Markets', publishedAt: '2026-10-10T11:05:00Z', tickers: ['BTC', 'ETH'], category: 'crypto', sentiment: 'Positive', eventId: 'b1' },
  { id: '4', headline: 'Apple investors weigh new device demand after product launch', source: 'Market Desk', publishedAt: '2026-10-09T18:00:00Z', tickers: ['AAPL'], category: 'asset', sentiment: 'Mixed', eventId: 'a1' },
  { id: '5', headline: 'Beverage makers hold steady as households adjust spending', source: 'Consumer Brief', publishedAt: '2026-10-09T14:00:00Z', tickers: ['KO'], category: 'sector', sentiment: 'Mixed', eventId: 'k1' },
  { id: '6', headline: 'Chip stocks retreat together on renewed export-policy questions', source: 'Sector Watch', publishedAt: '2026-10-08T16:00:00Z', tickers: ['NVDA', 'QQQ'], category: 'sector', sentiment: 'Negative', eventId: 'n3' },
];

/** CalendarEvent: { id, title, time, reason, symbol? } */
export const calendarData = [
  { id: 'c1', title: 'US consumer inflation (CPI)', time: '2026-10-13T12:30:00Z', reason: 'Inflation can change expectations for interest rates.' },
  { id: 'c2', title: 'Federal Reserve decision', time: '2026-10-28T18:00:00Z', reason: 'Interest-rate decisions affect borrowing costs and share valuations.' },
  { id: 'c3', title: 'US jobs report', time: '2026-11-06T13:30:00Z', reason: 'Hiring gives clues about the strength of the economy.' },
  { id: 'c4', title: 'Apple earnings', time: '2026-10-29T20:30:00Z', reason: 'Results can reset expectations for Apple and its suppliers.', symbol: 'AAPL' },
  { id: 'c5', title: 'Nvidia earnings', time: '2026-11-18T21:30:00Z', reason: 'AI-chip sales may move Nvidia and related technology shares.', symbol: 'NVDA' },
];

/**
 * Forecast contract:
 * { symbol, horizon: '1W'|'1M'|'3M', generatedAt, points: [{ t, mid, low, high }],
 *   confidence: 'low'|'medium'|'high', topFactors: [{ label, direction: 'up'|'down', weight }],
 *   status: 'ok'|'insufficient_data'|'model_unavailable', pastAccuracy?: { horizon, hitRate } }
 */
export const forecastData = (symbol) => ({
  symbol,
  horizon: '1M',
  generatedAt: new Date().toISOString(),
  status: symbol === 'OTLK' ? 'insufficient_data' : 'ok',
  confidence: 'low',
  points: [1, 2, 3, 4].map((n) => ({
    t: `Week ${n}`,
    mid: base[symbol][0] * (1 + n * 0.004),
    low: base[symbol][0] * (1 - n * 0.035),
    high: base[symbol][0] * (1 + n * 0.04),
  })),
  topFactors: [
    { label: 'Recent price swings', direction: 'down', weight: 0.41 },
    { label: 'Company and sector news', direction: 'down', weight: 0.34 },
    { label: 'Broader market demand', direction: 'up', weight: 0.25 },
  ],
  pastAccuracy: { horizon: '1-month', hitRate: 58 },
});

/** HistoryPoint: { t, value } — synthetic price curve ending at the current price. */
export const historyFor = (symbol, timeframe) => {
  const counts = { '1D': 32, '1W': 36, '1M': 40, '1Y': 52, '5Y': 260 };
  const span = { '1D': 86400000, '1W': 604800000, '1M': 2592000000, '1Y': 31536000000, '5Y': 157680000000 };
  const count = counts[timeframe] || 40;
  const end = new Date(LAST_CLOSE).getTime();
  return Array.from({ length: count }, (_, i) => {
    const phase = i / (count - 1);
    const target = base[symbol][0];
    return {
      t: new Date(end - span[timeframe] * (1 - phase)).toISOString(),
      value: target * (1 + 0.065 * (1 - phase) + 0.023 * Math.sin(i * 0.75 + symbol.length) - 0.009 * Math.cos(i * 0.28)),
    };
  });
};
