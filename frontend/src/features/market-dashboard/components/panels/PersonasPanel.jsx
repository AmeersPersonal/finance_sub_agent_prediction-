// "How the personas voted": each trader persona's call, conviction and reasoning
// from the latest saved forecast.
import { useRef } from 'react';
import { strings } from '../../constants/strings.js';
import { DIRECTIONS, STRATEGY_LABELS } from '../../constants/options.js';
import StatePanel from '../ui/StatePanel.jsx';

const ORDER = Object.keys(STRATEGY_LABELS);

export default function PersonasPanel({ state }) {
  const heading = useRef(null);
  const personas = (state.data?.prediction?.personas || [])
    .slice()
    .sort((a, b) => ORDER.indexOf(a.strategy) - ORDER.indexOf(b.strategy) || a.age_band.localeCompare(b.age_band));

  return (
    <section id="personas" aria-labelledby="personas-heading" className="panel lg:col-span-4">
      <h2 id="personas-heading" ref={heading} tabIndex={-1}>{strings.personas}</h2>
      <StatePanel name={strings.personas} state={state} headingRef={heading}>
        {personas.length ? (
          <div className="max-h-[460px] overflow-y-auto pr-1" tabIndex={0} aria-label="Persona votes">
            {personas.map((p) => {
              const [arrow, label, tone] = DIRECTIONS[p.view?.direction] || DIRECTIONS.unclear;
              return (
                <article key={`${p.persona_id}-${p.mode}`} className="line-row">
                  <div className="flex justify-between gap-2">
                    <strong className="small">{STRATEGY_LABELS[p.strategy] || p.strategy} · age {p.age_band}</strong>
                    {p.view
                      ? <span className={`mono small ${tone}`}>{arrow} {label} · {Math.round(p.view.conviction * 100)}%</span>
                      : <span className="small muted">no answer</span>}
                  </div>
                  <p className="small mt-1">{p.view?.rationale || p.error || strings.personaFailed}</p>
                </article>
              );
            })}
          </div>
        ) : <p className="muted">{strings.noPersonas}</p>}
      </StatePanel>
    </section>
  );
}
