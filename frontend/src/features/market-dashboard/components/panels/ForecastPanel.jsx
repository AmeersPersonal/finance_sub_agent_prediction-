// "What might happen next": a mock one-month range estimate with confidence and factors.
import { useRef } from 'react';
import { strings } from '../../constants/strings.js';
import { money } from '../../lib/format.js';
import StatePanel from '../ui/StatePanel.jsx';
import Term from '../ui/Term.jsx';

export default function ForecastPanel({ state, learning }) {
  const heading = useRef(null);
  const data = state.data;

  let body = null;
  if (data?.status === 'insufficient_data') {
    body = <p>{strings.insufficient}</p>;
  } else if (data?.status === 'model_unavailable') {
    body = (
      <div>
        <p>{strings.unavailable}</p>
        <button className="action mt-3" onClick={() => { state.refetch(); heading.current?.focus(); }}>{strings.retry}</button>
      </div>
    );
  } else if (data) {
    const final = data.points.at(-1);
    body = (
      <div>
        <div className="eyebrow mb-2">ONE-MONTH RANGE · MOCK ESTIMATE</div>
        <p className="mono text-lg">{money(final.low)} — {money(final.high)}</p>
        <p className="small muted mt-1">{strings.lowExplain}</p>
        {learning && (
          <p className="small muted mt-2">
            <Term name={strings.volatility} description={strings.volatilityExplain} /> — {strings.volatilityExplain}
          </p>
        )}
        <div className="border-t rule mt-4 pt-3 flex flex-wrap gap-2">
          {data.topFactors.slice(0, 3).map((f) => (
            <span className="tag" key={f.label}>{f.direction === 'up' ? '▲' : '▼'} {f.label}</span>
          ))}
        </div>
        {data.pastAccuracy && (
          <p className="small muted mt-4">
            {strings.accuracy.replace('{horizon}', data.pastAccuracy.horizon).replace('{rate}', String(data.pastAccuracy.hitRate))}
          </p>
        )}
      </div>
    );
  }

  return (
    <section id="forecast" aria-labelledby="forecast-heading" className="panel lg:col-span-4">
      <h2 id="forecast-heading" ref={heading} tabIndex={-1}>{strings.forecast}</h2>
      <StatePanel name={strings.forecast} state={state} headingRef={heading}>{body}</StatePanel>
      {/* DRAFT COPY — REQUIRES LEGAL REVIEW BEFORE LAUNCH. */}
      <p className="forecast-label mt-5">{strings.disclaimer}</p>
    </section>
  );
}
