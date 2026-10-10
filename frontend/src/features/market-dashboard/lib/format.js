export const percent = (price, previous) => ((price - previous) / previous) * 100;

export const signed = (n, d = 1) => `${n >= 0 ? '+' : '−'}${Math.abs(n).toFixed(d)}%`;

export const money = (v) => new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: v < 1 ? 6 : 2,
  maximumFractionDigits: v < 1 ? 8 : v < 10 ? 6 : 2,
}).format(v);

export const compact = (v) => new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(v);

export const dateText = (iso) => new Intl.DateTimeFormat('en-US', {
  month: 'short', day: 'numeric', timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
}).format(new Date(iso));

export const timeText = (iso) => new Intl.DateTimeFormat('en-US', {
  month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
}).format(new Date(iso));
