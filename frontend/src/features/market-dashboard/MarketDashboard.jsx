// Root component: owns app state (selected symbol, timeframe, news filter, preferences,
// dev preview state, live feed) and lays out the dashboard panels.
import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import './styles/market-dashboard.css';
import { strings } from './constants/strings.js';
import { TIMEFRAMES, NEWS_FILTERS } from './constants/options.js';
import { assets } from './data/mockData.js';
import { loadPreferences, savePreferences, mockServerSync } from './lib/preferences.js';
import { MockWebSocket } from './lib/MockWebSocket.js';
import { UIContext } from './context/UIContext.js';
import { useQuote, useHistory, useNews, useForecast, useCalendar } from './hooks/useResource.js';

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
import CalendarPanel from './components/panels/CalendarPanel.jsx';
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
    symbol: assets.some((a) => a.symbol === symbol) ? symbol : 'NVDA',
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
  const [connection, setConnection] = useState(strings.connected);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [announcement, announce] = useState('');
  const feed = useRef(null);

  const asset = assets.find((a) => a.symbol === symbol);

  // Start the mock live feed once.
  useEffect(() => {
    const ws = new MockWebSocket();
    ws.onState = setConnection;
    feed.current = ws;
    return () => ws.stop();
  }, []);

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
    const search = `?${p.toString()}`;
    if (search !== window.location.search) navigate({ search }, { replace: true });
  }, [symbol, tf, filter, navigate]);

  // Dev preview: simulate feed disconnect / reconnect.
  useEffect(() => {
    if (override === 'reconnecting') feed.current?.disconnect();
    if (override === 'live_again') feed.current?.reconnect();
  }, [override]);

  const changeSymbol = useCallback((s) => { setSymbol(s); setSelectedEvent(null); }, []);
  const add = useCallback((s) => setPrefs((p) => (p.watchlist.some((w) => w.symbol === s)
    ? p
    : { ...p, watchlist: [...p.watchlist, { symbol: s, addedAt: new Date().toISOString() }] })), []);
  const remove = useCallback((s) => setPrefs((p) => ({ ...p, watchlist: p.watchlist.filter((w) => w.symbol !== s) })), []);

  const quote = useQuote(symbol, override);
  const historyResource = useHistory(symbol, tf, override);
  const news = useNews(symbol, override);
  const forecast = useForecast(symbol, override);
  const calendar = useCalendar(symbol, override);

  const context = useMemo(() => ({ tip, setTip, learning: prefs.learning, theme: prefs.theme }), [tip, prefs.learning, prefs.theme]);

  return (
    <UIContext.Provider value={context}>
      <div className="mmd" data-theme={prefs.theme} data-contrast={prefs.theme === 'dark' ? 'high' : 'standard'}>
        <SkipLinks />
        <Header symbol={symbol} onSelect={changeSymbol} prefs={prefs} setPrefs={setPrefs} />

        <main className="w-full max-w-[1440px] mx-auto px-4 md:px-8 pb-12">
          <Hero connection={connection} feed={feed} />
          <MarketPulse override={override} />

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 mb-4">
            <PanelBoundary title={strings.story}>
              <StoryPanel asset={asset} quote={quote} setSelectedEvent={setSelectedEvent} learning={prefs.learning} />
            </PanelBoundary>
            <PanelBoundary title={strings.chart}>
              <ChartPanel
                asset={asset} tf={tf} setTf={setTf} history={historyResource} quote={quote} forecast={forecast}
                selectedEvent={selectedEvent} setSelectedEvent={setSelectedEvent} learning={prefs.learning} announce={announce}
              />
            </PanelBoundary>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-12 gap-4 mb-4">
            <PanelBoundary title={strings.why}>
              <WhyPanel asset={asset} history={historyResource} selectedEvent={selectedEvent} setSelectedEvent={setSelectedEvent} />
            </PanelBoundary>
            <PanelBoundary title={strings.forecast}>
              <ForecastPanel state={forecast} learning={prefs.learning} />
            </PanelBoundary>
            <PanelBoundary title={strings.calendar}>
              <CalendarPanel state={calendar} />
            </PanelBoundary>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 mb-8">
            <PanelBoundary title={strings.news}>
              <NewsPanel state={news} asset={asset} filter={filter} setFilter={setFilter} />
            </PanelBoundary>
            <PanelBoundary title={strings.watchlist}>
              <WatchlistPanel items={prefs.watchlist} add={add} remove={remove} />
            </PanelBoundary>
          </div>

          <DevStateControls override={override} setOverride={setOverride} />
          <AccessibilityNotes />

          {/* Screen-reader announcements for chart navigation and "Read current price". */}
          <div className="sr-only" aria-live="polite" aria-atomic="true">{announcement}</div>
        </main>

        <Footer />
      </div>
    </UIContext.Provider>
  );
}
