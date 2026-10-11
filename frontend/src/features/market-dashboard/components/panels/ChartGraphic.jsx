// Draws the price line. Uses TradingView Lightweight Charts when `api` is loaded,
// otherwise falls back to a simple inline SVG.
import { useEffect, useRef } from 'react';
import { useUI } from '../../context/UIContext.js';

// Theme tokens are scoped to the dashboard wrapper, so read them from the chart's own element.
const cssVar = (element, name) => getComputedStyle(element).getPropertyValue(name).trim();
// Unix seconds keep intraday points distinct; date strings would collide within a day.
const toTime = (iso) => Math.floor(new Date(iso).getTime() / 1000);

export default function ChartGraphic({ points, forecast, event, api }) {
  const host = useRef(null);
  const { theme } = useUI();

  useEffect(() => {
    if (!api || !host.current || points.length < 2) return undefined;
    try {
      host.current.innerHTML = '';
      const color = (name) => cssVar(host.current, name);
      const chart = api.createChart(host.current, {
        width: host.current.clientWidth,
        height: 260,
        layout: { background: { color: color('--panel') }, textColor: color('--ink2') },
        grid: { vertLines: { visible: false }, horzLines: { color: color('--rule') } },
        rightPriceScale: { borderVisible: false },
        timeScale: { borderVisible: false },
      });

      const series = chart.addLineSeries({ color: color('--accent'), lineWidth: 2 });
      series.setData(points.map((p) => ({ time: toTime(p.t), value: p.value })));

      if (forecast?.status === 'ok') {
        const line = chart.addLineSeries({ color: color('--ink2'), lineWidth: 2, lineStyle: 2 });
        const last = points[points.length - 1];
        line.setData([
          { time: toTime(last.t), value: last.value },
          ...forecast.points.map((p, i) => ({
            time: toTime(new Date(new Date(last.t).getTime() + (i + 1) * 7 * 86400000)),
            value: p.mid,
          })),
        ]);
      }

      chart.timeScale().fitContent();
      const observer = new ResizeObserver(() => chart.applyOptions({ width: host.current?.clientWidth || 300 }));
      observer.observe(host.current);
      return () => { observer.disconnect(); chart.remove(); };
    } catch (err) {
      console.error('Chart render failed:', err);
      return undefined;
    }
  }, [points, forecast, api, event, theme]);

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
        {forecast?.status === 'ok' && (
          <>
            <path d={`M 680 ${cy} L 700 ${cy - 25} L 700 ${cy + 28} Z`} fill="var(--accent)" opacity=".13" />
            <line x1="680" y1={cy} x2="700" y2={cy - 2} stroke="var(--accent)" strokeDasharray="5 4" />
          </>
        )}
        <polyline fill="none" stroke="var(--accent)" strokeWidth="2.5" points={xy} />
        <circle cx="680" cy={cy} r="5" fill="var(--accent)" />
      </svg>
    </div>
  );
}
