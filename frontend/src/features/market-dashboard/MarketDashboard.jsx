// Root component: owns app state (selected symbol, timeframe, news filter, preferences,
// dev preview state, data refreshes) and lays out the dashboard panels.
import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import './styles/market-dashboard.css';
import { strings } from './constants/strings.js';
import { TIMEFRAMES, NEWS_FILTERS } from './constants/options.js';
import { assetFor, TICKER_PATTERN } from './lib/assets.js';
import { loadPreferences, savePreferences, mockServerSync } from './lib/preferences.js';
import { refreshTicker } from './lib/api.js';
import { biggestMoves } from './lib/moves.js';
import { UIContext } from './context/UIContext.js';
import { useQuote, useHistory, useNews, useForecast, useForecastJob } from './hooks/useResource.js';

import PanelBoundary from './components/ui/PanelBoundary.jsx';
import SkipLinks from './components/layout/SkipLinks.jsx';
import Header from './components/layout/Header.jsx';
import Hero from './components/layout/Hero.jsx';
import MarketPulse from './components/layout/MarketPulse.jsx';
import DevStateControls from './components/layout/DevStateControls.jsx';
import AccessibilityNotes from './components/layout/AccessibilityNotes.jsx';
import Footer from './components/layout/Footer.jsx';
import StoryPanel from './components/panels/StoryPanel.jsx';
import ChartPanel from './components/panels/ChartPanel.jsx';
import WhyPanel from './components/panels/WhyPanel.jsx';
import ForecastPanel from './components/panels/ForecastPanel.jsx';
import PersonasPanel from './components/panels/PersonasPanel.jsx';
import NewsPanel from './components/panels/NewsPanel.jsx';
import WatchlistPanel from './components/panels/WatchlistPanel.jsx';

const initialPrefs = loadPreferences();

// Read initial selections from the URL (?symbol=NVDA&timeframe=1M&news=All).
function readUrlState(search) {
  const params = new URLSearchParams(search);
  const symbol = params.get('symbol');
  const timeframe = params.get('timeframe');
  const news = params.get('news');
  return {
    symbol: symbol && TICKER_PATTERN.test(symbol.toUpperCase()) ? symbol.toUpperCase() : 'NVDA',
    timeframe: TIMEFRAMES.includes(timeframe) ? timeframe : '1M',
    news: NEWS_FILTERS.includes(news) ? news : 'All',
  };
}

export default function MarketDashboard() {
  const location = useLocation();
  const navigate = useNavigate();
  const [initialUrl] = useState(() => readUrlState(location.search));
  const [symbol, setSymbol] = useState(initialUrl.symbol);
  const [tf, setTf] = useState(initialUrl.timeframe);
  const [filter, setFilter] = useState(initialUrl.news);
  const [prefs, setPrefs] = useState(initialPrefs);
  const [tip, setTip] = useState(null);
  const [override, setOverride] = useState('normal');
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [announcement, announce] = useState('');
  // Bumped after a refresh or a finished forecast so every panel refetches.
  const [reload, setReload] = useState(0);
  const [refresh, setRefresh] = useState({ symbol: null, status: 'idle', error: null });
  const focusRestored = useRef(false);
  // The dev preview control is for development builds, opened with ?dev.
  const [showDev] = useState(() => import.meta.env.DEV && new URLSearchParams(location.search).has('dev'));

  const asset = assetFor(symbol);

  // Returning from Scenarios should land on the page heading, once.
  useEffect(() => {
    if (focusRestored.current || !location.state?.fromScenarios) return;
    focusRestored.current = true;
    document.getElementById('dashboard-title')?.focus();
  }, [location.state]);

  // Persist preferences. The theme is applied on the dashboard wrapper below.
  useEffect(() => {
    savePreferences(prefs);
    void mockServerSync();
  }, [prefs]);

  // Keep the URL in sync so views are shareable. Goes through the router so its
  // history state survives; `navigate` stays stable while the pathname is unchanged.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    p.set('symbol', symbol);
    p.set('timeframe', tf);
    p.set('news', filter);
    if (showDev) p.set('dev', '');
    const search = `?${p.toString()}`;
    if (search !== window.location.search) navigate({ search }, { replace: true });
  }, [symbol, tf, filter, navigate, showDev]);

  const changeSymbol = useCallback((s) => { setSymbol(s); setSelectedEvent(null); }, []);
  const add = useCallback((s) => setPrefs((p) => (p.watchlist.some((w) => w.symbol === s)
    ? p
    : { ...p, watchlist: [...p.watchlist, { symbol: s, addedAt: new Date().toISOString() }] })), []);
  const remove = useCallback((s) => setPrefs((p) => ({ ...p, watchlist: p.watchlist.filter((w) => w.symbol !== s) })), []);

  const quote = useQuote(symbol, override, reload);
  const historyResource = useHistory(symbol, tf, override, reload);
  const news = useNews(symbol, override, reload);
  const forecast = useForecast(symbol, override, reload);
  const prediction = forecast.data?.prediction || null;
  const moves = useMemo(() => biggestMoves(historyResource.data, news.data), [historyResource.data, news.data]);
  const intraday = tf === '1D' || tf === '1W';

  const reloadAll = useCallback(() => setReload((n) => n + 1), []);
  const job = useForecastJob(symbol, () => { reloadAll(); announce(`New forecast saved for ${symbol}.`); });

  const runRefresh = useCallback(async () => {
    setRefresh({ symbol, status: 'running', error: null });
    try {
      await refreshTicker(symbol);
      setRefresh({ symbol, status: 'done', error: null });
      reloadAll();
    } catch (error) {
      setRefresh({ symbol, status: 'failed', error: error.message });
    }
  }, [symbol, reloadAll]);
  const refreshState = { ...(refresh.symbol === symbol ? refresh : { status: 'idle', error: null }), run: runRefresh };

  const context = useMemo(() => ({ tip, setTip, learning: prefs.learning, theme: prefs.theme }), [tip, prefs.learning, prefs.theme]);

  return (
    <UIContext.Provider value={context}>
      <div className="mmd" data-theme={prefs.theme} data-contrast={prefs.theme === 'dark' ? 'high' : 'standard'}>
        <SkipLinks />
        <Header symbol={symbol} onSelect={changeSymbol} prefs={prefs} setPrefs={setPrefs} />

        <main className="w-full max-w-[1440px] mx-auto px-4 md:px-8 pb-12">
          <Hero symbol={symbol} quote={quote} refresh={refreshState} />
          <MarketPulse override={override} reload={reload} />

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 mb-4">
            <PanelBoundary title={strings.story}>
              <StoryPanel
                asset={asset} quote={quote} news={news} prediction={prediction} moves={moves}
                setSelectedEvent={setSelectedEvent} learning={prefs.learning} onLoad={runRefresh}
              />
            </PanelBoundary>
            <PanelBoundary title={strings.chart}>
              <ChartPanel
                asset={asset} tf={tf} setTf={setTf} history={historyResource} quote={quote} prediction={prediction} moves={moves}
                selectedEvent={selectedEvent} setSelectedEvent={setSelectedEvent} learning={prefs.learning} announce={announce}
                onLoad={runRefresh}
              />
            </PanelBoundary>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-12 gap-4 mb-4">
            <PanelBoundary title={strings.why}>
              <WhyPanel history={historyResource} moves={moves} intraday={intraday} selectedEvent={selectedEvent} setSelectedEvent={setSelectedEvent} />
            </PanelBoundary>
            <PanelBoundary title={strings.forecast}>
              <ForecastPanel state={forecast} job={job} learning={prefs.learning} />
            </PanelBoundary>
            <PanelBoundary title={strings.personas}>
              <PersonasPanel state={forecast} />
            </PanelBoundary>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 mb-8">
            <PanelBoundary title={strings.news}>
              <NewsPanel state={news} filter={filter} setFilter={setFilter} onLoad={runRefresh} />
            </PanelBoundary>
            <PanelBoundary title={strings.watchlist}>
              <WatchlistPanel items={prefs.watchlist} add={add} remove={remove} onSelect={changeSymbol} reload={reload} />
            </PanelBoundary>
          </div>

          {showDev && <DevStateControls override={override} setOverride={setOverride} />}
          <AccessibilityNotes />

          {/* Screen-reader announcements for chart navigation, "Read current price" and finished forecasts. */}
          <div className="sr-only" aria-live="polite" aria-atomic="true">{announcement}</div>
        </main>

        <Footer />
      </div>
    </UIContext.Provider>
  );
}
