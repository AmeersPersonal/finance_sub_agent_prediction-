// Toggletip for explaining a financial term (e.g. "Market cap").
// Only one toggletip is open at a time — tracked in UIContext.
import { useUI } from '../../context/UIContext.js';

export default function Term({ name, description }) {
  const ui = useUI();
  const id = `tip-${name.replace(/\W/g, '-')}`;
  const open = ui.tip === id;

  return (
    <span className="relative inline-block">
      <button
        type="button"
        className="accent underline underline-offset-4 min-h-[28px]"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => ui.setTip(open ? null : id)}
        onKeyDown={(e) => { if (e.key === 'Escape') { ui.setTip(null); e.stopPropagation(); } }}
        onBlur={(e) => { if (!e.currentTarget.parentElement.contains(e.relatedTarget)) ui.setTip(null); }}
      >
        {name}
      </button>
      {open && <span id={id} role="note" className="tip small">{description}</span>}
    </span>
  );
}
