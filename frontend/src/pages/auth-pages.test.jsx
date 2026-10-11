// The sign-in and sign-up pages against a fake backend.
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';
import Signin from './Signin.jsx';
import Signup from './Signup.jsx';
import { installFakeBackend, json } from '../test/fakeBackend.js';

function Location() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/signin" element={<Signin />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/dashboard" element={<p>Dashboard page</p>} />
      </Routes>
      <Location />
    </MemoryRouter>,
  );
}

const confirm = () => userEvent.click(screen.getByRole('button', { name: 'CONFIRM' }));
let backend;
beforeEach(() => { backend = installFakeBackend(); });

describe('sign-in page', () => {
  async function signIn(email, password) {
    renderAt('/signin');
    if (email) await userEvent.type(screen.getByLabelText('EMAIL'), email);
    if (password) await userEvent.type(screen.getByLabelText('PASSWORD'), password);
    await confirm();
  }

  it('goes to the dashboard once the password is accepted', async () => {
    backend.respond = (method, path) => (path === '/login' ? json({ user: { email: 'maya@example.com' } }) : null);
    await signIn('maya@example.com', 'correct horse');
    expect(await screen.findByText('Dashboard page')).toBeInTheDocument();
    expect(backend.calls[0]).toMatchObject({ method: 'POST', path: '/login', body: { email: 'maya@example.com', password: 'correct horse' } });
  });

  it('stays and shows the error for a wrong password', async () => {
    backend.respond = () => json({ detail: 'Invalid email or password.' }, 401);
    await signIn('maya@example.com', 'wrong');
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password.');
    expect(screen.queryByText('Dashboard page')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'CONFIRM' })).toBeEnabled();
  });

  it('shows the attempt limit', async () => {
    backend.respond = () => json({ detail: 'Too many attempts. Try again in 15 min.' }, 429, { 'Retry-After': '900' });
    await signIn('maya@example.com', 'wrong');
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many attempts. Try again in 15 min.');
  });

  it('needs both fields before calling the backend', async () => {
    await signIn('maya@example.com', '');
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter your email and password');
    expect(backend.calls).toHaveLength(0);
  });

  it('explains an unreachable backend', async () => {
    backend.down = true;
    await signIn('maya@example.com', 'correct horse');
    expect(await screen.findByRole('alert')).toHaveTextContent('Can’t reach the server');
  });
});

describe('sign-up page', () => {
  const fill = async ({ firstName = 'Maya', lastName = 'Lopez', email = 'maya@example.com', password = 'correct horse', confirmed = password } = {}) => {
    renderAt('/signup');
    for (const [label, value] of [['FIRST NAME', firstName], ['LAST NAME', lastName], ['EMAIL', email], ['PASSWORD', password], ['CONFIRM PASSWORD', confirmed]]) {
      if (value) await userEvent.type(screen.getByLabelText(label), value);
    }
    await confirm();
  };

  it('creates the account with the fields the backend expects, then asks to sign in', async () => {
    backend.respond = (method, path) => (path === '/signup' ? json({ user: {} }, 201) : null);
    await fill();
    // Wait for the move to the sign-in page itself; its fields can't be told apart from sign-up's mid-render.
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/signin'));
    expect(screen.queryByLabelText('CONFIRM PASSWORD')).not.toBeInTheDocument();
    expect(backend.calls[0]).toMatchObject({
      method: 'POST', path: '/signup',
      body: { firstName: 'Maya', lastName: 'Lopez', email: 'maya@example.com', password: 'correct horse' },
    });
  });

  it.each([
    [{ lastName: '' }, 'Please fill in every box'],
    [{ password: 'short', confirmed: 'short' }, 'Password must be at least 8 characters'],
    [{ confirmed: 'something else' }, 'Passwords don\'t match'],
  ])('checks %o before calling the backend', async (fields, message) => {
    await fill(fields);
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(backend.calls).toHaveLength(0);
  });

  it.each([
    [409, { detail: 'An account with this email already exists. Sign in instead.' }, 'An account with this email already exists. Sign in instead.'],
    [422, { detail: [{ loc: ['body', 'email'], msg: 'Value error, Enter a valid email address.' }] }, 'Email: Enter a valid email address.'],
    [503, { detail: 'Database unavailable. Check its connection and migrations.' }, 'Database unavailable'],
  ])('shows the backend’s %i', async (status, body, message) => {
    backend.respond = () => json(body, status);
    await fill();
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(screen.getByLabelText('CONFIRM PASSWORD')).toBeInTheDocument(); // still on sign-up
  });
});
