import { useId, useRef, useState } from "react";
import { strings } from "../strings.js";

export default function GlossaryToggletip({ term }) {
  const entry = strings.glossary[term];
  const tipId = useId();
  const buttonRef = useRef(null);
  const [open, setOpen] = useState(false);

  function close() {
    setOpen(false);
  }

  function onButtonKeyDown(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
      buttonRef.current?.focus();
    }
  }

  function onButtonBlur(event) {
    if (!event.currentTarget.parentElement.contains(event.relatedTarget)) close();
  }

  return (
    <span className="toggletip">
      <button
        ref={buttonRef}
        type="button"
        className="toggletipButton"
        aria-expanded={open}
        aria-controls={tipId}
        aria-describedby={open ? tipId : undefined}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={onButtonKeyDown}
        onBlur={onButtonBlur}
      >
        {entry.label}
      </button>
      {open ? (
        <span
          id={tipId}
          role="note"
          tabIndex={-1}
          className="toggletipPanel"
          onKeyDown={onButtonKeyDown}
          onBlur={onButtonBlur}
        >
          {entry.definition}
        </span>
      ) : null}
    </span>
  );
}
