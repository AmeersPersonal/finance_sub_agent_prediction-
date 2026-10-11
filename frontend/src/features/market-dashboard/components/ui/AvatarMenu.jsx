// Account menu button: who is signed in (GET /oauth/me) and sign in / sign out.
// Focus moves into the menu on open, is trapped while open, and returns to the button on close.
import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { strings } from '../../constants/strings.js';
import { currentUser, signOut } from '../../../../lib/auth.js';

export default function AvatarMenu() {
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState(null);
  const button = useRef(null);
  const menu = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    let active = true;
    currentUser().then((u) => { if (active) setUser(u); });
    return () => { active = false; };
  }, []);

  async function leave() {
    try { await signOut(); } catch { /* the session is gone either way once the cookie expires */ }
    setUser(null);
    navigate('/signin');
  }

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
        {user?.name?.trim()?.[0]?.toUpperCase() || '?'}
      </button>
      {open && (
        <div ref={menu} role="menu" aria-label={strings.account} className="menu" onKeyDown={onKeyDown}>
          <div className="px-2 py-2 small muted">
            {user ? <><strong className="block">{user.name}</strong>{user.email}</> : strings.notSignedIn}
          </div>
          {user
            ? <button role="menuitem" className="action w-full text-left" onClick={leave}>{strings.signOut}</button>
            : <button role="menuitem" className="action w-full text-left" onClick={() => navigate('/signin')}>{strings.signIn}</button>}
          <button role="menuitem" className="action w-full text-left mt-1" onClick={close}>{strings.close}</button>
        </div>
      )}
    </div>
  );
}
