// Thin client for the backend API (backend/src/api/spec.md). In development the
// Vite proxy serves it under /api; set VITE_API_BASE to call it directly instead.
const BASE = (import.meta.env.VITE_API_BASE || '/api').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(status, message, retryAfter = null) {
    super(message);
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

// FastAPI sends `detail` as a string, or a list of validation errors for a 422.
function detailText(detail, status) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return detail.map((d) => d.msg).join('; ');
  if (status === 502 || status === 503 || status === 504) return 'The backend is unavailable right now. Try again shortly.';
  return `Request failed (${status}).`;
}

async function request(path, { method = 'GET', body, signal } = {}) {
  let response;
  try {
    response = await fetch(BASE + path, {
      method,
      signal,
      credentials: 'include',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError(0, 'Can’t reach the backend. Is the API running on port 8000?');
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const retry = Number(response.headers.get('Retry-After')) || null;
    throw new ApiError(response.status, detailText(data?.detail, response.status), retry);
  }
  return data;
}

const ticker = (symbol) => encodeURIComponent(symbol);

/** Saved price bars, oldest first: [{ bar_at, open, high, low, close, volume, ... }] */
export const getBars = (symbol, interval, limit, signal) =>
  request(`/stocks/${ticker(symbol)}/history?interval=${interval}&limit=${limit}`, { signal }).then((d) => d.bars);

/** Latest saved document versions: [{ id, title, source_url, source_name, excerpt, published_at, ... }] */
export const getNews = (symbol, limit, signal) =>
  request(`/stocks/${ticker(symbol)}/news?limit=${limit}`, { signal }).then((d) => d.documents);

/** The most recent saved forecast for a ticker, or null. */
export const getLatestPrediction = (symbol, signal) =>
  request(`/predictions?ticker=${ticker(symbol)}&limit=1`, { signal }).then((d) => d.predictions[0] || null);

/** Fetch and store prices, company data and documents (no model calls). */
export const refreshTicker = (symbol) => request(`/stocks/${ticker(symbol)}/refresh`, { method: 'POST' });

/** Start a background forecast; poll it with getJob. */
export const startForecast = (symbol, horizonDays = 5) =>
  request('/prediction-jobs', { method: 'POST', body: { ticker: symbol, horizon_days: horizonDays, modes: 'default' } });

/** { job_id, status: queued|running|succeeded|failed, prediction, error } */
export const getJob = (jobId, signal) => request(`/prediction-jobs/${encodeURIComponent(jobId)}`, { signal });
