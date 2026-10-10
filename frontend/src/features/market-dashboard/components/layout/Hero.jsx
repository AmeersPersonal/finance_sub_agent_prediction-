// Welcome heading plus the live-feed connection status and demo disconnect button.
import { strings } from '../../constants/strings.js';

export default function Hero({ connection, feed }) {
  const connected = feed.current?.connected;
  return (
    <div className="flex justify-between flex-wrap gap-3 py-5">
      <div>
        <p className="eyebrow">THE MARKET, EXPLAINED</p>
        <p className="serif text-[clamp(1.5rem,2.8vw,2.35rem)] leading-tight">{strings.welcome}</p>
        <h1 className="serif text-[clamp(2rem,4vw,3.4rem)] leading-tight">{strings.welcomeQuestion}</h1>
        <p className="muted small mt-1">{strings.educational} {strings.mock}</p>
      </div>
      <div className="self-end small" role="status" aria-live="polite">
        <span className="live-dot" aria-hidden="true" />
        {connection}
        <button
          className="action ml-2 small"
          onClick={() => (connected ? feed.current.disconnect() : feed.current?.reconnect())}
        >
          {connected ? strings.disconnect : strings.connect}
        </button>
      </div>
    </div>
  );
}
