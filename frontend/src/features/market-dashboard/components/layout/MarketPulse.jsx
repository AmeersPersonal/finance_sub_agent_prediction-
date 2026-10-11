// Strip of headline indices (S&P 500, Nasdaq/QQQ, Dow, Bitcoin) with live prices.
import { strings } from '../../constants/strings.js';
import { assets, seedQuotes } from '../../data/mockData.js';
import { marketStatus } from '../../lib/marketStatus.js';
import PriceCell from '../ui/PriceCell.jsx';

const PULSE = [
  { symbol: 'SPX', label: 'S&P 500' },
  { symbol: 'QQQ', label: 'Nasdaq / QQQ' },
  { symbol: 'DJI', label: 'Dow' },
  { symbol: 'BTC', label: 'Bitcoin' },
].map((p) => ({ ...p, asset: assets.find((a) => a.symbol === p.symbol) }));

export default function MarketPulse({ override }) {
  return (
    <section aria-labelledby="pulse-heading" className="border-y rule py-4 mb-5">
      <h2 id="pulse-heading" className="eyebrow mb-3">{strings.pulse}</h2>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {PULSE.map(({ symbol, label, asset }) => (
          <div key={symbol} className="border-r rule pr-3">
            <div className="font-semibold">{label}</div>
            <PriceCell symbol={symbol} previous={seedQuotes[symbol].previousClose} />
            <div className="small muted">
              <span className="live-dot" aria-hidden="true" style={{ background: asset.type === 'Crypto' ? 'var(--up)' : 'var(--ink2)' }} />
              {strings.statuses[marketStatus(asset, seedQuotes[symbol], override)]}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
