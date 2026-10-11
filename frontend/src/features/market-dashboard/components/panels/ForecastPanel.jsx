// "What might happen next": the latest saved persona forecast, and a button that runs a
// new one in the background (10-60 s). Confidence is signal strength, never a probability.
import { useEffect, useRef, useState } from 'react';
import { strings } from '../../constants/strings.js';
import { DIRECTIONS, STRATEGY_LABELS } from '../../constants/options.js';
import { money, dateText } from '../../lib/format.js';
import StatePanel from '../ui/StatePanel.jsx';
import Term from '../ui/Term.jsx';

const RUNNING = ['starting', 'queued', 'running'];

function callSentence(p) {
  const band = `${p.flat_band_pct.toFixed(1)}%`;
  const window = `${p.horizon_days} trading day${p.horizon_days === 1 ? '' : 's'}`;
  if (p.direction === 'flat') return `Personas expect ${p.ticker} to stay within ±${band} of ${money(p.last_price)} over ${window}.`;
  if (p.direction === 'up') return `Personas lean toward a rise of more than ${band} from ${money(p.last_price)} over ${window}.`;
  if (p.direction === 'down') return `Personas lean toward a fall of more than ${band} from ${money(p.last_price)} over ${window}.`;
  return 'Personas split or leaned only weakly, so there is no call.';
}

function Elapsed({ since }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return <>{Math.max(0, Math.round((now - since) / 1000))} s</>;
}

export default function ForecastPanel({ state, job, learning }) {
  const heading = useRef(null);
  const p = state.data?.prediction;
  const running = RUNNING.includes(job.status);

  let body = <p>{strings.noForecast}</p>;
  if (p) {
    const [arrow, label, tone] = DIRECTIONS[p.direction] || DIRECTIONS.unclear;
    const voters = p.personas.filter((x) => x.view).length;
    const agree = Math.round(p.agreement * voters);
    body = (
      <div>
        <div className="eyebrow mb-2">{p.horizon_days}-TRADING-DAY CALL · {dateText(p.generated_at)}</div>
        <p className={`serif text-3xl ${tone}`}>{arrow} {label}</p>
        <p className="small mt-1">
          <Term name={strings.strength} description={strings.strengthExplain} /> {Math.round(p.confidence * 100)}% · {agree} of {voters} personas agree
        </p>
        {learning && <p className="small muted mt-1">{strings.strengthExplain}</p>}
        <p className="mt-3">{callSentence(p)}</p>

        <div className="border-t rule mt-4 pt-3 space-y-1">
          {Object.entries(p.by_strategy).map(([strategy, score]) => (
            <div key={strategy} className="flex justify-between gap-2 small">
              <span>{STRATEGY_LABELS[strategy] || strategy}</span>
              <span className={`mono ${score > 0 ? 'up' : score < 0 ? 'down' : ''}`}>{score >= 0 ? '+' : '−'}{Math.abs(score).toFixed(2)}</span>
            </div>
          ))}
          {learning && <p className="small muted">{strings.netScoreExplain}</p>}
        </div>

        <p className="small muted mt-3">
          Simple baselines: always-up says {p.baselines.always_up}, momentum says {p.baselines.momentum}
          {p.baselines.linear_regression && `, the regression says ${p.baselines.linear_regression}`}.
        </p>
        {p.earnings_within_horizon && p.next_earnings_date && (
          <p className="small mt-2">Earnings on {dateText(`${p.next_earnings_date}T12:00:00Z`)} fall inside this window, so bigger swings are possible.</p>
        )}
        {!p.earnings_within_horizon && p.next_earnings_date && (
          <p className="small muted mt-2">Next earnings: {dateText(`${p.next_earnings_date}T12:00:00Z`)}</p>
        )}
      </div>
    );
  }

  return (
    <section id="forecast" aria-labelledby="forecast-heading" className="panel lg:col-span-4">
      <h2 id="forecast-heading" ref={heading} tabIndex={-1}>{strings.forecast}</h2>
      <StatePanel name={strings.forecast} state={state} headingRef={heading}>
        {body}
        <div className="mt-4" role="status" aria-live="polite">
          {running ? (
            <p className="small">{strings.forecastRunning} <span className="mono">{job.startedAt && <Elapsed since={job.startedAt} />}</span></p>
          ) : (
            <button className="action primary" onClick={() => job.start(5)}>{p ? strings.runAgain : strings.runFirst}</button>
          )}
          {job.status === 'failed' && <p className="small down mt-2">{job.error}</p>}
        </div>
      </StatePanel>
      {/* DRAFT COPY — REQUIRES LEGAL REVIEW BEFORE LAUNCH. */}
      <p className="forecast-label mt-5">{strings.disclaimer}</p>
    </section>
  );
}
