// Strip of broad-market ETFs with their last saved prices.
import { strings } from '../../constants/strings.js';
import { assetFor } from '../../lib/assets.js';
import { marketStatus } from '../../lib/marketStatus.js';
import { useQuote } from '../../hooks/useResource.js';
import PriceCell from '../ui/PriceCell.jsx';

const PULSE = [
  { symbol: 'SPY', label: 'S&P 500 · SPY' },
  { symbol: 'QQQ', label: 'Nasdaq-100 · QQQ' },
  { symbol: 'DIA', label: 'Dow · DIA' },
];

function PulseItem({ symbol, label, override, reload }) {
  const quote = useQuote(symbol, 'normal', reload);
  const asset = assetFor(symbol);
  return (
    <div className="border-r rule pr-3">
      <div className="font-semibold">{label}</div>
      <PriceCell symbol={symbol} price={quote.data?.price} previous={quote.data?.previousClose} />
      <div className="small muted">
        <span className="live-dot" aria-hidden="true" style={{ background: 'var(--ink2)' }} />
        {strings.statuses[marketStatus(asset, quote.data, override)]}
      </div>
    </div>
  );
}

export default function MarketPulse({ override, reload }) {
  return (
    <section aria-labelledby="pulse-heading" className="border-y rule py-4 mb-5">
      <h2 id="pulse-heading" className="eyebrow mb-3">{strings.pulse}</h2>
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        {PULSE.map((p) => <PulseItem key={p.symbol} {...p} override={override} reload={reload} />)}
      </div>
    </section>
  );
}
