import process from 'node:process';
import { describe, expect, it } from 'vitest';
import config from '../../vite.config.js';

describe('dev proxy', () => {
  const proxy = config.server.proxy['/api'];

  it('sends /api/* to the backend without the prefix', () => {
    expect(proxy.target).toBe(process.env.API_TARGET || 'http://127.0.0.1:8000');
    expect(proxy.rewrite('/api/stocks/NVDA/history?interval=1d')).toBe('/stocks/NVDA/history?interval=1d');
    expect(proxy.rewrite('/api/login')).toBe('/login');
  });
});
