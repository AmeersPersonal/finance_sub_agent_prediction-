// Price chart with timeframe tabs, keyboard point navigation, table view, and event markers.
import { useState, useEffect, useRef } from 'react';
import { strings } from '../../constants/strings.js';
import { TIMEFRAMES } from '../../constants/options.js';
import { money, percent, signed, dateText } from '../../lib/format.js';
import { marketStatus } from '../../lib/marketStatus.js';
import { tickValues } from '../../lib/tickStore.js';
import { useRoving } from '../../hooks/useRoving.js';
import StatePanel from '../ui/StatePanel.jsx';
import PriceCell from '../ui/PriceCell.jsx';
import ChartGraphic from './ChartGraphic.jsx';

export default function ChartPanel({
  asset, tf, setTf, history, quote, prediction, moves, selectedEvent, setSelectedEvent, learning, announce, onLoad,
}) {
  const [table, setTable] = useState(false);
  const [index, setIndex] = useState(0);
  const [chartApi, setChartApi] = useState(null);
  const heading = useRef(null);
  const roving = useRoving(TIMEFRAMES, tf, setTf);

  const points = history.data || [];
  const first = points[0];
  const last = points[points.length - 1];
  const change = first && last ? percent(last.value, first.value) : 0;
  const relevant = moves;
  const summary = first && last
    ? `${asset.name}, ${tf}: ${change >= 0 ? 'rose' : 'fell'} from ${money(first.value)} to ${money(last.value)}, ${signed(change)}. ${relevant.length} largest moves marked.`
    : `${asset.name}, ${tf}: chart loading.`;

  // Lazy-load the chart library; if it fails, the SVG fallback is used.
  useEffect(() => {
    let cancelled = false;
    import('lightweight-charts')
      .then((mod) => { if (!cancelled) setChartApi(mod); })
      .catch((err) => { console.warn('lightweight-charts failed to load, using SVG fallback.', err); });
    return () => { cancelled = true; };
  }, []);

  function selectEvent(e) {
    setSelectedEvent(e.id);
    announce(`${dateText(e.t)}: ${signed(e.change)}. ${e.headlines[0]?.headline || strings.noMoveHeadline}`);
    document.getElementById('why')?.scrollIntoView({ block: 'nearest' });
  }

  function movePoint(e) {
    if (!points.length) return;
    let n = index;
    if (e.key === 'ArrowLeft') n = Math.max(0, index - 1);
    else if (e.key === 'ArrowRight') n = Math.min(points.length - 1, index + 1);
    else if (e.key === 'Home') n = 0;
    else if (e.key === 'End') n = points.length - 1;
    else if (e.key === 'Enter' && relevant.length) selectEvent(relevant[0]);
    else return;
    e.preventDefault();
    setIndex(n);
    if (e.key !== 'Enter') announce(`${dateText(points[n].t)}, ${money(points[n].value)}, point ${n + 1} of ${points.length}.`);
  }

  return (
    <section id="chart" aria-labelledby="chart-heading" className={`panel lg:col-span-7 ${selectedEvent ? 'chart-highlight' : ''}`}>
      <div className="flex justify-between gap-3 mobile-stack">
        <div>
          <div className="eyebrow">{asset.symbol} · {asset.type}</div>
          <h2 id="chart-heading" ref={heading} tabIndex={-1}>{strings.chart}</h2>
        </div>
        {quote.data && (
          <div className="text-right">
            <PriceCell symbol={asset.symbol} price={quote.data.price} previous={quote.data.previousClose} learning={learning} />
            <div className="small muted">{strings.statuses[marketStatus(asset, quote.data, 'normal')]}</div>
          </div>
        )}
      </div>

      <StatePanel name={strings.chart} state={history} headingRef={heading} onLoad={onLoad} emptyText={strings.noPrices}>
        <div role="tablist" aria-label="Chart timeframe" className="flex gap-1 flex-wrap mb-3">
          {TIMEFRAMES.map((t, i) => (
            <button
              key={t}
              role="tab"
              aria-selected={tf === t}
              tabIndex={tf === t ? 0 : -1}
              className="action mono small"
              onClick={() => { setTf(t); setIndex(0); }}
              onKeyDown={(e) => roving(e, i)}
            >
              {t}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap justify-between gap-2 mb-2">
          <span className="small muted">{strings.chartInstructions}</span>
          <div className="flex gap-2">
            <button
              className="action small"
              onClick={() => {
                const price = tickValues[asset.symbol]?.price ?? quote.data?.price;
                announce(price ? `${asset.name}, last saved price ${money(price)}.` : `${asset.name}: no saved price yet.`);
              }}
            >
              {strings.readPrice}
            </button>
            <button className="action small" aria-pressed={table} onClick={() => setTable((v) => !v)}>
              {table ? strings.visual : strings.table}
            </button>
          </div>
        </div>

        {table ? (
          <div className="overflow-x-auto max-h-[260px] overflow-y-auto">
            <table className="w-full text-left small">
              <caption className="text-left mb-2">{asset.name} · {tf} historical prices</caption>
              <thead>
                <tr><th scope="col" className="py-2">Date</th><th scope="col">Price</th></tr>
              </thead>
              <tbody>
                {points.map((p) => (
                  <tr key={p.t} className="border-t rule">
                    <th scope="row" className="py-1 font-normal">{dateText(p.t)}</th>
                    <td className="mono">{money(p.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div role="img" tabIndex={0} aria-label={summary} onKeyDown={movePoint} className="rounded focus-visible:outline">
            <ChartGraphic points={points} prediction={prediction} moves={relevant} event={selectedEvent} api={chartApi} />
          </div>
        )}

        <div className="flex flex-wrap gap-2 mt-3" aria-label="Chart event markers">
          {relevant.map((e) => (
            <button key={e.id} className="action small" aria-pressed={selectedEvent === e.id} onClick={() => selectEvent(e)}>
              ● {dateText(e.t)} · <span className={e.change >= 0 ? 'up' : 'down'}>{signed(e.change)}</span>
            </button>
          ))}
        </div>

        <p className="small muted mt-3">
          {chartApi
            ? <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">{strings.chartAttribution}</a>
            : strings.chartFallback}
        </p>
      </StatePanel>
    </section>
  );
}
