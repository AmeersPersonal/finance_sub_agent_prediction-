// Welcome heading plus when the shown data was saved and a button to fetch fresh data.
import { strings } from '../../constants/strings.js';
import { timeText } from '../../lib/format.js';

export default function Hero({ symbol, quote, refresh }) {
  const running = refresh.status === 'running';
  return (
    <div className="flex justify-between flex-wrap gap-3 py-5">
      <div>
        <p className="eyebrow">THE MARKET, EXPLAINED</p>
        <p className="serif text-[clamp(1.5rem,2.8vw,2.35rem)] leading-tight">{strings.welcome}</p>
        <h1 id="dashboard-title" tabIndex={-1} className="serif text-[clamp(2rem,4vw,3.4rem)] leading-tight">{strings.welcomeQuestion}</h1>
        <p className="muted small mt-1">{strings.educational} {strings.dataSource}</p>
      </div>
      <div className="self-end small text-right" role="status" aria-live="polite">
        {quote.data?.asOf && <div className="muted">{strings.dataAsOf} {timeText(quote.data.asOf)}</div>}
        <div className="mt-1">
          {running && <span className="mr-2">{strings.refreshing}</span>}
          {refresh.status === 'done' && <span className="mr-2">{strings.refreshed}</span>}
          {refresh.status === 'failed' && <span className="down mr-2">{refresh.error}</span>}
          <button className="action small" disabled={running} onClick={refresh.run}>{strings.refresh} · {symbol}</button>
        </div>
      </div>
    </div>
  );
}
