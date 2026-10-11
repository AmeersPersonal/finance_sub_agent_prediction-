// Works out the US market session (in New York time) for an asset.
// Crypto is always open; preview overrides can force 'halted' or 'closed'.
export function marketStatus(asset, quote, override) {
  if (override === 'halted' && asset.type === 'Stock') return 'halted';
  if (asset.type === 'Crypto') return 'open';
  if (override === 'market_closed') return 'closed';

  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', weekday: 'short', hour: 'numeric', minute: 'numeric',
    hour12: false, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date());
  const part = (type) => parts.find((p) => p.type === type)?.value || '';
  const day = part('weekday');
  const md = `${part('month')}-${part('day')}`;
  const minutes = Number(part('hour')) * 60 + Number(part('minute'));

  if (day === 'Sat' || day === 'Sun') return 'weekend';
  if (['01-01', '07-04', '12-25'].includes(md)) return 'holiday';
  if (['11-27', '12-24'].includes(md) && minutes >= 570 && minutes < 780) return 'half-day';
  if (minutes < 570) return minutes >= 240 ? 'pre-market' : 'closed';
  if (minutes < 960) return 'open';
  return minutes < 1200 ? 'after-hours' : 'closed';
}
