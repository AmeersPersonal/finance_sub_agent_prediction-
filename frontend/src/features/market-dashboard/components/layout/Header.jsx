// Top bar: home link, product name, ticker search, learning-mode switch, theme toggle, account menu.
import { Link } from 'react-router-dom';
import { strings } from '../../constants/strings.js';
import Search from '../ui/Search.jsx';
import AvatarMenu from '../ui/AvatarMenu.jsx';

export default function Header({ symbol, onSelect, prefs, setPrefs }) {
  return (
    <header className="w-full border-b rule bg-[var(--panel)]">
      <div className="max-w-[1440px] mx-auto px-4 md:px-8 py-4 flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <Link to="/" className="action small" aria-label={strings.home} title={strings.home}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M3 10.5 12 3l9 7.5" />
              <path d="M5 9.5V21h14V9.5" />
              <path d="M10 21v-6h4v6" />
            </svg>
          </Link>
          <div className="serif font-bold text-[1.35rem] whitespace-nowrap">{strings.product}</div>
        </div>
        <nav aria-label="Asset search" className="flex-1 min-w-[210px]">
          <Search symbol={symbol} onSelect={onSelect} />
        </nav>
        <div className="small muted hidden xl:block">{strings.usHours}</div>
        <Link to="/scenarios" className="action small">{strings.scenarios}</Link>
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
