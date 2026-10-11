// "Why it moved": the three largest explained moves for the selected asset.
import { useState, useEffect, useMemo } from 'react';
import { strings } from '../../constants/strings.js';
import { events } from '../../data/mockData.js';
import { dateText, signed } from '../../lib/format.js';
import { calculateMoves } from '../../lib/calculateMoves.js';
import StatePanel from '../ui/StatePanel.jsx';

export default function WhyPanel({ asset, history, selectedEvent, setSelectedEvent }) {
  const [ids, setIds] = useState([]);
  const available = useMemo(() => events.filter((e) => e.symbol === asset.symbol), [asset.symbol]);

  useEffect(() => {
    let active = true;
    calculateMoves({ id: Date.now(), points: history.data || [], events: available })
      .then((r) => { if (active) setIds(r.eventIds); });
    return () => { active = false; };
  }, [history.data, available]);

  const biggest = useMemo(() => ids.map((id) => available.find((e) => e.id === id)).filter(Boolean), [ids, available]);

  return (
    <section id="why" aria-labelledby="why-heading" className="panel lg:col-span-4">
      <h2 id="why-heading">{strings.why}</h2>
      <StatePanel name={strings.why} state={history}>
        {biggest.length ? biggest.map((e) => (
          <button
            key={e.id}
            className="line-row w-full text-left block hover:opacity-75"
            aria-pressed={selectedEvent === e.id}
            onClick={() => { setSelectedEvent(e.id); document.getElementById('chart')?.scrollIntoView({ block: 'nearest' }); }}
          >
            <span className="flex justify-between gap-2">
              <strong>{dateText(e.t)} · {e.category}</strong>
              <span className={`mono ${e.change >= 0 ? 'up' : 'down'}`}>{e.change >= 0 ? '▲' : '▼'} {signed(e.change)}</span>
            </span>
            <span className="block small muted mt-1">{e.explanation}</span>
          </button>
        )) : <p className="muted">{strings.empty}</p>}
      </StatePanel>
    </section>
  );
}
