// Account menu button. Focus moves into the menu on open, is trapped while open,
// and returns to the button on close.
import { useState, useEffect, useRef } from 'react';
import { strings } from '../../constants/strings.js';

export default function AvatarMenu() {
  const [open, setOpen] = useState(false);
  const button = useRef(null);
  const menu = useRef(null);

  useEffect(() => {
    if (open) menu.current?.querySelector('button')?.focus();
  }, [open]);

  function close() {
    setOpen(false);
    setTimeout(() => button.current?.focus(), 0);
  }

  function onKeyDown(e) {
    if (e.key === 'Escape') { e.preventDefault(); close(); }
    if (e.key === 'Tab') {
      const items = [...menu.current.querySelectorAll('button')];
      const at = items.indexOf(document.activeElement);
      if (e.shiftKey && at === 0) { e.preventDefault(); items[items.length - 1].focus(); }
      else if (!e.shiftKey && at === items.length - 1) { e.preventDefault(); items[0].focus(); }
    }
  }

  return (
    <div className="relative">
      <button
        ref={button}
        type="button"
        className="action rounded-full !w-10 !h-10 !p-0 font-bold"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={strings.account}
        onClick={() => (open ? close() : setOpen(true))}
      >
        M
      </button>
      {open && (
        <div ref={menu} role="menu" aria-label={strings.account} className="menu" onKeyDown={onKeyDown}>
          <div className="px-2 py-2 small muted">{strings.signedIn}</div>
          <button role="menuitem" className="action w-full text-left" onClick={close}>{strings.settings}</button>
          <button role="menuitem" className="action w-full text-left mt-1" onClick={close}>{strings.close}</button>
        </div>
      )}
    </div>
  );
}
