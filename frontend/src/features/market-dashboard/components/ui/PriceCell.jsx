// Last saved price + change vs. previous close. Subscribes to the tick store for its symbol,
// so every cell showing a symbol updates when any panel loads a newer price.
import { memo } from 'react';
import { useTick } from '../../lib/tickStore.js';
import { money, percent, signed } from '../../lib/format.js';

function PriceCell({ symbol, price, previous, learning = false }) {
  const tick = useTick(symbol);
  const p = tick.symbol ? tick.price : price;
  if (p == null) return <span className="mono muted">—</span>;
  const change = previous ? percent(p, previous) : null;

  return (
    <span className="inline-flex flex-col items-end leading-tight">
      <strong className="mono">{money(p)}</strong>
      {change != null && (
        <span className={`mono small ${change >= 0 ? 'up' : 'down'}`}>
          {change >= 0 ? '▲' : '▼'} {signed(change)} <span className="sr-only">{change >= 0 ? 'up' : 'down'}</span>
        </span>
      )}
      {learning && <span className="small muted text-right">Change since the previous close.</span>}
    </span>
  );
}

export default memo(PriceCell);
