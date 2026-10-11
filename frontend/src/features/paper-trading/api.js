// Paper-trading calls to the backend (`/paper/*`). Simulated: no real money moves.
// Base URL: VITE_API_BASE_URL, else the backend's default development address. The
// sign-in session is a cookie, so every request sends credentials.
const BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '');

export const loginUrl = `${BASE}/oauth/login`;

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${BASE}${path}`, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
  } catch {
    throw new ApiError(0, 'Could not reach the server. Is the backend running?');
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    // Our own rejections carry a readable string; request-validation errors are a list.
    const detail = typeof body?.detail === 'string' ? body.detail : null;
    if (detail) throw new ApiError(response.status, detail);
    if (response.status === 401) throw new ApiError(401, 'Sign in to use paper trading.');
    if (response.status === 422) throw new ApiError(422, 'Check the order and try again.');
    throw new ApiError(response.status, `Request failed (${response.status}). Try again shortly.`);
  }
  return body;
}

export const getAccount = () => request('/paper/account');
export const getOrders = (limit = 50) => request(`/paper/orders?limit=${limit}`);
export const resetAccount = () => request('/paper/reset', { method: 'POST' });
export const placeOrder = (order) => request('/paper/orders', { method: 'POST', body: JSON.stringify(order) });

/** The newest saved daily bar, or null when nothing is saved for the ticker. */
export async function getLatestBar(ticker) {
  const { bars } = await request(`/stocks/${encodeURIComponent(ticker)}/history?interval=1d&limit=1`);
  const bar = bars.at(-1);
  return bar ? { price: Number(bar.close), asOf: bar.bar_at } : null;
}

/** Fetch and save prices and sources for a ticker (no model calls). */
export const refreshPrices = (ticker) =>
  request(`/stocks/${encodeURIComponent(ticker)}/refresh`, { method: 'POST' });
