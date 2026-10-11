// Tickers offered in search. Any other US ticker can be typed in; the backend
// fetches its data on "Refresh data".

/** Asset: { symbol, name, type: 'Stock'|'ETF', sector } */
export const assets = [
  { symbol: 'NVDA', name: 'Nvidia', type: 'Stock', sector: 'Semiconductors' },
  { symbol: 'AAPL', name: 'Apple', type: 'Stock', sector: 'Technology' },
  { symbol: 'MSFT', name: 'Microsoft', type: 'Stock', sector: 'Technology' },
  { symbol: 'AMZN', name: 'Amazon', type: 'Stock', sector: 'Consumer and cloud' },
  { symbol: 'GOOGL', name: 'Alphabet', type: 'Stock', sector: 'Technology' },
  { symbol: 'META', name: 'Meta Platforms', type: 'Stock', sector: 'Technology' },
  { symbol: 'TSLA', name: 'Tesla', type: 'Stock', sector: 'Automakers' },
  { symbol: 'AMD', name: 'AMD', type: 'Stock', sector: 'Semiconductors' },
  { symbol: 'SPY', name: 'SPDR S&P 500 ETF', type: 'ETF', sector: 'Broad market' },
  { symbol: 'QQQ', name: 'Invesco QQQ Trust', type: 'ETF', sector: 'Technology' },
  { symbol: 'DIA', name: 'SPDR Dow Jones ETF', type: 'ETF', sector: 'Broad market' },
];

// Same rule as the API's ticker check (database.service.normalize_ticker), so a ticker
// accepted here is never a 422 there; backend/src/tests/test_frontend_contract.py compares them.
export const TICKER_PATTERN = /^[A-Z0-9^][A-Z0-9.^=-]{0,14}$/;

export function assetFor(symbol) {
  return assets.find((a) => a.symbol === symbol)
    || { symbol, name: symbol, type: symbol.startsWith('^') ? 'Index' : 'Stock', sector: '' };
}

/** The New York calendar date (YYYY-MM-DD) of an ISO timestamp: the trading session it belongs to. */
export const sessionDate = (iso) => new Intl.DateTimeFormat('en-CA', {
  timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date(iso));
