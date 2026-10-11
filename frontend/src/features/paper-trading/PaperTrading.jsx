// Paper trading: simulated buys and sells with virtual cash, filled at the latest saved
// daily close. Educational only: no real money, no brokerage, not financial advice.
import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import * as api from './api.js';

const TICKER = /^[A-Z0-9^][A-Z0-9.^=-]{0,14}$/;
const usd = (n) => (n == null ? '—' : Number(n).toLocaleString('en-US', { style: 'currency', currency: 'USD' }));
const signedUsd = (n) => (n == null ? '—' : `${n > 0 ? '+' : ''}${usd(n)}`);
const count = (n) => Number(n).toLocaleString('en-US', { maximumFractionDigits: 6 });
const day = (iso) => (iso ? new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—');
const tone = (n) => (n > 0 ? 'text-emerald-700' : n < 0 ? 'text-red-700' : '');
const DIRECTIONS = { up: 'up', down: 'down', flat: 'flat', unclear: 'unclear' };

export default function PaperTrading() {
  const [params] = useSearchParams();
  const forecastId = params.get('prediction_id');
  const forecastSymbol = (params.get('symbol') ?? '').toUpperCase();

  const [account, setAccount] = useState(null);
  const [orders, setOrders] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [loading, setLoading] = useState(true);

  const [ticker, setTicker] = useState(TICKER.test(forecastSymbol) ? forecastSymbol : 'NVDA');
  const [side, setSide] = useState('buy');
  const [mode, setMode] = useState('dollars');
  const [amount, setAmount] = useState('');
  const [quote, setQuote] = useState({ state: 'idle' });
  const [message, setMessage] = useState(null);
  const [needsPrices, setNeedsPrices] = useState(false);
  const [busy, setBusy] = useState(false);
  const [orderKey, setOrderKey] = useState(null); // one idempotency key per ticket, so a retry can't trade twice

  // Account and order history load on mount and again whenever `load()` bumps the counter.
  const [reloads, setReloads] = useState(0);
  const load = () => setReloads((n) => n + 1);
  useEffect(() => {
    let current = true;
    Promise.all([api.getAccount(), api.getOrders()])
      .then(([summary, history]) => {
        if (!current) return;
        setAccount(summary);
        setOrders(history.orders);
        setLoadError(null);
      })
      .catch((error) => { if (current) setLoadError(error); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [reloads]);

  // Latest saved close for the ticker in the ticket, after a short pause in typing.
  const [quoteVersion, setQuoteVersion] = useState(0);
  useEffect(() => {
    if (!TICKER.test(ticker)) return undefined;
    let current = true;
    const timer = setTimeout(async () => {
      setQuote({ state: 'loading' });
      try {
        const bar = await api.getLatestBar(ticker);
        if (current) setQuote(bar ? { state: 'ready', ...bar } : { state: 'missing' });
      } catch (error) {
        if (current) setQuote({ state: 'error', message: error.message });
      }
    }, 350);
    return () => { current = false; clearTimeout(timer); };
  }, [ticker, quoteVersion]);

  const ticketChanged = () => { setOrderKey(null); setMessage(null); setNeedsPrices(false); };
  const holding = account?.positions.find((p) => p.symbol === ticker);
  const validTicker = TICKER.test(ticker);
  const price = quote.state === 'ready' && validTicker ? quote.price : null;
  const value = Number(amount);
  const estimate = price && value > 0
    ? (mode === 'shares' ? { shares: value, total: value * price } : { shares: value / price, total: value })
    : null;

  const choose = (nextSide, symbol, nextAmount = '') => {
    ticketChanged();
    setSide(nextSide);
    if (symbol) setTicker(symbol);
    setMode(nextSide === 'sell' ? 'shares' : mode);
    setAmount(nextAmount);
  };

  const sellFraction = (fraction) => {
    if (!holding) return;
    ticketChanged();
    setMode('shares');
    const shares = fraction === 1 ? holding.shares : Math.floor(holding.shares * fraction * 1e6) / 1e6;
    setAmount(String(shares));
  };

  async function submit(event) {
    event.preventDefault();
    if (!validTicker) return setMessage({ kind: 'error', text: 'Enter a ticker such as AAPL.' });
    if (!(value > 0)) return setMessage({ kind: 'error', text: 'Enter an amount above zero.' });
    const key = orderKey ?? crypto.randomUUID();
    setOrderKey(key);
    const order = { ticker, side, idempotency_key: key, [mode]: value };
    if (forecastId && ticker === forecastSymbol) order.prediction_id = forecastId;
    setBusy(true);
    try {
      const result = await api.placeOrder(order);
      setOrderKey(null);
      setAccount({ account: result.account, positions: result.positions });
      const { order: filled } = result;
      setMessage({
        kind: 'ok',
        text: `${filled.side === 'buy' ? 'Bought' : 'Sold'} ${count(filled.shares)} ${filled.symbol} at ${usd(filled.price)} `
          + `(${usd(filled.total)}, last saved close ${day(filled.price_as_of)}).`,
      });
      setAmount('');
      load();
    } catch (error) {
      if (error.status === 401) setLoadError(error);
      setNeedsPrices(/saved price|too old/i.test(error.message));
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setBusy(false);
    }
  }

  async function fetchPrices() {
    setBusy(true);
    setMessage({ kind: 'ok', text: `Fetching prices for ${ticker}…` });
    try {
      await api.refreshPrices(ticker);
      setNeedsPrices(false);
      setMessage({ kind: 'ok', text: `Prices for ${ticker} are up to date. Try the order again.` });
      setQuoteVersion((n) => n + 1);
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!window.confirm('Reset to $100,000 of virtual cash and clear all holdings and history?')) return;
    setBusy(true);
    try {
      await api.resetAccount();
      setOrderKey(null);
      setMessage({ kind: 'ok', text: 'Account reset.' });
      load();
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setBusy(false);
    }
  }

  const summary = account?.account;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center justify-between gap-4 flex-wrap">
          <h1 className="text-xl font-bold">Paper trading</h1>
          <Link to="/dashboard" className="text-sm font-semibold underline">← Back to the dashboard</Link>
        </div>
        <p role="note" className="bg-amber-100 text-amber-900 text-sm px-4 py-2 text-center">
          Simulated trading with virtual cash. No real money moves, and this is not financial advice.
          Orders fill at the latest saved daily close, not a live quote.
        </p>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-6 space-y-6">
        {loading && <p>Loading your practice account…</p>}

        {loadError?.status === 401 && (
          <section className="bg-white border border-slate-200 rounded-lg p-6">
            <h2 className="font-semibold text-lg">Sign in to practice</h2>
            <p className="mt-1 text-slate-700">Your virtual account is tied to your sign-in so it is there next time.</p>
            <a href={api.loginUrl} className="inline-block mt-3 px-4 py-2 rounded bg-slate-900 text-white font-semibold">Sign in with Google</a>
          </section>
        )}
        {loadError && loadError.status !== 401 && (
          <p role="alert" className="bg-red-50 border border-red-200 text-red-900 rounded p-3">{loadError.message}</p>
        )}

        {summary && (
          <section aria-label="Account summary" className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat label="Equity" value={usd(summary.equity)} />
            <Stat label="Cash" value={usd(summary.cash)} />
            <Stat label="Holdings" value={usd(summary.market_value)} />
            <Stat
              label="Total P&L"
              value={`${signedUsd(summary.total_pnl)} (${summary.total_return_pct > 0 ? '+' : ''}${summary.total_return_pct}%)`}
              className={tone(summary.total_pnl)}
            />
          </section>
        )}

        {summary && (
          <div className="grid gap-6 lg:grid-cols-5">
            <form onSubmit={submit} className="lg:col-span-2 bg-white border border-slate-200 rounded-lg p-4 space-y-4" noValidate>
              <h2 className="font-semibold text-lg">Trade ticket</h2>

              <div role="group" aria-label="Side" className="grid grid-cols-2 gap-2">
                {['buy', 'sell'].map((s) => (
                  <button
                    type="button" key={s} aria-pressed={side === s}
                    onClick={() => choose(s)}
                    className={`py-2 rounded font-semibold border ${side === s
                      ? (s === 'buy' ? 'bg-emerald-700 text-white border-emerald-700' : 'bg-red-700 text-white border-red-700')
                      : 'bg-white border-slate-300'}`}
                  >
                    {s === 'buy' ? 'Buy' : 'Sell'}
                  </button>
                ))}
              </div>

              <div>
                <label htmlFor="ticker" className="block text-sm font-semibold">Ticker</label>
                <input
                  id="ticker" value={ticker} autoComplete="off" spellCheck={false}
                  onChange={(e) => { ticketChanged(); setTicker(e.target.value.trim().toUpperCase()); }}
                  className="mt-1 w-full border border-slate-300 rounded px-3 py-2 uppercase"
                />
                <p className="text-sm text-slate-600 mt-1" aria-live="polite">
                  {!validTicker && 'Use a ticker such as AAPL or BRK-B.'}
                  {validTicker && quote.state === 'loading' && 'Checking the latest saved price…'}
                  {validTicker && quote.state === 'ready' && `Last saved close ${usd(quote.price)} on ${day(quote.asOf)}.`}
                  {validTicker && quote.state === 'missing' && `No saved prices for ${ticker} yet.`}
                  {validTicker && quote.state === 'error' && quote.message}
                </p>
                {validTicker && quote.state === 'missing' && (
                  <button type="button" onClick={fetchPrices} disabled={busy} className="mt-1 text-sm font-semibold underline">
                    Fetch prices for {ticker}
                  </button>
                )}
              </div>

              <div>
                <div className="flex items-end justify-between gap-2">
                  <label htmlFor="amount" className="block text-sm font-semibold">
                    {mode === 'shares' ? 'Shares' : 'Dollars'}
                  </label>
                  {side === 'buy' && (
                    <button
                      type="button" className="text-sm underline"
                      onClick={() => { ticketChanged(); setMode(mode === 'shares' ? 'dollars' : 'shares'); setAmount(''); }}
                    >
                      Enter {mode === 'shares' ? 'dollars' : 'shares'} instead
                    </button>
                  )}
                </div>
                <input
                  id="amount" inputMode="decimal" value={amount} placeholder={mode === 'shares' ? '0' : '$0.00'}
                  onChange={(e) => { ticketChanged(); setAmount(e.target.value); }}
                  className="mt-1 w-full border border-slate-300 rounded px-3 py-2"
                />
                {side === 'sell' && (
                  <div className="mt-2 flex items-center gap-2 text-sm">
                    <span className="text-slate-600">
                      {holding ? `You own ${count(holding.shares)}.` : `You don’t own ${validTicker ? ticker : 'this stock'}.`}
                    </span>
                    {holding && [0.25, 0.5, 1].map((f) => (
                      <button type="button" key={f} onClick={() => sellFraction(f)} className="px-2 py-0.5 border border-slate-300 rounded">
                        {f === 1 ? 'All' : `${f * 100}%`}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {estimate && (
                <p className="text-sm bg-slate-100 rounded p-2">
                  {side === 'buy' ? 'Estimated cost' : 'Estimated proceeds'}: <strong>{usd(estimate.total)}</strong>
                  {' '}for {count(Math.floor(estimate.shares * 1e6) / 1e6)} shares at {usd(price)}.
                </p>
              )}

              <button
                type="submit" disabled={busy}
                className="w-full py-2 rounded bg-slate-900 text-white font-semibold disabled:opacity-60"
              >
                {busy ? 'Working…' : `${side === 'buy' ? 'Buy' : 'Sell'} ${validTicker ? ticker : ''} (simulated)`}
              </button>

              {message && (
                <p
                  role={message.kind === 'error' ? 'alert' : 'status'}
                  className={`text-sm rounded p-2 ${message.kind === 'error' ? 'bg-red-50 text-red-900' : 'bg-emerald-50 text-emerald-900'}`}
                >
                  {message.text}
                </p>
              )}
              {needsPrices && (
                <button type="button" onClick={fetchPrices} disabled={busy} className="text-sm font-semibold underline">
                  Fetch the latest prices for {ticker}
                </button>
              )}
            </form>

            <section aria-labelledby="holdings-heading" className="lg:col-span-3 bg-white border border-slate-200 rounded-lg p-4">
              <h2 id="holdings-heading" className="font-semibold text-lg">Holdings</h2>
              {account.positions.length === 0 ? (
                <p className="mt-2 text-slate-600">Nothing yet. Place a simulated buy to start.</p>
              ) : (
                <div className="overflow-x-auto mt-2">
                  <table className="w-full text-sm text-left">
                    <thead>
                      <tr className="border-b border-slate-200 text-slate-600">
                        <th className="py-2 pr-3">Stock</th><th className="pr-3">Shares</th><th className="pr-3">Avg cost</th>
                        <th className="pr-3">Price</th><th className="pr-3">Value</th><th className="pr-3">P&amp;L</th><th><span className="sr-only">Actions</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      {account.positions.map((p) => (
                        <tr key={p.symbol} className="border-b border-slate-100">
                          <th scope="row" className="py-2 pr-3 font-semibold">{p.symbol}</th>
                          <td className="pr-3">{count(p.shares)}</td>
                          <td className="pr-3">{usd(p.average_cost)}</td>
                          <td className="pr-3">
                            {usd(p.price)}
                            {!p.price_available && <span className="block text-xs text-slate-500">no saved price</span>}
                          </td>
                          <td className="pr-3">{usd(p.market_value)}</td>
                          <td className={`pr-3 ${tone(p.unrealized_pnl)}`}>
                            {signedUsd(p.unrealized_pnl)} <span className="text-xs">({p.unrealized_pnl_pct > 0 ? '+' : ''}{p.unrealized_pnl_pct}%)</span>
                          </td>
                          <td className="whitespace-nowrap">
                            <button
                              type="button" className="px-2 py-1 border border-slate-300 rounded"
                              onClick={() => { choose('sell', p.symbol, String(p.shares)); }}
                              aria-label={`Sell ${p.symbol}`}
                            >
                              Sell
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        )}

        {summary && (
          <section aria-labelledby="orders-heading" className="bg-white border border-slate-200 rounded-lg p-4">
            <div className="flex items-center justify-between gap-3">
              <h2 id="orders-heading" className="font-semibold text-lg">Order history</h2>
              <button type="button" onClick={reset} disabled={busy} className="text-sm px-3 py-1 border border-slate-300 rounded">
                Reset account
              </button>
            </div>
            {orders.length === 0 ? (
              <p className="mt-2 text-slate-600">No orders yet.</p>
            ) : (
              <div className="overflow-x-auto mt-2">
                <table className="w-full text-sm text-left">
                  <thead>
                    <tr className="border-b border-slate-200 text-slate-600">
                      <th className="py-2 pr-3">When</th><th className="pr-3">Side</th><th className="pr-3">Stock</th>
                      <th className="pr-3">Shares</th><th className="pr-3">Price</th><th className="pr-3">Total</th>
                      <th className="pr-3">Realized P&amp;L</th><th>From forecast</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orders.map((o) => (
                      <tr key={o.id} className="border-b border-slate-100">
                        <td className="py-2 pr-3 whitespace-nowrap">{day(o.created_at)}</td>
                        <td className="pr-3 capitalize">{o.side}</td>
                        <th scope="row" className="pr-3 font-semibold">{o.symbol}</th>
                        <td className="pr-3">{count(o.shares)}</td>
                        <td className="pr-3">{usd(o.price)}</td>
                        <td className="pr-3">{usd(o.shares * o.price)}</td>
                        <td className={`pr-3 ${tone(o.realized_pnl)}`}>{o.realized_pnl == null ? '—' : signedUsd(o.realized_pnl)}</td>
                        <td>
                          {o.prediction_id
                            ? `${DIRECTIONS[o.forecast_direction] ?? 'saved'} call${o.forecast_horizon_days ? `, ${o.forecast_horizon_days}-day` : ''}`
                            : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}
      </main>
    </div>
  );
}

function Stat({ label, value, className = '' }) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-3">
      <div className="text-xs uppercase tracking-wide text-slate-600">{label}</div>
      <div className={`text-lg font-semibold ${className}`}>{value}</div>
    </div>
  );
}
