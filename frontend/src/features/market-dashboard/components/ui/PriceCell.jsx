// Live price + change vs. previous close. Subscribes to the tick store for its symbol only.
import { memo } from 'react';
import { useTick } from '../../lib/tickStore.js';
import { base } from '../../data/mockData.js';
import { money, percent, signed } from '../../lib/format.js';

function PriceCell({ symbol, previous, learning = false }) {
  const tick = useTick(symbol);
  const p = tick.symbol ? tick.price : base[symbol][0];
  const change = percent(p, previous);

  return (
    <span className="inline-flex flex-col items-end leading-tight">
      <strong className="mono">{money(p)}</strong>
      <span className={`mono small ${change >= 0 ? 'up' : 'down'}`}>
        {change >= 0 ? '▲' : '▼'} {signed(change)} <span className="sr-only">{change >= 0 ? 'up' : 'down'}</span>
      </span>
      {learning && <span className="small muted text-right">Change since the previous close.</span>}
    </span>
  );
}

export default memo(PriceCell);
