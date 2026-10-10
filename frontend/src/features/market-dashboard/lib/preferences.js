// Reader preferences live in localStorage only — no account endpoint is implied.
const STORAGE_KEY = 'mmd-preferences';

/** UserPreferences: { theme: 'light'|'dark', learning: boolean, watchlist: [{ symbol, addedAt }], sessions: number } */
export function loadPreferences() {
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); } catch { /* ignore */ }
  const sessions = (Number(stored.sessions) || 0) + 1;
  const theme = stored.theme === 'light' || stored.theme === 'dark'
    ? stored.theme
    : (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  // Learning mode defaults on for a reader's first five sessions.
  const learning = typeof stored.learning === 'boolean' ? stored.learning : sessions <= 5;
  const watchlist = Array.isArray(stored.watchlist)
    ? stored.watchlist
    : ['NVDA', 'AAPL', 'VOO', 'BTC', 'OTLK'].map((symbol) => ({ symbol, addedAt: '2026-10-10T00:00:00Z' }));
  const result = { theme, learning, watchlist, sessions };
  savePreferences(result);
  return result;
}

export function savePreferences(preferences) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences)); } catch { /* ignore */ }
}

export async function mockServerSync() {
  // Deliberately local-only: no account endpoint or remote persistence is implied.
  return { ok: true };
}
