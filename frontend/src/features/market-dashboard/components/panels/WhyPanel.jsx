// "Why it moved": the three largest moves in the chart's timeframe, each with the
// saved headlines from that trading session (if any were collected that day).
import { strings } from '../../constants/strings.js';
import { dateText, signed } from '../../lib/format.js';
import StatePanel from '../ui/StatePanel.jsx';

export default function WhyPanel({ history, moves, intraday, selectedEvent, setSelectedEvent }) {
  return (
    <section id="why" aria-labelledby="why-heading" className="panel lg:col-span-4">
      <h2 id="why-heading">{strings.why}</h2>
      <p className="small muted mb-2">{intraday ? strings.whyIntraday : strings.whyDaily}</p>
      <StatePanel name={strings.why} state={history} emptyText={strings.noPrices}>
        {moves.length ? moves.map((m) => (
          <button
            key={m.id}
            className="line-row w-full text-left block hover:opacity-75"
            aria-pressed={selectedEvent === m.id}
            onClick={() => { setSelectedEvent(m.id); document.getElementById('chart')?.scrollIntoView({ block: 'nearest' }); }}
          >
            <span className="flex justify-between gap-2">
              <strong>{dateText(m.t)}</strong>
              <span className={`mono ${m.change >= 0 ? 'up' : 'down'}`}>{m.change >= 0 ? '▲' : '▼'} {signed(m.change)}</span>
            </span>
            <span className="block small muted mt-1">
              {m.headlines.length
                ? `${m.headlines[0].headline}${m.headlines.length > 1 ? ` (+${m.headlines.length - 1} more that day)` : ''}`
                : strings.noMoveHeadline}
            </span>
          </button>
        )) : <p className="muted">{strings.empty}</p>}
      </StatePanel>
    </section>
  );
}
