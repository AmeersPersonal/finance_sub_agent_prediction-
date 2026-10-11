// Email/password accounts on the backend (backend/src/oauth/accounts.py), reached
// through the Vite /api proxy. The session is an HttpOnly cookie set by /login.

const FIELD_LABELS = { firstName: 'First name', lastName: 'Last name', email: 'Email', password: 'Password' };

// FastAPI sends `detail` as a string, or for a 422 as a list of { loc, msg }.
export function authErrorMessage(status, detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0];
    const field = FIELD_LABELS[first.loc?.at(-1)];
    const message = String(first.msg || '').replace(/^Value error, /, '');
    if (field === 'Password' && /at least/.test(message)) return 'Password must be at least 8 characters.';
    return field ? `${field}: ${message}` : message;
  }
  if (status >= 500) return 'The server is unavailable right now. Try again shortly.';
  return 'Something went wrong. Try again.';
}

async function post(path, body) {
  let response;
  try {
    response = await fetch(`/api${path}`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error('Can’t reach the server. Is the backend running?');
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(authErrorMessage(response.status, data?.detail));
  return data;
}

/** { user: { sub, email, name, provider } } */
export const signUp = ({ firstName, lastName, email, password }) => post('/signup', { firstName, lastName, email, password });

/** Starts a session (cookie); { user } */
export const signIn = (email, password) => post('/login', { email, password });

/** The signed-in user, or null. */
export async function currentUser() {
  try {
    const response = await fetch('/api/oauth/me', { credentials: 'include' });
    return response.ok ? (await response.json()).user : null;
  } catch {
    return null;
  }
}

export const signOut = () => post('/oauth/logout', {});

export const MIN_PASSWORD = 8;
