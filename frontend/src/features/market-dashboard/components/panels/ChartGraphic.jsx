// Draws the price line. Uses TradingView Lightweight Charts when `api` is loaded,
// otherwise falls back to a simple inline SVG. Marks the biggest moves and, when a
// forecast exists, its flat band around the forecast's last price.
import { useEffect, useRef } from 'react';
import { useUI } from '../../context/UIContext.js';

// Theme tokens are scoped to the dashboard wrapper, so read them from the chart's own element.
const cssVar = (element, name) => getComputedStyle(element).getPropertyValue(name).trim();
// Unix seconds keep intraday points distinct; date strings would collide within a day.
const toTime = (iso) => Math.floor(new Date(iso).getTime() / 1000);

export default function ChartGraphic({ points, prediction, moves, event, api }) {
  const host = useRef(null);
  const { theme } = useUI();

  useEffect(() => {
    if (!api || !host.current || points.length < 2) return undefined;
    try {
      host.current.innerHTML = '';
      const color = (name) => cssVar(host.current, name);
      const intraday = new Date(points.at(-1).t) - new Date(points[0].t) < 8 * 86400000;
      const chart = api.createChart(host.current, {
        width: host.current.clientWidth,
        height: 260,
        layout: { background: { color: color('--panel') }, textColor: color('--ink2') },
        grid: { vertLines: { visible: false }, horzLines: { color: color('--rule') } },
        rightPriceScale: { borderVisible: false },
        timeScale: { borderVisible: false, timeVisible: intraday },
      });

      const series = chart.addLineSeries({ color: color('--accent'), lineWidth: 2 });
      series.setData(points.map((p) => ({ time: toTime(p.t), value: p.value })));

      // Markers for the biggest moves; the selected one is labelled.
      series.setMarkers((moves || [])
        .map((m) => ({
          time: toTime(m.t),
          position: m.change >= 0 ? 'aboveBar' : 'belowBar',
          shape: 'circle',
          color: m.id === event ? color('--accent') : color('--ink2'),
          text: m.id === event ? `${m.change >= 0 ? '+' : ''}${m.change.toFixed(1)}%` : '',
        }))
        .sort((a, b) => a.time - b.time));

      if (prediction?.last_price && prediction.flat_band_pct) {
        const band = prediction.last_price * (prediction.flat_band_pct / 100);
        for (const [price, title] of [[prediction.last_price + band, 'flat band'], [prediction.last_price - band, '']]) {
          series.createPriceLine({ price, color: color('--ink2'), lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title });
        }
      }

      chart.timeScale().fitContent();
      const observer = new ResizeObserver(() => chart.applyOptions({ width: host.current?.clientWidth || 300 }));
      observer.observe(host.current);
      return () => { observer.disconnect(); chart.remove(); };
    } catch (err) {
      console.error('Chart render failed:', err);
      return undefined;
    }
  }, [points, prediction, moves, api, event, theme]);

  if (api) return <div ref={host} className="plot" aria-hidden="true" />;

  // ---- SVG fallback ----
  if (points.length < 2) return <div className="plot" aria-hidden="true" />;
  const min = Math.min(...points.map((p) => p.value)) * 0.98;
  const max = Math.max(...points.map((p) => p.value)) * 1.02;
  const y = (v) => 210 - ((v - min) / (max - min || 1)) * 175;
  const xy = points.map((p, i) => `${(i / (points.length - 1)) * 680},${y(p.value)}`).join(' ');
  const cy = y(points[points.length - 1].value);

  return (
    <div className="plot" aria-hidden="true">
      <svg viewBox="0 0 700 260" preserveAspectRatio="none">
        <line x1="0" y1="210" x2="700" y2="210" stroke="currentColor" opacity=".2" />
        <polyline fill="none" stroke="var(--accent)" strokeWidth="2.5" points={xy} />
        <circle cx="680" cy={cy} r="5" fill="var(--accent)" />
      </svg>
    </div>
  );
}
