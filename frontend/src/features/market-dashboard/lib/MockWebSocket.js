// Simulated live price feed. Emits a random-walk tick for every asset every 250 ms.
// On disconnect it falls back to 5-second polling and retries with exponential backoff (max 30 s).
// Swap this class for a real WebSocket client when a market-data provider is available.
import { assets, base } from '../data/mockData.js';
import { strings } from '../constants/strings.js';
import { publishTick } from './tickStore.js';

export class MockWebSocket {
  timer;
  poll;
  reconnectTimer;
  attempt = 0;
  prices = {};
  connected = true;
  onState = () => {};

  constructor() {
    for (const a of assets) this.prices[a.symbol] = base[a.symbol][0];
    this.start();
  }

  emit() {
    for (const a of assets) {
      const p = this.prices[a.symbol];
      const scale = a.type === 'Crypto' ? 0.00024 : 0.00012;
      this.prices[a.symbol] = Math.max(0.000001, p * (1 + (Math.random() - 0.5) * scale));
      publishTick({ symbol: a.symbol, price: this.prices[a.symbol], at: new Date().toISOString() });
    }
  }

  start() {
    clearInterval(this.timer);
    this.timer = window.setInterval(() => this.emit(), 250);
    this.connected = true;
    this.attempt = 0;
    clearInterval(this.poll);
    this.onState(strings.liveAgain);
  }

  disconnect() {
    clearInterval(this.timer);
    this.connected = false;
    this.onState(strings.disconnected);
    clearInterval(this.poll);
    this.poll = window.setInterval(() => this.emit(), 5000);
    this.schedule();
  }

  schedule() {
    this.onState(strings.reconnecting);
    const delay = Math.min(30000, 1000 * Math.pow(2, this.attempt++));
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = window.setTimeout(() => this.start(), delay);
  }

  reconnect() {
    clearTimeout(this.reconnectTimer);
    this.start();
  }

  stop() {
    clearInterval(this.timer);
    clearInterval(this.poll);
    clearTimeout(this.reconnectTimer);
  }
}
