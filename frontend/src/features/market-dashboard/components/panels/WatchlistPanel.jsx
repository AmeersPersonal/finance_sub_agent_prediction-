// Reader watchlist (saved in this browser) with each symbol's last saved price.
import { memo } from 'react';
import { strings } from '../../constants/strings.js';
import { assetFor } from '../../lib/assets.js';
import { marketStatus } from '../../lib/marketStatus.js';
import { useQuote } from '../../hooks/useResource.js';
import PriceCell from '../ui/PriceCell.jsx';

const WatchRow = memo(function WatchRow({ symbol, reload, onSelect, onRemove }) {
  const asset = assetFor(symbol);
  const quote = useQuote(symbol, 'normal', reload);
  const status = marketStatus(asset, quote.data, 'normal');
  return (
    <div className="line-row flex items-center gap-2">
      <div className="min-w-0 flex-1">
        <button className="flex items-center gap-1 hover:opacity-75" onClick={() => onSelect(symbol)} aria-label={`Show ${asset.name}`}>
          <strong>{symbol}</strong><span className="tag">{asset.type}</span>
        </button>
        <div className="small muted truncate-name" title={asset.name}>{asset.name}</div>
        <div className="small muted">
          <span className="live-dot" aria-hidden="true" style={{ background: status === 'open' ? 'var(--up)' : 'var(--ink2)' }} />
          {quote.status === 'empty' ? strings.noPrices : strings.statuses[status]}
        </div>
      </div>
      <PriceCell symbol={symbol} price={quote.data?.price} previous={quote.data?.previousClose} />
      <button className="action small !px-2" aria-label={`${strings.remove} ${asset.name}`} onClick={() => onRemove(symbol)}>×</button>
    </div>
  );
});

export default function WatchlistPanel({ items, add, remove, onSelect, reload }) {
  return (
    <section aria-labelledby="watch-heading" className="panel lg:col-span-4">
      <h2 id="watch-heading">{strings.watchlist}</h2>
      {!items.length ? (
        <div>
          <p>{strings.noWatchlist}</p>
          <div className="flex gap-2 flex-wrap mt-4">
            {['NVDA', 'AAPL', 'SPY'].map((s) => (
              <button key={s} className="action" onClick={() => add(s)}>{strings.add} {s}</button>
            ))}
          </div>
        </div>
      ) : (
        <div className="max-h-[430px] overflow-y-auto pr-1" tabIndex={0} aria-label="Watchlist assets">
          {items.map((w) => <WatchRow key={w.symbol} symbol={w.symbol} reload={reload} onSelect={onSelect} onRemove={remove} />)}
        </div>
      )}
    </section>
  );
}
