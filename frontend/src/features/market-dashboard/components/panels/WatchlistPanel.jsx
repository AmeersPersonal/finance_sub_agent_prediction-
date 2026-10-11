// Reader watchlist. Repeats saved symbols to 150 rows to demo the virtualized list.
import { memo, useMemo } from 'react';
import { strings } from '../../constants/strings.js';
import { assets, seedQuotes } from '../../data/mockData.js';
import { marketStatus } from '../../lib/marketStatus.js';
import PriceCell from '../ui/PriceCell.jsx';
import VirtualList from '../ui/VirtualList.jsx';

const WatchRow = memo(function WatchRow({ asset, onRemove }) {
  const status = marketStatus(asset, seedQuotes[asset.symbol], 'normal');
  return (
    <div className="line-row flex items-center gap-2 h-full">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1"><strong>{asset.symbol}</strong><span className="tag">{asset.type}</span></div>
        <div className="small muted truncate-name" aria-label={asset.name} title={asset.name}>{asset.name}</div>
        <div className="small muted">
          <span className="live-dot" aria-hidden="true" style={{ background: status === 'open' ? 'var(--up)' : 'var(--ink2)' }} />
          {strings.statuses[status]}
        </div>
      </div>
      <PriceCell symbol={asset.symbol} previous={seedQuotes[asset.symbol].previousClose} />
      <button className="action small !px-2" aria-label={`${strings.remove} ${asset.name}`} onClick={() => onRemove(asset.symbol)}>×</button>
    </div>
  );
});

export default function WatchlistPanel({ items, add, remove }) {
  const demo = useMemo(() => (items.length > 0
    ? Array.from({ length: 150 }, (_, i) => assets.find((a) => a.symbol === items[i % items.length].symbol)).filter(Boolean)
    : []), [items]);

  return (
    <section aria-labelledby="watch-heading" className="panel lg:col-span-4">
      <h2 id="watch-heading">{strings.watchlist}</h2>
      {!items.length ? (
        <div>
          <p>{strings.noWatchlist}</p>
          <div className="flex gap-2 flex-wrap mt-4">
            {['AAPL', 'VOO', 'BTC'].map((s) => (
              <button key={s} className="action" onClick={() => add(s)}>{strings.add} {s}</button>
            ))}
          </div>
        </div>
      ) : (
        <>
          <p className="small muted mb-2">150-row scrolling demo · {items.length} saved selections</p>
          <VirtualList items={demo} rowHeight={85} ariaLabel="Watchlist assets" render={(a) => <WatchRow asset={a} onRemove={remove} />} />
        </>
      )}
      <a href="/paper-trading" target="_blank" rel="noopener noreferrer" className="inline-block mt-4 font-semibold">{strings.paper}</a>
      <p className="small muted">{strings.paperNote}</p>
    </section>
  );
}
