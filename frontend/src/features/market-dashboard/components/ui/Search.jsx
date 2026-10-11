// Ticker search combobox (ARIA combobox + listbox with active descendant).
import { useState, useMemo, useRef } from 'react';
import { strings } from '../../constants/strings.js';
import { assets, base } from '../../data/mockData.js';
import { percent, signed } from '../../lib/format.js';

export default function Search({ symbol, onSelect }) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef(null);

  const matches = useMemo(() => {
    const q = query.toLowerCase();
    return assets.filter((a) => a.name.toLowerCase().includes(q) || a.symbol.toLowerCase().includes(q)).slice(0, 8);
  }, [query]);

  function choose(a) {
    onSelect(a.symbol);
    setQuery('');
    setOpen(false);
    input.current?.focus();
  }

  function onKeyDown(e) {
    if (e.key === 'Escape') { setOpen(false); return; }
    if (!open) return;
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) {
      e.preventDefault();
      setActive((n) => (
        e.key === 'Home' ? 0
          : e.key === 'End' ? matches.length - 1
            : e.key === 'ArrowDown' ? (n + 1) % matches.length
              : (n + matches.length - 1) % matches.length
      ));
    }
    if (e.key === 'Enter' && matches[active]) { e.preventDefault(); choose(matches[active]); }
  }

  return (
    <div className="relative w-full max-w-sm">
      <label className="sr-only" htmlFor="ticker-search">{strings.search}</label>
      <input
        ref={input}
        id="ticker-search"
        className="action w-full"
        role="combobox"
        autoComplete="off"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls="ticker-results"
        aria-activedescendant={open && matches[active] ? `ticker-${matches[active].symbol}` : undefined}
        value={query}
        placeholder={`${strings.search} · ${symbol}`}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); setActive(0); }}
        onFocus={() => setOpen(true)}
        onBlur={(e) => { if (!e.currentTarget.parentElement.contains(e.relatedTarget)) setTimeout(() => setOpen(false), 120); }}
        onKeyDown={onKeyDown}
      />
      <span className="sr-only">{strings.searchHint}</span>
      {open && matches.length > 0 && (
        <div id="ticker-results" role="listbox" className="absolute z-30 top-full mt-1 w-full max-h-72 overflow-auto panel !p-1">
          {matches.map((a, i) => (
            <button
              type="button"
              id={`ticker-${a.symbol}`}
              key={a.symbol}
              role="option"
              aria-selected={i === active}
              className="block w-full text-left px-3 py-2 rounded hover:bg-black/5"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(a)}
            >
              {a.name} · {a.symbol} <span className="tag">{a.type}</span> · {signed(percent(base[a.symbol][0], base[a.symbol][1]))}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
