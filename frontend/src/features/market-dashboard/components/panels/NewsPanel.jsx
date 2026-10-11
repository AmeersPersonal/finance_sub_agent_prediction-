// Saved source documents for the ticker, filterable by the role the backend gave them.
// Each headline links to the original article or filing.
import { useMemo, useRef } from 'react';
import { strings } from '../../constants/strings.js';
import { NEWS_FILTERS, NEWS_ROLES } from '../../constants/options.js';
import { dateText } from '../../lib/format.js';
import { useRoving } from '../../hooks/useRoving.js';
import StatePanel from '../ui/StatePanel.jsx';
import VirtualList from '../ui/VirtualList.jsx';

const ROLE_LABELS = { company_info: 'Company info', public_opinion: 'Opinion', product_event: 'Product & events' };

function NewsRow({ item }) {
  return (
    <article className="line-row pr-2 h-full">
      <div className="small muted">{item.source} · {dateText(item.publishedAt)}</div>
      <h3 className="headline font-semibold leading-snug my-1">
        <a href={item.url} target="_blank" rel="noopener noreferrer">{item.headline}</a>
      </h3>
      <span className="tag">{ROLE_LABELS[item.role] || 'Other'}</span>
    </article>
  );
}

export default function NewsPanel({ state, filter, setFilter, onLoad }) {
  const heading = useRef(null);
  const roving = useRoving(NEWS_FILTERS, filter, setFilter);

  const filtered = useMemo(() => (state.data || [])
    .filter((n) => filter === 'All' || n.role === NEWS_ROLES[filter])
    .sort((a, b) => new Date(b.publishedAt) - new Date(a.publishedAt)), [state.data, filter]);

  return (
    <section id="news" aria-labelledby="news-heading" className="panel lg:col-span-8">
      <h2 id="news-heading" ref={heading} tabIndex={-1}>{strings.news}</h2>
      <div role="tablist" aria-label="News filter" className="flex gap-1 flex-wrap mb-4">
        {NEWS_FILTERS.map((f, i) => (
          <button
            key={f}
            role="tab"
            aria-selected={filter === f}
            tabIndex={filter === f ? 0 : -1}
            className="action small"
            onClick={() => setFilter(f)}
            onKeyDown={(e) => roving(e, i)}
          >
            {f}
          </button>
        ))}
      </div>
      <StatePanel name={strings.news} state={state} headingRef={heading} onLoad={onLoad} emptyText={strings.noNews}>
        {filtered.length ? (
          <VirtualList items={filtered} rowHeight={107} ariaLabel="News headlines" render={(n) => <NewsRow item={n} />} />
        ) : (
          <p className="muted">{strings.noNewsFilter}</p>
        )}
      </StatePanel>
      <p className="small muted mt-3">{strings.newsNote}</p>
    </section>
  );
}
