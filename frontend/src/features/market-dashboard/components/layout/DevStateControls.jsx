// Dev-only control to preview loading, error, empty, stale and other edge states.
// Remove (or hide behind an env flag) before shipping.
import { strings } from '../../constants/strings.js';
import { PREVIEW_STATES } from '../../constants/options.js';

export default function DevStateControls({ override, setOverride }) {
  return (
    <section aria-labelledby="dev-heading" className="panel mb-8">
      <h2 id="dev-heading">{strings.dev}</h2>
      <p className="small muted mb-3">{strings.devHelp}</p>
      <label htmlFor="dev-state" className="font-semibold mr-3">Preview state</label>
      <select id="dev-state" className="action max-w-full" value={override} onChange={(e) => setOverride(e.target.value)}>
        {PREVIEW_STATES.map((v) => <option key={v} value={v}>{v.replaceAll('_', ' ')}</option>)}
      </select>
    </section>
  );
}
