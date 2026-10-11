import { describe, expect, it } from 'vitest';
import { authErrorMessage, currentUser, signIn, signOut, signUp } from './auth.js';
import { installFakeBackend, json } from '../test/fakeBackend.js';

describe('authErrorMessage', () => {
  it('passes the backend’s message through', () => {
    expect(authErrorMessage(401, 'Invalid email or password.')).toBe('Invalid email or password.');
    expect(authErrorMessage(409, 'An account with this email already exists. Sign in instead.')).toMatch(/already exists/);
  });

  it('names the field for validation errors', () => {
    expect(authErrorMessage(422, [{ loc: ['body', 'email'], msg: 'Value error, Enter a valid email address.' }]))
      .toBe('Email: Enter a valid email address.');
    expect(authErrorMessage(422, [{ loc: ['body', 'password'], msg: 'String should have at least 8 characters' }]))
      .toBe('Password must be at least 8 characters.');
    expect(authErrorMessage(422, [{ loc: ['body', 'firstName'], msg: 'Field required' }])).toBe('First name: Field required');
    expect(authErrorMessage(422, [{ loc: ['body'], msg: 'JSON decode error' }])).toBe('JSON decode error');
  });

  it('has fallbacks', () => {
    expect(authErrorMessage(503, undefined)).toMatch(/unavailable/);
    expect(authErrorMessage(400, undefined)).toBe('Something went wrong. Try again.');
  });
});

describe('requests', () => {
  it('signs up and in with the fields the backend expects, sending the cookie', async () => {
    const backend = installFakeBackend();
    backend.respond = (method, path) => (path === '/signup' ? json({ user: { email: 'm@x.io' } }, 201)
      : path === '/login' ? json({ user: { email: 'm@x.io' } }) : null);
    await signUp({ firstName: 'Maya', lastName: 'Lopez', email: 'm@x.io', password: 'longenough', confirm: 'longenough' });
    await signIn('m@x.io', 'longenough');
    expect(backend.calls.map((c) => [c.method, c.path, c.body, c.init.credentials])).toEqual([
      ['POST', '/signup', { firstName: 'Maya', lastName: 'Lopez', email: 'm@x.io', password: 'longenough' }, 'include'],
      ['POST', '/login', { email: 'm@x.io', password: 'longenough' }, 'include'],
    ]);
  });

  it('throws the readable message on failure', async () => {
    installFakeBackend().respond = () => json({ detail: 'Invalid email or password.' }, 401);
    await expect(signIn('m@x.io', 'nope')).rejects.toThrow('Invalid email or password.');
  });

  it('explains an unreachable backend', async () => {
    installFakeBackend().down = true;
    await expect(signIn('m@x.io', 'x')).rejects.toThrow('Can’t reach the server. Is the backend running?');
  });

  it('reads the current user, or null when signed out or offline', async () => {
    const backend = installFakeBackend();
    expect(await currentUser()).toBeNull();
    backend.user = { name: 'Maya' };
    expect(await currentUser()).toEqual({ name: 'Maya' });
    backend.down = true;
    expect(await currentUser()).toBeNull();
  });

  it('signs out through the OAuth logout route', async () => {
    const backend = installFakeBackend();
    backend.respond = (method, path) => (path === '/oauth/logout' ? json({ signed_out: true }) : null);
    await signOut();
    expect(backend.calls[0]).toMatchObject({ method: 'POST', path: '/oauth/logout' });
  });
});
