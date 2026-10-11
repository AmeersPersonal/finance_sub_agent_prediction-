// "Today's story": a plain-language explanation of the selected asset's move.
import { useRef } from 'react';
import { strings } from '../../constants/strings.js';
import { events, newsData } from '../../data/mockData.js';
import { percent, compact } from '../../lib/format.js';
import StatePanel from '../ui/StatePanel.jsx';
import Term from '../ui/Term.jsx';

export default function StoryPanel({ asset, quote, setSelectedEvent, learning }) {
  const heading = useRef(null);
  const e = events.find((x) => x.symbol === asset.symbol) || events[0];
  const headline = newsData.find((n) => n.eventId === e.id);
  const move = quote.data ? percent(quote.data.price, quote.data.previousClose) : 0;

  function seeOnChart() {
    setSelectedEvent(e.id);
    document.getElementById('chart')?.scrollIntoView({ block: 'center' });
    document.querySelector('#chart [role=img]')?.focus();
  }

  return (
    <section id="story" aria-labelledby="story-heading" className="panel lg:col-span-5">
      <div className="eyebrow mb-2">THE DAILY EXPLANATION · {asset.type.toUpperCase()}</div>
      <h2 id="story-heading" ref={heading} tabIndex={-1}>{strings.story}</h2>

      <StatePanel name={strings.story} state={quote} headingRef={heading}>
        <p className="serif text-[clamp(1.35rem,2.3vw,2rem)] leading-snug mb-5">
          {asset.name} {move < 0 ? 'fell' : 'rose'} {Math.abs(move).toFixed(1)}% versus its previous close. {e.explanation}
        </p>
        <div className="tag mb-4">{e.category}</div>

        {headline && (
          <p className="small border-l-2 pl-3 mb-5" style={{ borderColor: 'var(--accent)' }}>
            Related headline: {headline.headline} <span className="muted">· {headline.source}</span>
          </p>
        )}

        <button className="action primary" onClick={seeOnChart}>{strings.seeChart} →</button>

        <div className="border-t rule mt-6 pt-4 flex justify-between gap-3">
          <span>
            <Term name={strings.marketCap} description={strings.marketCapExplain} />
            {learning && <span className="block small muted">{strings.marketCapExplain}</span>}
          </span>
          <span className="mono text-right" aria-label={`${asset.marketCap.toLocaleString('en-US')} US dollars`}>
            {compact(asset.marketCap)}
          </span>
        </div>

        {quote.data?.status === 'halted' && <p className="mt-3 down">{strings.halt} · {strings.haltExplain}</p>}
      </StatePanel>
    </section>
  );
}
