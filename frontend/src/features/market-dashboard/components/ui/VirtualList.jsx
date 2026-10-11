// Fixed-row-height virtualized list: only renders rows in view (plus 3 rows of overscan).
import { useState, useEffect, useRef } from 'react';

export default function VirtualList({ items, rowHeight, render, ariaLabel }) {
  const [scroll, setScroll] = useState(0);
  const [height, setHeight] = useState(330);
  const viewport = useRef(null);

  useEffect(() => {
    if (!viewport.current) return undefined;
    const observer = new ResizeObserver((entries) => setHeight(entries[0].contentRect.height));
    observer.observe(viewport.current);
    return () => observer.disconnect();
  }, []);

  const start = Math.max(0, Math.floor(scroll / rowHeight) - 3);
  const end = Math.min(items.length, Math.ceil((scroll + height) / rowHeight) + 3);

  return (
    <div ref={viewport} className="virtual-scroll" aria-label={ariaLabel} onScroll={(e) => setScroll(e.currentTarget.scrollTop)}>
      <div style={{ height: items.length * rowHeight, position: 'relative' }}>
        {items.slice(start, end).map((item, i) => (
          <div
            key={start + i}
            style={{ position: 'absolute', top: (start + i) * rowHeight, height: rowHeight, width: '100%', overflow: 'hidden' }}
          >
            {render(item, start + i)}
          </div>
        ))}
      </div>
    </div>
  );
}
