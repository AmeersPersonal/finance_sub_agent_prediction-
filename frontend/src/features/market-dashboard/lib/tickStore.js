// A tiny external store for live price ticks.
// Ticks are batched per animation frame and throttled to one update per symbol per second,
// so components subscribed via useTick() re-render at most once a second.
import { useCallback, useSyncExternalStore } from 'react';

export const tickValues = {};
const tickListeners = {};
const lastPublished = {};
const pending = {};
let frame = 0;
const emptyTick = { symbol: '', price: 0, at: '' };

function flush() {
  frame = 0;
  const now = Date.now();
  for (const symbol of Object.keys(pending)) {
    if (now - (lastPublished[symbol] || 0) < 1000) continue;
    tickValues[symbol] = pending[symbol];
    delete pending[symbol];
    lastPublished[symbol] = now;
    tickListeners[symbol]?.forEach((listener) => listener());
  }
}

/** Tick: { symbol, price, at } */
export function publishTick(tick) {
  pending[tick.symbol] = tick;
  if (frame) return;
  frame = requestAnimationFrame(() => {
    flush();
    if (Object.keys(pending).length) {
      setTimeout(() => { if (!frame) frame = requestAnimationFrame(flush); }, 1000);
    }
  });
}

export function tickSubscribe(symbol, listener) {
  (tickListeners[symbol] ??= new Set()).add(listener);
  return () => tickListeners[symbol]?.delete(listener);
}

export function useTick(symbol) {
  const subscribe = useCallback((listener) => tickSubscribe(symbol, listener), [symbol]);
  const snapshot = useCallback(() => tickValues[symbol] || emptyTick, [symbol]);
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
