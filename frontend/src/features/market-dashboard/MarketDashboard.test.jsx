// The whole dashboard against a fake backend (src/test/fakeBackend.js): what each panel
// shows for real API data, and how it behaves for missing data, errors and slow jobs.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MarketDashboard from './MarketDashboard.jsx';
import { tickValues } from './lib/tickStore.js';
import { dailyBars, document, installFakeBackend, intradayBars, json, prediction, requested } from '../../test/fakeBackend.js';

// The chart library needs a canvas; record what the dashboard draws instead.
const chart = vi.hoisted(() => ({ data: [], markers: [], priceLines: [] }));
vi.mock('lightweight-charts', () => ({
  createChart: () => ({
    addLineSeries: () => ({
      setData: (data) => { chart.data = data; },
      setMarkers: (markers) => { chart.markers = markers; },
      createPriceLine: (line) => { chart.priceLines.push(line); },
    }),
    timeScale: () => ({ fitContent() {} }),
    applyOptions() {},
    remove() {},
  }),
}));

// 22 daily closes (the 1M view): moves of +10% (Sep 24), -9.1% (Sep 25) and +5% (Oct 9).
const NVDA_CLOSES = Array.from({ length: 22 }, (_, i) => (i === 10 ? 110 : i === 21 ? 105 : 100));

function seed(backend) {
  backend.bars.NVDA = { '1d': dailyBars(NVDA_CLOSES), '5m': intradayBars([105.2, 105.5], '2026-10-09T19:50:00Z') };
  backend.news.NVDA = [
    document(1, 'Nvidia beats on data center sales', { classification: { role: 'company_info' } }),
    document(2, 'Analysts debate AI chip demand', { published_at: '2026-10-08T15:00:00+00:00' }),
  ];
  backend.predictions.NVDA = prediction();
  for (const [ticker, close] of [['SPY', 600], ['QQQ', 500], ['DIA', 450], ['AAPL', 230], ['MSFT', 420]]) {
    backend.bars[ticker] = { '1d': dailyBars([close - 6, close]) };
  }
}

function Location() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

function renderDashboard(url = '/Dashboard?symbol=NVDA&timeframe=1M&news=All') {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/Dashboard" element={<MarketDashboard />} />
        <Route path="/signin" element={<p>Sign-in page</p>} />
      </Routes>
      <Location />
    </MemoryRouter>,
  );
}

const panel = (name) => screen.getByRole('region', { name });
const fetchButtons = () => screen.queryAllByRole('button', { name: 'Fetch data for this ticker' });

let backend;
beforeEach(() => {
  for (const symbol of Object.keys(tickValues)) delete tickValues[symbol];
  Object.assign(chart, { data: [], markers: [], priceLines: [] });
  backend = installFakeBackend();
});

describe('with saved data', () => {
  beforeEach(() => seed(backend));

  it('shows the latest price and today’s story', async () => {
    renderDashboard();
    const story = panel('Today’s story');
    expect(await within(story).findByText(/Nvidia rose 5\.5% versus its previous close/)).toBeInTheDocument();
    expect(within(story).getByText('Chip demand headlines are upbeat.')).toBeInTheDocument();
    expect(within(story).getByText('Headlines lean positive')).toBeInTheDocument();
    expect(within(story).getByRole('link', { name: 'Nvidia beats on data center sales' }))
      .toHaveAttribute('href', 'https://news.example/1');
    const price = within(panel('Price chart'));
    expect(await price.findByText('$105.50')).toBeInTheDocument();
    expect(price.getByText(/\+5\.5%/)).toBeInTheDocument();
    expect(screen.getByText(/Data as of/)).toBeInTheDocument();
  });

  it('draws the price history with the biggest moves and the forecast’s flat band', async () => {
    renderDashboard();
    await waitFor(() => expect(chart.data).toHaveLength(22));
    expect(chart.data[0].value).toBe(100);
    expect(chart.markers.map((m) => m.position)).toEqual(['aboveBar', 'belowBar', 'aboveBar']); // in time order
    expect(chart.priceLines.map((l) => Number(l.price.toFixed(2)))).toEqual([111.21, 108.79]);
    const markerButtons = within(panel('Price chart')).getByLabelText('Chart event markers');
    expect(within(markerButtons).getAllByRole('button')).toHaveLength(3);
  });

  it('explains the biggest moves with headlines from that day', async () => {
    renderDashboard();
    const why = panel('Why it moved');
    const moves = await within(why).findAllByRole('button');
    expect(moves.map((b) => b.textContent)).toEqual([
      expect.stringMatching(/\+10\.0%.*No saved headline from that day/),
      expect.stringMatching(/−9\.1%.*No saved headline from that day/),
      expect.stringMatching(/\+5\.0%.*Nvidia beats on data center sales/),
    ]);
    await userEvent.click(moves[2]);
    expect(moves[2]).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() => expect(chart.markers.find((m) => m.text)?.text).toBe('+5.0%'));
  });

  it('shows the latest forecast and how each persona voted', async () => {
    renderDashboard();
    const forecast = within(panel('What might happen next'));
    expect(await forecast.findByText('▲ Up')).toBeInTheDocument();
    expect(forecast.getByText(/63% · 2 of 3 personas agree/)).toBeInTheDocument();
    expect(forecast.getByText(/rise of more than 1\.1% from \$110\.00 over 5 trading days/)).toBeInTheDocument();
    expect(forecast.getByText('Index & options traders').nextSibling).toHaveTextContent('−0.10');
    expect(forecast.getByText(/always-up says up, momentum says down, the regression says flat/)).toBeInTheDocument();
    expect(forecast.getByText(/Next earnings: Oct 28/)).toBeInTheDocument();
    expect(forecast.getByRole('button', { name: 'Run a new forecast' })).toBeInTheDocument();

    const personas = within(panel('How the personas voted'));
    expect(personas.getByText('Long-term investors · age 25-39')).toBeInTheDocument();
    expect(personas.getByText('Strong cloud growth.')).toBeInTheDocument();
    expect(personas.getByText('▼ Down · 55%')).toBeInTheDocument();
    expect(personas.getByText('no answer')).toBeInTheDocument();
    expect(personas.getByText('Model call failed')).toBeInTheDocument();
  });

  it('lists news with source links and filters it by kind', async () => {
    renderDashboard();
    const news = within(panel('News'));
    expect(await news.findByRole('link', { name: 'Analysts debate AI chip demand' })).toHaveAttribute('target', '_blank');
    const tags = news.getAllByRole('article').map((article) => within(article).getByText(/Company info|Opinion/).textContent);
    expect(tags.sort()).toEqual(['Company info', 'Opinion']);
    await userEvent.click(news.getByRole('tab', { name: 'Company info' }));
    expect(news.queryByText('Analysts debate AI chip demand')).not.toBeInTheDocument();
    expect(news.getByText('Nvidia beats on data center sales')).toBeInTheDocument();
    await userEvent.click(news.getByRole('tab', { name: 'Product & events' }));
    expect(news.getByText('No saved headlines of this kind for this ticker.')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('news=Product+%26+events');
  });

  it('shows market ETFs and watchlist prices, and the watchlist switches the ticker', async () => {
    renderDashboard();
    const pulse = within(screen.getByRole('region', { name: 'Market pulse' }));
    expect(await pulse.findByText('$600.00')).toBeInTheDocument();
    expect(pulse.getByText('$450.00')).toBeInTheDocument();
    const watchlist = within(panel('Your watchlist'));
    expect(await watchlist.findByText('$230.00')).toBeInTheDocument();
    await userEvent.click(watchlist.getByRole('button', { name: 'Show Apple' }));
    expect(await within(panel('Today’s story')).findByText(/Apple rose 2\.7%/)).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('symbol=AAPL');
  });

  it('asks for 5-minute bars on the 1D and 1W views', async () => {
    renderDashboard();
    const tabs = within(panel('Price chart'));
    await userEvent.click(await tabs.findByRole('tab', { name: '1D' }));
    await waitFor(() => expect(requested(backend)).toContain('GET /stocks/NVDA/history?interval=5m&limit=100'));
    await waitFor(() => expect(chart.data).toHaveLength(2));
    expect(screen.getByText(/biggest 5-minute moves/)).toBeInTheDocument();
    await userEvent.click(tabs.getByRole('tab', { name: '5Y' }));
    await waitFor(() => expect(requested(backend)).toContain('GET /stocks/NVDA/history?interval=1d&limit=1260'));
  });

  it('looks up any typed ticker', async () => {
    renderDashboard();
    const search = screen.getByRole('combobox');
    await userEvent.type(search, 'intc');
    await userEvent.click(await screen.findByRole('option', { name: 'Look up ticker INTC' }));
    await waitFor(() => expect(requested(backend)).toContain('GET /stocks/INTC/history?interval=1d&limit=3'));
    expect(screen.getByTestId('location')).toHaveTextContent('symbol=INTC');
    expect(within(panel('Price chart')).getByText('INTC · Stock')).toBeInTheDocument();
  });

  it('ignores an invalid ticker in the URL', async () => {
    renderDashboard('/Dashboard?symbol=%3Cscript%3E');
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('symbol=NVDA'));
  });
});

describe('a ticker with no saved data', () => {
  it('offers to fetch it, then shows it in every panel', async () => {
    seed(backend);
    backend.onRefresh = (ticker) => {
      backend.bars[ticker] = { '1d': dailyBars([900, 945]) };
      backend.news[ticker] = [document(9, 'Costco opens new stores')];
    };
    renderDashboard('/Dashboard?symbol=COST');
    await waitFor(() => expect(fetchButtons()).toHaveLength(3)); // story, chart, news
    expect(screen.getAllByText('No saved prices for this ticker yet.').length).toBeGreaterThan(0);
    expect(within(panel('What might happen next')).getByRole('button', { name: 'Run the first forecast' })).toBeInTheDocument();
    expect(within(panel('How the personas voted')).getByText(/Run a forecast to see/)).toBeInTheDocument();

    await userEvent.click(fetchButtons()[1]);
    expect(requested(backend)).toContain('POST /stocks/COST/refresh');
    expect(await within(panel('Today’s story')).findByText(/COST rose 5\.0%/)).toBeInTheDocument();
    expect(await screen.findByText('Data refreshed.')).toBeInTheDocument();
    expect(await within(panel('News')).findByText('Costco opens new stores')).toBeInTheDocument();
    expect(fetchButtons()).toHaveLength(0);
  });

  it('shows why a refresh failed', async () => {
    backend.respond = (method, path) => (method === 'POST' && path.endsWith('/refresh')
      ? json({ detail: 'Price provider unavailable. Try again later.' }, 502) : null);
    renderDashboard('/Dashboard?symbol=COST');
    await userEvent.click(await screen.findByRole('button', { name: 'Refresh data · COST' }));
    expect(await screen.findByText('Price provider unavailable. Try again later.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh data · COST' })).toBeEnabled();
  });
});

describe('when the backend is down', () => {
  it('says so in each panel and recovers on retry', async () => {
    backend.down = true;
    renderDashboard();
    const chartPanel = within(panel('Price chart'));
    expect(await chartPanel.findByText('This panel could not load.')).toBeInTheDocument();
    expect(chartPanel.getByText(/Can’t reach the backend/)).toBeInTheDocument();
    expect(within(panel('What might happen next')).getByText('This panel could not load.')).toBeInTheDocument();

    backend.down = false;
    seed(backend);
    await userEvent.click(chartPanel.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(chart.data).toHaveLength(22));
    expect(within(panel('What might happen next')).getByText('This panel could not load.')).toBeInTheDocument();
  });
});

describe('running a forecast', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true, toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
    seed(backend);
    delete backend.predictions.NVDA;
  });
  const poll = () => act(() => vi.advanceTimersByTimeAsync(3000));

  it('polls the job and shows the new forecast when it is saved', async () => {
    backend.jobs = [{ status: 'running' }, { status: 'succeeded', prediction: prediction({ direction: 'down', confidence: 0.4 }) }];
    renderDashboard();
    const forecast = within(panel('What might happen next'));
    fireEvent.click(await forecast.findByRole('button', { name: 'Run the first forecast' }));
    expect(await forecast.findByText(/The personas are reading the data and voting/)).toBeInTheDocument();
    expect(forecast.queryByRole('button', { name: /forecast/ })).not.toBeInTheDocument();
    await poll();
    await poll();
    expect(await forecast.findByText('▼ Down')).toBeInTheDocument();
    expect(forecast.getByRole('button', { name: 'Run a new forecast' })).toBeInTheDocument();
    expect(await within(panel('How the personas voted')).findByText('Strong cloud growth.')).toBeInTheDocument();
    expect(screen.getByText('New forecast saved for NVDA.')).toBeInTheDocument();
    expect(backend.calls.find((c) => c.path === '/prediction-jobs').body).toEqual({ ticker: 'NVDA', horizon_days: 5, modes: 'default' });
  });

  it('shows why a job failed and lets you try again', async () => {
    backend.jobs = [{ status: 'failed', error: { status_code: 500, detail: 'The forecast failed. Try again later.' } }];
    renderDashboard();
    const forecast = within(panel('What might happen next'));
    fireEvent.click(await forecast.findByRole('button', { name: 'Run the first forecast' }));
    await poll();
    expect(await forecast.findByText('The forecast failed. Try again later.')).toBeInTheDocument();
    expect(forecast.getByRole('button', { name: 'Run the first forecast' })).toBeInTheDocument();
  });

  it('shows the hourly limit message', async () => {
    backend.respond = (method, path) => (method === 'POST' && path === '/prediction-jobs'
      ? json({ detail: 'Forecast limit reached (10 an hour). Try again in 42 min.' }, 429, { 'Retry-After': '2520' }) : null);
    renderDashboard();
    const forecast = within(panel('What might happen next'));
    fireEvent.click(await forecast.findByRole('button', { name: 'Run the first forecast' }));
    expect(await forecast.findByText('Forecast limit reached (10 an hour). Try again in 42 min.')).toBeInTheDocument();
  });
});

describe('forecast wording', () => {
  it.each([
    [{ direction: 'flat' }, '◆ Flat', /stay within ±1\.1% of \$110\.00 over 5 trading days/],
    [{ direction: 'down' }, '▼ Down', /fall of more than 1\.1%/],
    [{ direction: 'unclear' }, '? Unclear', /split or leaned only weakly, so there is no call/],
    [{ horizon_days: 1 }, '▲ Up', /over 1 trading day\./],
  ])('%o', async (overrides, label, sentence) => {
    seed(backend);
    backend.predictions.NVDA = prediction(overrides);
    renderDashboard();
    const forecast = within(panel('What might happen next'));
    expect(await forecast.findByText(label)).toBeInTheDocument();
    expect(forecast.getByText(sentence)).toBeInTheDocument();
  });

  it('warns when earnings fall inside the window', async () => {
    seed(backend);
    backend.predictions.NVDA = prediction({ earnings_within_horizon: true, next_earnings_date: '2026-10-13' });
    renderDashboard();
    expect(await screen.findByText(/Earnings on Oct 13 fall inside this window/)).toBeInTheDocument();
  });

  it('copes with a forecast that has no headline summary or earnings date', async () => {
    seed(backend);
    backend.predictions.NVDA = prediction({ headline_sentiment: null, next_earnings_date: null, baselines: { always_up: 'up', momentum: 'up' } });
    renderDashboard();
    expect(await within(panel('What might happen next')).findByText('▲ Up')).toBeInTheDocument();
    expect(within(panel('Today’s story')).getByText(/Run a forecast to get an AI summary/)).toBeInTheDocument();
    expect(screen.queryByText(/Next earnings/)).not.toBeInTheDocument();
    expect(screen.getByText(/momentum says up\./)).toBeInTheDocument();
  });
});

describe('account menu', () => {
  it('offers sign-in when nobody is signed in', async () => {
    seed(backend);
    renderDashboard();
    await userEvent.click(screen.getByRole('button', { name: 'Account menu' }));
    expect(screen.getByText('Not signed in')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('menuitem', { name: 'Sign in' }));
    expect(await screen.findByText('Sign-in page')).toBeInTheDocument();
  });

  it('shows the signed-in user and signs out', async () => {
    seed(backend);
    backend.user = { sub: 'password:1', email: 'maya@example.com', name: 'Maya Lopez', provider: 'password' };
    renderDashboard();
    const button = screen.getByRole('button', { name: 'Account menu' });
    await waitFor(() => expect(button).toHaveTextContent('M'));
    await userEvent.click(button);
    expect(screen.getByText('Maya Lopez')).toBeInTheDocument();
    expect(screen.getByText('maya@example.com')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('menuitem', { name: 'Sign out' }));
    expect(await screen.findByText('Sign-in page')).toBeInTheDocument();
    expect(requested(backend)).toContain('POST /oauth/logout');
  });
});
