// Filterable, virtualized news list.
import { useState, useMemo, useRef } from 'react';
import { strings } from '../../constants/strings.js';
import { NEWS_FILTERS } from '../../constants/options.js';
import { dateText } from '../../lib/format.js';
import { useRoving } from '../../hooks/useRoving.js';
import StatePanel from '../ui/StatePanel.jsx';
import VirtualList from '../ui/VirtualList.jsx';

function NewsRow({ item }) {
  const icon = item.sentiment === 'Positive' ? '▲' : item.sentiment === 'Negative' ? '▼' : '◆';
  return (
    <article className="line-row pr-2 h-full">
      <div className="small muted">{item.source} · {dateText(item.publishedAt)} · {item.tickers.join(', ')}</div>
      <h3 className="headline font-semibold leading-snug my-1">{item.headline}</h3>
      <span className="tag">{icon} {item.sentiment}</span>
    </article>
  );
}

export default function NewsPanel({ state, asset, filter, setFilter }) {
  const heading = useRef(null);
  const roving = useRoving(NEWS_FILTERS, filter, setFilter);
  const [sector, setSector] = useState(false);

  const filtered = useMemo(() => state.data?.filter((n) => {
    if (sector) return n.category === 'sector';
    if (filter === 'This asset') return n.tickers.includes(asset.symbol);
    if (filter === 'Economy') return n.category === 'economy';
    if (filter === 'Crypto') return n.category === 'crypto';
    return true;
  }) || [], [state.data, filter, asset.symbol, sector]);

  return (
    <section id="news" aria-labelledby="news-heading" className="panel lg:col-span-8">
      <h2 id="news-heading" ref={heading} tabIndex={-1}>{strings.news}</h2>
      <div role="tablist" aria-label="News filter" className="flex gap-1 flex-wrap mb-4">
        {NEWS_FILTERS.map((f, i) => (
          <button
            key={f}
            role="tab"
            aria-selected={!sector && filter === f}
            tabIndex={filter === f ? 0 : -1}
            className="action small"
            onClick={() => { setSector(false); setFilter(f); }}
            onKeyDown={(e) => roving(e, i)}
          >
            {f}
          </button>
        ))}
      </div>
      <StatePanel name={strings.news} state={state} headingRef={heading}>
        {filtered.length ? (
          <VirtualList items={filtered} rowHeight={107} ariaLabel="News headlines" render={(n) => <NewsRow item={n} />} />
        ) : (
          <div>
            <p>{strings.noNews}</p>
            <button className="action mt-3" onClick={() => setSector(true)}>{strings.sector}</button>
          </div>
        )}
      </StatePanel>
    </section>
  );
}
