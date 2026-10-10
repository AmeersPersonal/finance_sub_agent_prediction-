// Top bar: product name, ticker search, learning-mode switch, theme toggle, account menu.
import { strings } from '../../constants/strings.js';
import Search from '../ui/Search.jsx';
import AvatarMenu from '../ui/AvatarMenu.jsx';

export default function Header({ symbol, onSelect, prefs, setPrefs }) {
  return (
    <header className="w-full border-b rule bg-[var(--panel)]">
      <div className="max-w-[1440px] mx-auto px-4 md:px-8 py-4 flex items-center gap-4 flex-wrap">
        <div className="serif font-bold text-[1.35rem] whitespace-nowrap">{strings.product}</div>
        <nav aria-label="Asset search" className="flex-1 min-w-[210px]">
          <Search symbol={symbol} onSelect={onSelect} />
        </nav>
        <div className="small muted hidden xl:block">{strings.usHours}</div>
        <label className="flex items-center gap-2 small cursor-pointer">
          <input
            type="checkbox"
            role="switch"
            checked={prefs.learning}
            onChange={(e) => setPrefs((p) => ({ ...p, learning: e.target.checked }))}
            className="w-5 h-5 accent-[var(--accent)]"
          />
          {strings.learning}
        </label>
        <button
          className="action small"
          onClick={() => setPrefs((p) => ({ ...p, theme: p.theme === 'light' ? 'dark' : 'light' }))}
          aria-label={strings.theme}
        >
          {prefs.theme === 'light' ? '☾ Dark' : '☀ Light'}
        </button>
        <AvatarMenu />
      </div>
    </header>
  );
}
