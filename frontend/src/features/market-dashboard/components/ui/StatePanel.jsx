// Renders loading / error / empty / stale states for a resource, or its children on success.
// `onLoad` adds a button to the empty state that fetches the ticker's data.
import { strings } from '../../constants/strings.js';
import { timeText } from '../../lib/format.js';

export default function StatePanel({ name, state, headingRef, children, onLoad, emptyText = strings.empty }) {
  if (state.status === 'loading') {
    return (
      <div aria-busy="true" className="space-y-3" style={{ minHeight: 145 }}>
        <span className="sr-only">{strings.loading} {name}</span>
        <div className="skeleton h-5 w-3/4" />
        <div className="skeleton h-4 w-full" />
        <div className="skeleton h-4 w-2/3" />
      </div>
    );
  }

  if (state.status === 'error') {
    return (
      <div role="status" className="space-y-3">
        <p>{strings.error}</p>
        {state.error?.message && <p className="small muted">{state.error.message}</p>}
        <button
          className="action"
          onClick={() => { state.refetch(); setTimeout(() => headingRef?.current?.focus(), 0); }}
        >
          {strings.retry}
        </button>
      </div>
    );
  }

  if (state.status === 'empty') {
    return (
      <div>
        <p className="muted">{emptyText}</p>
        {onLoad && <button className="action primary mt-3" onClick={onLoad}>{strings.loadData}</button>}
      </div>
    );
  }

  return (
    <>
      {state.isStale && <p className="small muted mb-3">{strings.stale}{state.asOf && ` · ${timeText(state.asOf)}`}</p>}
      {children}
    </>
  );
}
