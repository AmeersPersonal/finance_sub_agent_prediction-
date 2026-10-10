// Upcoming economic events and why each can move markets.
import { useRef } from 'react';
import { strings } from '../../constants/strings.js';
import { timeText } from '../../lib/format.js';
import StatePanel from '../ui/StatePanel.jsx';

export default function CalendarPanel({ state }) {
  const heading = useRef(null);

  return (
    <section aria-labelledby="calendar-heading" className="panel lg:col-span-4">
      <h2 id="calendar-heading" ref={heading} tabIndex={-1}>{strings.calendar}</h2>
      <StatePanel name={strings.calendar} state={state} headingRef={heading}>
        {state.data?.length ? state.data.slice(0, 5).map((e) => (
          <div className="line-row" key={e.id}>
            <div className="font-semibold">{e.title}</div>
            <time className="mono small muted" dateTime={e.time}>{timeText(e.time)}</time>
            <p className="small mt-1">Why this can move markets: {e.reason}</p>
          </div>
        )) : <p className="muted">{strings.noCalendar}</p>}
      </StatePanel>
    </section>
  );
}
