import { useEffect, useRef, useState } from "react";
import { strings } from "../strings.js";

export default function UserMenu({ onOpenSettings }) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef(null);
  const menuRef = useRef(null);

  useEffect(() => {
    if (open) menuRef.current?.querySelector("button")?.focus();
  }, [open]);

  function close(restore = true) {
    setOpen(false);
    if (restore) setTimeout(() => buttonRef.current?.focus(), 0);
  }

  function onKeyDown(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab") return;
    const items = [...menuRef.current.querySelectorAll("button")];
    const index = items.indexOf(document.activeElement);
    if (event.shiftKey && index === 0) {
      event.preventDefault();
      items[items.length - 1].focus();
    } else if (!event.shiftKey && index === items.length - 1) {
      event.preventDefault();
      items[0].focus();
    }
  }

  return (
    <div className="userMenu">
      <button
        ref={buttonRef}
        type="button"
        className="avatarButton"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={strings.account}
        onClick={() => (open ? close() : setOpen(true))}
        onKeyDown={(event) => {
          if (event.key === "Escape" && open) {
            event.preventDefault();
            close();
          }
        }}
      >
        M
      </button>
      {open ? (
        <div ref={menuRef} role="menu" aria-label={strings.account} className="menuPanel" onKeyDown={onKeyDown}>
          <p className="menuLabel" role="presentation">
            {strings.signedIn}
          </p>
          <button
            type="button"
            role="menuitem"
            className="menuItem"
            onClick={() => {
              close(false);
              onOpenSettings?.();
            }}
          >
            {strings.readerSettings}
          </button>
          <button type="button" role="menuitem" className="menuItem" onClick={() => close()}>
            {strings.closeMenu}
          </button>
        </div>
      ) : null}
    </div>
  );
}
