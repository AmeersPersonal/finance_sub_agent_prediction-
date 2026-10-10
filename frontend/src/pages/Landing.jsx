/* =============================================================================
   MONEY MOVES — LANDING PAGE
   =============================================================================

   WHAT THIS FILE IS
   This is a single React component file that builds the entire landing page.
   React lets us build a web page out of small reusable pieces called
   "components". A component is just a JavaScript function that returns
   something that looks like HTML (that HTML-like syntax is called JSX).

   HOW THE FILE IS ORGANIZED (read top to bottom):
     1. Imports .................. pull in React tools and the stylesheet
     2. Text & sample data ....... all the words and fake numbers on the page
     3. Helper functions ......... small tools for dates, money and percentages
     4. Custom hooks ............. reusable logic (theme, live prices, etc.)
     5. Small building blocks .... tiny components used in many places
     6. Page sections ............ header, chart, features, FAQ, signup, footer
     7. LandingPage .............. the main component that stacks every section

   THE BIG IDEA OF THE PRODUCT
   Markets aren't random — they just never explain themselves. Every section
   of this page shows WHAT happened to a price, WHY it happened, and what
   MIGHT happen next.

   A FEW REACT WORDS YOU'LL SEE A LOT
   - props ....... inputs passed into a component, like arguments to a function.
   - state ....... data a component remembers between screen updates.
                   Changing state makes React redraw ("re-render") the component.
   - hook ........ a special React function whose name starts with "use"
                   (useState, useEffect...). Hooks give components superpowers
                   like memory (state) or running code after the page draws.
   - render ...... React running your component function to figure out what
                   should be on screen.
   ========================================================================== */


/* -----------------------------------------------------------------------------
   1. IMPORTS
   -----------------------------------------------------------------------------
   We bring in React plus the specific hooks we use. Each one, in plain words:
   - useState ...... gives a component a piece of memory (a "state" variable).
   - useEffect ..... runs code AFTER React puts things on screen. Used for
                     talking to things outside React: timers, the browser, etc.
   - useMemo ....... remembers the result of a slow calculation so it isn't
                     redone on every redraw.
   - useCallback ... remembers a function so React doesn't create a brand-new
                     copy on every redraw.
   - useRef ........ holds a reference to a real HTML element (e.g. to focus it).
   - useId ......... creates a unique ID string, handy for linking labels to
                     elements for screen readers.
   The CSS import loads all the styling for this page.
   -------------------------------------------------------------------------- */
import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import "../LandingPage.css";


/* -----------------------------------------------------------------------------
   2. TEXT & SAMPLE DATA
   -----------------------------------------------------------------------------
   Keeping all words in one place (instead of scattered through the code) makes
   them easy to edit, and makes it possible to translate the site later.
   Constants written in ALL_CAPS are values that never change while the page
   runs.
   -------------------------------------------------------------------------- */

// The product name. Change it here and it updates everywhere on the page.
const BRAND = "Money Moves";

// All the main text on the page, grouped in one object.
const COPY = {
  // Text for the hidden "skip" link keyboard users see first (see the bottom).
  skip: "Skip to main content",

  // The links in the top navigation bar. Each "href" starting with # jumps to
  // the part of the page whose id matches (e.g. "#how" → the section id="how").
  nav: [
    { href: "#how", label: "How it works" },
    { href: "#features", label: "Inside the dashboard" },
    { href: "#learn", label: "Learning mode" },
    { href: "#faq", label: "Questions" },
  ],

  // Text for the big top section of the page (called the "hero").
  heroKicker: "Financial literacy, in plain language",
  heroTitle: "The market isn't random. It just never explains itself.",
  heroBody:
    "Money Moves puts the price line, the news behind it, and an honest estimate of what's next on one page — so you finally see why a stock went up or down, not just that it did.",
  heroPrimary: "Get early access",
  heroSecondary: "See how it works",
  heroFootnote: "Free to start. Educational only — no trading, no brokerage logins.",

  // Legal-style notice shown in the footer. Have a lawyer review before launch.
  disclaimer:
    "Money Moves is an educational tool. Nothing on this site is financial advice. Forecasts are computer-generated estimates, and prices can move outside any range shown.",
};

/* ---------- Sample chart data ----------
   Fake data for a made-up company. We use a fictional company on purpose so
   we never accidentally make false claims about a real one.                   */
const SAMPLE = {
  name: "Northwind Chips",
  symbol: "NWCH",

  // 30 daily closing prices, oldest first. Position 0 is day 1, position 29 is
  // the most recent day. (In JavaScript, array positions start counting at 0.)
  values: [
    112.0, 113.4, 112.8, 114.1, 115.0, 114.6, 115.8, 116.2, 123.4, 124.1,
    123.0, 124.8, 125.5, 124.9, 126.2, 127.0, 126.4, 122.5, 121.8, 123.0,
    123.9, 124.6, 125.1, 124.0, 118.9, 119.6, 120.8, 121.5, 122.4, 123.1,
  ],

  // The forecast: 8 future days. For each day:
  //   mid  = the model's best guess (drawn as a dashed line)
  //   low  = bottom of the likely range
  //   high = top of the likely range
  // The low/high gap widens over time because the further ahead you guess,
  // the less certain you are. This becomes the shaded "cone" on the chart.
  forecast: [
    { mid: 123.4, low: 122.2, high: 124.6 },
    { mid: 123.8, low: 121.6, high: 126.0 },
    { mid: 124.1, low: 120.9, high: 127.3 },
    { mid: 124.5, low: 120.3, high: 128.7 },
    { mid: 124.8, low: 119.6, high: 130.0 },
    { mid: 125.2, low: 119.0, high: 131.4 },
    { mid: 125.5, low: 118.4, high: 132.6 },
    { mid: 125.9, low: 117.8, high: 134.0 },
  ],

  // The three big price moves we explain. "index" says WHICH day in the
  // `values` list above the move happened on (8 = the 9th day).
  events: [
    {
      index: 8,
      category: "Earnings",
      title: "Earnings beat expectations",
      body:
        "The company reported profits well above what analysts predicted. When results beat the guess, buyers rush in and the price jumps — often overnight.",
    },
    {
      index: 17,
      category: "Interest rates",
      title: "Central bank signals rates stay high",
      body:
        "Higher interest rates make borrowing pricier and safe savings more attractive, so investors often pull money from growth stocks like chipmakers.",
    },
    {
      index: 24,
      category: "Sector-wide",
      title: "The whole chip sector slid",
      body:
        "Reports that large tech firms may slow spending on chips hit every chipmaker at once. Nothing changed at this company — it fell with its group.",
    },
  ],
};


/* -----------------------------------------------------------------------------
   3. HELPER FUNCTIONS
   -----------------------------------------------------------------------------
   Small, plain JavaScript tools. None of these are React-specific.
   -------------------------------------------------------------------------- */

/* Makes a list of dates for our sample chart, skipping weekends (the stock
   market is closed on Saturday and Sunday).
   - count: how many dates we want (30, one per price)
   - start: the first date. Note: JavaScript months start at 0, so 7 = August.
   Holidays are ignored because this is only sample data.                      */
function buildTradingDates(count, start = new Date(2026, 7, 17)) {
  const out = [];              // the list of dates we'll return
  const d = new Date(start);   // a copy we can move forward day by day
  while (out.length < count) {
    const day = d.getDay();    // 0 = Sunday, 6 = Saturday
    if (day !== 0 && day !== 6) out.push(new Date(d)); // keep weekdays only
    d.setDate(d.getDate() + 1);                         // move to the next day
  }
  return out;
}

/* Formatters: built-in browser tools (Intl = "internationalization") that turn
   raw numbers and dates into nicely written text.                            */
// 123.1 → "$123.10"
const fmtUSD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
// a Date → "Sep 18"
const fmtDate = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
// a Date → "Friday, September 18" (used for screen-reader announcements)
const fmtDateLong = new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric" });

// Turns a number into a signed percentage: 4.12 → "+4.1%", -3.06 → "−3.1%".
// The ? : syntax is a short if/else: (condition ? valueIfTrue : valueIfFalse).
const fmtPct = (n) => `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(1)}%`;

// How much something changed, in percent. From 100 to 110 → 10.
const pctChange = (from, to) => ((to - from) / from) * 100;

/* ---------- Market hours ----------
   Returns true if the US stock market is open right now, false otherwise.
   Regular hours are Monday–Friday, 9:30 AM to 4:00 PM New York time.
   We always check New York time, no matter where the visitor lives.
   (Crypto trades 24/7, so it doesn't use this check.)                         */
function isUsMarketOpen(now = new Date()) {
  // Ask the browser for the current weekday, hour and minute in New York.
  // formatToParts gives back pieces like { type: "hour", value: "14" }.
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);

  // Small helper: find one piece by its type, e.g. get("hour") → "14".
  // The ?. means "only read .value if a piece was found" (avoids a crash).
  const get = (t) => parts.find((p) => p.type === t)?.value;

  const day = get("weekday");
  if (day === "Sat" || day === "Sun") return false; // weekends: closed

  // Convert the time to "minutes since midnight" so it's easy to compare.
  // (% 24 turns a possible "24" hour at midnight into 0.)
  const mins = (parseInt(get("hour"), 10) % 24) * 60 + parseInt(get("minute"), 10);
  return mins >= 570 && mins < 960; // 570 = 9:30 AM, 960 = 4:00 PM
}

/* Starting prices for the scrolling price strip under the header.
   - kind: "index" (a group of stocks, follows market hours) or "crypto" (24/7)
   - open: the price at the start of the day, used to work out today's change. */
const TICKERS_SEED = [
  { id: "spx", label: "S&P 500", kind: "index", price: 6512.4, open: 6488.1 },
  { id: "ndx", label: "Nasdaq", kind: "index", price: 21734.9, open: 21802.6 },
  { id: "dji", label: "Dow", kind: "index", price: 45120.3, open: 45001.8 },
  { id: "btc", label: "Bitcoin", kind: "crypto", price: 98412.55, open: 97160.2 },
  { id: "eth", label: "Ether", kind: "crypto", price: 3621.18, open: 3655.9 },
];


/* -----------------------------------------------------------------------------
   4. CUSTOM HOOKS
   -----------------------------------------------------------------------------
   A "custom hook" is our own function that uses React hooks inside it. It lets
   us package up a piece of logic and reuse it, keeping components short.
   By React's rules, a hook's name must start with "use".
   -------------------------------------------------------------------------- */

/* usePrefersReducedMotion
   Some people turn on "reduce motion" in their computer settings because
   animations can make them feel dizzy or sick. This hook reports whether that
   setting is on (true/false), and keeps watching in case it changes.
   Right now the CSS handles reduced motion on its own, so this hook is ready
   for any future JavaScript animations.                                      */
function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    // Safety check: stop if we're not in a browser that supports this.
    if (typeof window === "undefined" || !window.matchMedia) return undefined;

    // matchMedia checks a CSS "media query" from JavaScript.
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(mq.matches);
    update();                               // read the current setting
    mq.addEventListener?.("change", update); // re-read whenever it changes

    // The function returned from useEffect is a "cleanup": React runs it when
    // the component goes away, so we stop listening and don't leak memory.
    return () => mq.removeEventListener?.("change", update);
  }, []); // [] = run this effect once, when the component first appears
  return reduced;
}

/* safeGet / safeSet
   localStorage is a small storage box in the browser that remembers things
   even after the page is closed (we use it to remember the chosen theme).
   Some browsers block it (e.g. strict privacy modes), which throws an error.
   "try/catch" catches that error so the page keeps working instead of crashing. */
function safeGet(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null; // storage is blocked: behave as if nothing was saved
  }
}
function safeSet(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage blocked — the preference just won't be remembered */
  }
}

/* useTheme
   Manages light mode vs. dark mode.
   - theme is "light", "dark", or null.
   - null means "the visitor hasn't picked one yet, so follow their computer's
     setting" (the CSS file handles that part automatically).
   Returns two things: the current theme, and a function that flips it.       */
function useTheme() {
  // Read any previously saved choice WHILE creating the state. Passing a
  // function to useState means "run this once to get the starting value".
  // Doing it here (instead of in a useEffect afterwards) means the page draws
  // with the right theme the first time, instead of drawing twice.
  const [theme, setTheme] = useState(() => {
    if (typeof window === "undefined") return null; // not in a browser
    const saved = safeGet("pm-theme");
    return saved === "light" || saved === "dark" ? saved : null;
  });

  // Whenever `theme` changes, put it on the <html> tag as data-theme="dark"
  // (or remove it). The CSS file looks for that attribute to swap colors.
  // This is a good use of useEffect: syncing React's state to the real page.
  useEffect(() => {
    const root = document.documentElement; // the <html> element
    if (theme) root.setAttribute("data-theme", theme);
    else root.removeAttribute("data-theme");
  }, [theme]); // [theme] = re-run this whenever `theme` changes

  // The function the theme button calls. useCallback keeps the same function
  // between redraws, which avoids needless work in child components.
  const toggle = useCallback(() => {
    // Passing a function to setTheme gives us the previous value ("prev").
    setTheme((prev) => {
      // If nothing was chosen yet (null), work out what the computer is using.
      // ?? means "use the right side only if the left side is null/undefined".
      const current =
        prev ?? (window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      const next = current === "dark" ? "light" : "dark"; // flip it
      safeSet("pm-theme", next); // remember the choice for next visit
      return next;               // this becomes the new theme
    });
  }, []);

  return [theme, toggle];
}

/* useSampleTicks
   Fakes a live price feed so the price strip feels alive. Once per second it
   nudges each price up or down a tiny random amount.
   - Stock indexes only move while the US market is open.
   - Crypto always moves, because it trades around the clock.

   Accessibility note: these numbers are deliberately NOT announced to screen
   readers. A screen reader reading a new price every second would make the
   page impossible to use.                                                    */
function useSampleTicks() {
  const [tickers, setTickers] = useState(TICKERS_SEED);
  // Passing a function means "work out the starting value once".
  const [usOpen, setUsOpen] = useState(() => isUsMarketOpen());

  useEffect(() => {
    // setInterval runs the code below every 1000 ms (1 second).
    const id = window.setInterval(() => {
      const open = isUsMarketOpen();
      setUsOpen(open);

      // Build a NEW list of tickers. In React you never change state in place;
      // you create a new copy, so React notices the change and redraws.
      setTickers((list) =>
        list.map((t) => {
          const live = t.kind === "crypto" || open;
          if (!live) return t; // market closed: keep this price as it is

          // A tiny random move: Math.random() gives 0–1, minus 0.5 gives
          // −0.5 to +0.5, times a small fraction of the price.
          const drift = (Math.random() - 0.5) * t.price * 0.0006;

          // { ...t } copies every field of t, then we overwrite `price`.
          // Math.max(0.01, ...) makes sure a price can never go below 1 cent.
          return { ...t, price: Math.max(0.01, t.price + drift) };
        })
      );
    }, 1000);

    // Cleanup: stop the timer if the component is removed from the page.
    return () => window.clearInterval(id);
  }, []);

  return { tickers, usOpen };
}


/* -----------------------------------------------------------------------------
   5. SMALL BUILDING BLOCKS
   -----------------------------------------------------------------------------
   Tiny components used in several places on the page.
   -------------------------------------------------------------------------- */

/* Direction
   Shows a change like "▲ +6.2%" in teal or "▼ −4.1%" in orange.
   Why the arrow AND the sign AND the color? Many people are colorblind and
   can't tell red from green, so color alone would hide the meaning.

   Props (the inputs):
   - value: the percent change, e.g. 6.2 or -4.1
   - className: optional extra CSS classes                                    */
function Direction({ value, className = "" }) {
  const up = value >= 0;
  return (
    <span className={`dir ${up ? "dir--up" : "dir--down"} ${className}`}>
      {/* aria-hidden="true" hides the arrow from screen readers — they'd read
          it as "black up-pointing triangle", which is just noise. */}
      <span aria-hidden="true">{up ? "▲" : "▼"}</span> {fmtPct(value)}
      {/* "sr-only" text is invisible on screen but read by screen readers,
          so they hear "+6.2% up" instead of a symbol. */}
      <span className="sr-only">{up ? " up" : " down"}</span>
    </span>
  );
}

/* Toggletip
   A word you can click (or press Enter on) to show a short definition, like
   "volatility". It closes when you press Escape, click elsewhere, or tab away.
   We open it on click, not on hover, so it works for keyboard and touch users.

   Props:
   - term: the word shown in the sentence
   - children: whatever is placed between <Toggletip>...</Toggletip>, which is
     the definition text                                                      */
function Toggletip({ term, children }) {
  const [open, setOpen] = useState(false); // is the definition showing?
  const id = useId();                      // unique ID linking button ↔ bubble
  const wrapRef = useRef(null);            // points at the wrapping <span>

  // While the bubble is open, listen for Escape or a click outside to close it.
  useEffect(() => {
    if (!open) return undefined; // closed: nothing to listen for

    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onPointer = (e) => {
      // .contains() checks whether the click landed inside our component.
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);

    // Cleanup: remove the listeners when the bubble closes.
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  return (
    <span className="tip" ref={wrapRef}>
      <button
        type="button"
        className="tip__term"
        aria-expanded={open}  // tells screen readers whether it's open
        aria-controls={id}    // tells screen readers which element it opens
        onClick={() => setOpen((o) => !o)} // flip open ↔ closed
        onBlur={(e) => {
          // Close when keyboard focus moves somewhere outside this component.
          if (!wrapRef.current?.contains(e.relatedTarget)) setOpen(false);
        }}
      >
        {term}
        <span className="sr-only"> — show definition</span>
      </button>
      {/* role="status" makes this a "live region": when text appears inside
          it, screen readers read it aloud automatically. The box always exists
          (just empty when closed) so screen readers notice the new text. */}
      <span id={id} role="status" className={`tip__bubble ${open ? "is-open" : ""}`}>
        {open ? children : ""}
      </span>
    </span>
  );
}


/* -----------------------------------------------------------------------------
   6. PAGE SECTIONS
   -----------------------------------------------------------------------------
   Each section of the page is its own component, in top-to-bottom order.
   -------------------------------------------------------------------------- */

/* ---------- SiteHeader ----------
   The bar fixed to the top of the screen: logo, navigation links, the
   light/dark button and the "Early access" button.
   Props:
   - theme: the current theme from useTheme
   - onToggleTheme: the function to call when the theme button is clicked     */
function SiteHeader({ theme, onToggleTheme }) {
  // Work out if the page is currently dark: either the visitor chose dark, or
  // they haven't chosen and their computer is set to dark mode.
  const isDark =
    theme === "dark" ||
    (theme === null && typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);

  return (
    // <header> is a "landmark": screen-reader users can jump straight to it.
    <header className="site-header">
      <div className="wrap site-header__inner">
        {/* The logo. aria-label gives the link a clear name for screen readers. */}
        <a className="brand" href="#top" aria-label={`${BRAND} home`}>
          <span className="brand__mark" aria-hidden="true">
            {/* A tiny drawing (SVG) of a rising line — decorative only. */}
            <svg viewBox="0 0 24 24" width="22" height="22">
              <path d="M3 17 L9 11 L13 14 L21 6" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="13" cy="14" r="2.2" fill="currentColor" />
            </svg>
          </span>
          <span className="brand__name">{BRAND}</span>
        </a>

        {/* Main navigation. .map() turns each item in COPY.nav into a link.
            React needs a unique "key" on each repeated item to track it. */}
        <nav aria-label="Primary" className="site-nav">
          <ul>
            {COPY.nav.map((n) => (
              <li key={n.href}>
                <a href={n.href}>{n.label}</a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="site-header__actions">
          {/* Theme button. The label describes what clicking WILL do. */}
          <button
            type="button"
            className="icon-btn"
            onClick={onToggleTheme}
            aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
          >
            <span aria-hidden="true">{isDark ? "☀" : "☾"}</span>
          </button>
          <a className="btn btn--small" href="/signin">
            Sign in
          </a>
        </div>
      </div>
    </header>
  );
}

/* ---------- TickerStrip ----------
   The thin bar of moving prices under the header.
   React.memo tells React: "only redraw this component when its own data
   changes", so the prices updating every second doesn't redraw the whole page. */
const TickerStrip = React.memo(function TickerStrip() {
  const { tickers, usOpen } = useSampleTicks(); // our fake live prices

  return (
    <section className="ticker" aria-labelledby="ticker-heading">
      <div className="wrap ticker__inner">
        <h2 id="ticker-heading" className="ticker__label">
          Sample prices <span className="badge">Demo data</span>
        </h2>
        <ul className="ticker__list">
          {tickers.map((t) => {
            // Each asset has its own status: crypto never closes, stocks do.
            const live = t.kind === "crypto" || usOpen;
            const status = t.kind === "crypto" ? "Trades 24/7" : usOpen ? "Market open" : "Market closed";
            return (
              <li key={t.id} className="ticker__item">
                <span className="ticker__name">{t.label}</span>
                {/* Indexes are points, not dollars, so we remove the "$". */}
                <span className="ticker__price num">{fmtUSD.format(t.price).replace("$", t.kind === "index" ? "" : "$")}</span>
                <Direction value={pctChange(t.open, t.price)} />
                <span className={`status ${live ? "status--live" : "status--closed"}`}>
                  <span className="status__dot" aria-hidden="true" />
                  {status}
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
});

/* ---------- StoryChart ----------
   The heart of the page: an interactive chart that shows a price line, marks
   the three big moves, explains why each one happened, and shows a forecast.

   Everything is drawn with SVG — the web's built-in format for shapes and
   lines. SVG uses x/y coordinates where (0, 0) is the TOP-LEFT corner and
   y grows DOWNWARD (the opposite of a math class graph).

   CHART holds the drawing size and the empty margins ("padding") on each side,
   which leave room for the axis labels.                                      */
const CHART = { w: 640, h: 300, padL: 44, padR: 16, padT: 18, padB: 30 };

function StoryChart() {
  // A date for each price. useMemo with [] = calculate once, then reuse.
  const dates = useMemo(() => buildTradingDates(SAMPLE.values.length), []);

  // ----- State: what this component remembers -----
  const [activeEvent, setActiveEvent] = useState(2); // which move is selected (2 = the third, the big drop)
  const [cursor, setCursor] = useState(null);        // which day the keyboard is on (null = none)
  const [showTable, setShowTable] = useState(false); // is the data table visible?
  const [announce, setAnnounce] = useState("");      // text read aloud to screen readers

  /* ----- Geometry: turning prices into points on the drawing -----
     This is the math that converts "day 8, $123.40" into "x = 180, y = 95".
     It only needs to run once, so we wrap it in useMemo.                     */
  const geo = useMemo(() => {
    // Total days across the chart: 30 real + 8 forecast.
    const total = SAMPLE.values.length + SAMPLE.forecast.length;

    // Lowest and highest prices anywhere on the chart (including the forecast
    // range), with $2 of breathing room so the line doesn't touch the edges.
    // The ... ("spread") unpacks a list into individual values.
    const all = [...SAMPLE.values, ...SAMPLE.forecast.flatMap((f) => [f.low, f.high])];
    const min = Math.floor(Math.min(...all) - 2);
    const max = Math.ceil(Math.max(...all) + 2);

    // x(i): day number → horizontal position. Day 0 sits at the left margin,
    // the last forecast day at the right margin, evenly spaced in between.
    const x = (i) => CHART.padL + (i / (total - 1)) * (CHART.w - CHART.padL - CHART.padR);

    // y(v): price → vertical position. We use "1 −" to flip it, because in
    // SVG y grows downward but we want higher prices to sit higher up.
    const y = (v) => CHART.padT + (1 - (v - min) / (max - min)) * (CHART.h - CHART.padT - CHART.padB);

    // The price line as SVG "path" instructions:
    //   "M x,y" = Move the pen here (without drawing)
    //   "L x,y" = draw a Line to here
    // So we Move to the first point, then draw a Line to each point after it.
    const line = SAMPLE.values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");

    const last = SAMPLE.values.length - 1;  // position of the most recent real day
    const fIdx = (k) => last + 1 + k;       // forecast step k → its day number

    // The dashed forecast line: starts at the last real price, then connects
    // each forecast "mid" (best guess) point.
    const mid =
      `M${x(last).toFixed(1)},${y(SAMPLE.values[last]).toFixed(1)} ` +
      SAMPLE.forecast.map((f, k) => `L${x(fIdx(k)).toFixed(1)},${y(f.mid).toFixed(1)}`).join(" ");

    // The shaded forecast cone: trace along the HIGH values going right, then
    // back along the LOW values going left, and close the shape ("Z").
    const band =
      `M${x(last).toFixed(1)},${y(SAMPLE.values[last]).toFixed(1)} ` +
      SAMPLE.forecast.map((f, k) => `L${x(fIdx(k)).toFixed(1)},${y(f.high).toFixed(1)}`).join(" ") +
      " " +
      [...SAMPLE.forecast]
        .map((f, k) => ({ f, k }))  // remember each step's number before reversing
        .reverse()                  // walk back from right to left
        .map(({ f, k }) => `L${x(fIdx(k)).toFixed(1)},${y(f.low).toFixed(1)}`)
        .join(" ") +
      " Z";

    // Three price labels on the left side: bottom, middle and top.
    const ticks = [min, (min + max) / 2, max].map((v) => ({ v, y: y(v) }));

    return { x, y, line, mid, band, ticks, last, forecastStartX: x(last) };
  }, []);

  // ----- Headline numbers for the top of the card -----
  const first = SAMPLE.values[0];                          // oldest price
  const lastVal = SAMPLE.values[SAMPLE.values.length - 1]; // newest price
  const change = pctChange(first, lastVal);                // total % change

  /* A written summary of the whole chart for screen-reader users, since they
     can't see the picture. This is the chart's "alt text".                    */
  const summary = useMemo(() => {
    const drop = SAMPLE.events[2];
    return `${SAMPLE.name}, sample data, past ${SAMPLE.values.length} trading days: rose from ${fmtUSD.format(first)} to ${fmtUSD.format(
      lastVal
    )}, up ${change.toFixed(1)} percent. Largest one-day drop on ${fmtDate.format(dates[drop.index])}, when the whole chip sector slid. A dashed forecast continues with a widening range.`;
  }, [dates, first, lastVal, change]);

  // The currently selected event, and how big that day's move was.
  const ev = SAMPLE.events[activeEvent];
  const evMove = pctChange(SAMPLE.values[ev.index - 1], SAMPLE.values[ev.index]);

  /* Builds the sentence a screen reader says for one day, e.g.
     "Friday, September 18: $118.90, down 4.1 percent. Event: ..."           */
  const describePoint = useCallback(
    (i) => {
      const v = SAMPLE.values[i];
      const prev = i > 0 ? SAMPLE.values[i - 1] : v; // day 0 has no "previous day"
      const d = pctChange(prev, v);
      const event = SAMPLE.events.find((e) => e.index === i); // is there a big move on this day?
      return `${fmtDateLong.format(dates[i])}: ${fmtUSD.format(v)}, ${d >= 0 ? "up" : "down"} ${Math.abs(d).toFixed(
        1
      )} percent.${event ? ` Event: ${event.title}. Press Enter for the explanation.` : ""}`;
    },
    [dates]
  );

  /* Keyboard controls for the chart. Once the chart has focus (reach it with
     Tab), these keys work:
       → / ←      step one day forward / back
       Home / End jump to the first / last day
       Enter      on a day with a big move, open its explanation              */
  const onPlotKey = (e) => {
    const n = SAMPLE.values.length;
    let next = cursor;
    if (e.key === "ArrowRight") next = cursor === null ? 0 : Math.min(n - 1, cursor + 1);
    else if (e.key === "ArrowLeft") next = cursor === null ? n - 1 : Math.max(0, cursor - 1);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = n - 1;
    else if (e.key === "Enter" && cursor !== null) {
      // findIndex returns −1 if no event happened on this day.
      const idx = SAMPLE.events.findIndex((x) => x.index === cursor);
      if (idx >= 0) {
        setActiveEvent(idx);
        setAnnounce(`${SAMPLE.events[idx].title}. ${SAMPLE.events[idx].body}`);
      }
      return;
    } else return; // any other key: do nothing, let the browser handle it

    e.preventDefault();             // stop arrow keys from also scrolling the page
    setCursor(next);                // move the highlight on the chart
    setAnnounce(describePoint(next)); // and read the day aloud
  };

  // ----- What gets drawn on screen -----
  return (
    <figure className="story card" aria-labelledby="story-title">
      {/* Card header: company name on the left, latest price on the right. */}
      <div className="story__head">
        <div>
          <p className="eyebrow">
            Today's story <span className="badge">Sample data</span>
          </p>
          <h2 id="story-title" className="story__title">
            {SAMPLE.name} <span className="story__symbol">{SAMPLE.symbol}</span>
          </h2>
        </div>
        <div className="story__price">
          <span className="num story__value">{fmtUSD.format(lastVal)}</span>
          <Direction value={change} />
          <span className="story__range">30 days</span>
        </div>
      </div>

      {/* The chart area. tabIndex={0} lets keyboard users Tab to it, and
          onKeyDown runs our arrow-key handler. When focus leaves (onBlur),
          the day highlight is removed. */}
      <div
        className="plot"
        tabIndex={0}
        role="group"
        aria-roledescription="interactive chart"
        aria-label="Price chart. Use left and right arrow keys to step through days, Home and End to jump."
        onKeyDown={onPlotKey}
        onBlur={() => setCursor(null)}
      >
        {/* role="img" + aria-label: screen readers announce the summary. */}
        <svg viewBox={`0 0 ${CHART.w} ${CHART.h}`} role="img" aria-label={summary} preserveAspectRatio="xMidYMid meet">
          {/* Faint horizontal guide lines, each with its price label. */}
          {geo.ticks.map((t) => (
            <g key={t.v}>
              <line x1={CHART.padL} x2={CHART.w - CHART.padR} y1={t.y} y2={t.y} className="plot__grid" />
              <text x={CHART.padL - 8} y={t.y + 4} className="plot__axis" textAnchor="end">
                {Math.round(t.v)}
              </text>
            </g>
          ))}

          {/* A lightly shaded area marking "the future" (the forecast zone). */}
          <rect
            x={geo.forecastStartX}
            y={CHART.padT}
            width={CHART.w - CHART.padR - geo.forecastStartX}
            height={CHART.h - CHART.padT - CHART.padB}
            className="plot__future"
          />
          <text x={geo.forecastStartX + 8} y={CHART.padT + 14} className="plot__axis plot__axis--accent">
            Estimate
          </text>

          {/* Drawn in this order so later shapes sit on top of earlier ones:
              the forecast cone, then the dashed guess line, then the real price line. */}
          <path d={geo.band} className="plot__band" />
          <path d={geo.mid} className="plot__mid" />
          <path d={geo.line} className="plot__line" />

          {/* The numbered circles marking the three big moves. */}
          {SAMPLE.events.map((e, i) => {
            const cx = geo.x(e.index);               // circle center, horizontal
            const cy = geo.y(SAMPLE.values[e.index]); // circle center, vertical
            const active = i === activeEvent;
            return (
              <g key={e.index} className={`marker ${active ? "is-active" : ""}`}>
                {/* "condition && <thing>" means: only draw <thing> if condition
                    is true. Here: a dotted vertical line for the selected move. */}
                {active && <line x1={cx} x2={cx} y1={CHART.padT} y2={CHART.h - CHART.padB} className="marker__rule" />}
                <circle cx={cx} cy={cy} r={active ? 9 : 7} className="marker__ring" />
                <text x={cx} y={cy + 4} textAnchor="middle" className="marker__num">
                  {i + 1}
                </text>
              </g>
            );
          })}

          {/* The keyboard highlight: a thin line and dot on the current day. */}
          {cursor !== null && (
            <g className="cursor">
              <line x1={geo.x(cursor)} x2={geo.x(cursor)} y1={CHART.padT} y2={CHART.h - CHART.padB} />
              <circle cx={geo.x(cursor)} cy={geo.y(SAMPLE.values[cursor])} r="4.5" />
            </g>
          )}

          {/* First and last date labels along the bottom. */}
          <text x={CHART.padL} y={CHART.h - 8} className="plot__axis">
            {fmtDate.format(dates[0])}
          </text>
          <text x={geo.forecastStartX} y={CHART.h - 8} className="plot__axis" textAnchor="middle">
            {fmtDate.format(dates[dates.length - 1])}
          </text>
        </svg>
      </div>

      {/* An invisible "live region". Any text we put in `announce` is read
          aloud by screen readers. aria-live="polite" means "wait until the
          screen reader finishes talking, then read this". */}
      <p className="sr-only" aria-live="polite">
        {announce}
      </p>

      {/* The three buttons under the chart, one per big move. These do the
          same job as the circles on the chart, but as real buttons that
          everyone can click or reach with the keyboard. */}
      <div className="events" role="group" aria-label="Why it moved: the three biggest moves">
        {SAMPLE.events.map((e, i) => {
          const move = pctChange(SAMPLE.values[e.index - 1], SAMPLE.values[e.index]);
          return (
            <button
              key={e.index}
              type="button"
              className={`event-chip ${i === activeEvent ? "is-active" : ""}`}
              aria-pressed={i === activeEvent} // tells screen readers which one is selected
              onClick={() => setActiveEvent(i)}
            >
              <span className="event-chip__num" aria-hidden="true">
                {i + 1}
              </span>
              <span className="event-chip__text">
                <span className="event-chip__date">{fmtDate.format(dates[e.index])}</span>
                <span className="event-chip__cat">{e.category}</span>
              </span>
              <Direction value={move} />
            </button>
          );
        })}
      </div>

      {/* The explanation box for the selected move. It's also a live region,
          so picking a new move reads the new explanation aloud. */}
      <div className="explain" aria-live="polite">
        <p className="explain__kicker">
          Why it moved · {fmtDate.format(dates[ev.index])} · <Direction value={evMove} />
        </p>
        <h3 className="explain__title">{ev.title}</h3>
        <p className="explain__body">{ev.body}</p>
      </div>

      {/* Legend explaining the chart's lines, plus the table toggle button. */}
      <figcaption className="story__foot">
        <span className="legend">
          <span className="legend__swatch legend__swatch--line" aria-hidden="true" /> Actual price
        </span>
        <span className="legend">
          <span className="legend__swatch legend__swatch--band" aria-hidden="true" /> Estimated range — not a promise
        </span>
        {/* aria-expanded tells screen readers whether the table is open. */}
        <button type="button" className="link-btn" aria-expanded={showTable} aria-controls="story-table" onClick={() => setShowTable((s) => !s)}>
          {showTable ? "Hide table" : "View as table"}
        </button>
      </figcaption>

      {/* The same data as a plain table. Some people (and screen readers) find
          a table much easier than a picture. Only shown when toggled on. */}
      {showTable && (
        <div id="story-table" className="table-wrap" tabIndex={0} role="region" aria-label="Daily prices, sample data">
          <table>
            <caption>
              {SAMPLE.name} daily closing prices (sample data)
            </caption>
            <thead>
              <tr>
                {/* scope="col" tells screen readers this header labels a column. */}
                <th scope="col">Date</th>
                <th scope="col">Close</th>
                <th scope="col">Change</th>
                <th scope="col">Event</th>
              </tr>
            </thead>
            <tbody>
              {SAMPLE.values.map((v, i) => {
                const event = SAMPLE.events.find((e) => e.index === i);
                return (
                  <tr key={i}>
                    {/* scope="row": this cell labels its whole row. */}
                    <th scope="row">{fmtDate.format(dates[i])}</th>
                    <td className="num">{fmtUSD.format(v)}</td>
                    {/* Day one has nothing to compare against, so show a dash. */}
                    <td>{i === 0 ? "—" : <Direction value={pctChange(SAMPLE.values[i - 1], v)} />}</td>
                    <td>{event ? event.title : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </figure>
  );
}

/* ---------- Hero ----------
   The first big section visitors see: headline, description, two buttons on
   the left, and the StoryChart on the right.                                 */
function Hero() {
  return (
    <section className="hero" aria-labelledby="hero-title">
      <div className="wrap hero__grid">
        <div className="hero__copy">
          <p className="eyebrow">{COPY.heroKicker}</p>
          {/* <h1> is the single most important heading on the page.
              Every page should have exactly one. */}
          <h1 id="hero-title" className="hero__title">
            {COPY.heroTitle}
          </h1>
          <p className="hero__body">{COPY.heroBody}</p>
          <div className="hero__ctas">
            {/* "CTA" = call to action, the buttons we want people to click. */}
            <a className="btn" href="#signup">
              {COPY.heroPrimary}
            </a>
            <a className="btn btn--ghost" href="#how">
              {COPY.heroSecondary}
            </a>
          </div>
          <p className="hero__foot">{COPY.heroFootnote}</p>
        </div>
        <StoryChart />
      </div>
    </section>
  );
}

/* ---------- How it works ----------
   Three numbered steps: what happened, why, and what might happen next.     */
const STEPS = [
  {
    n: "01",
    title: "What happened",
    body: "A live price line for stocks, ETFs and crypto — with the market's open or closed status shown for each one, because crypto never sleeps and stocks do.",
  },
  {
    n: "02",
    title: "Why it happened",
    body: "Every big move gets a marker tied to its cause: an earnings report, an interest-rate decision, company news, or a whole sector sliding together.",
  },
  {
    n: "03",
    title: "What might happen next",
    body: "An estimate drawn as a range, never a single line — with the confidence in words and how often past estimates actually landed in range.",
  },
];

function HowItWorks() {
  return (
    <section id="how" className="section" aria-labelledby="how-title">
      <div className="wrap">
        <p className="eyebrow">How it works</p>
        <h2 id="how-title" className="section__title">
          One page. One move. Understood.
        </h2>
        <p className="section__lede">
          A good session isn't measured in hours on a trading screen. It's the moment one price move finally makes sense.
        </p>
        {/* <ol> = ordered (numbered) list, because the steps go in order. */}
        <ol className="steps">
          {STEPS.map((s) => (
            <li key={s.n} className="step">
              {/* The big "01" is decorative; the list is already numbered
                  for screen readers, so we hide it to avoid saying it twice. */}
              <span className="step__n" aria-hidden="true">
                {s.n}
              </span>
              <h3 className="step__title">{s.title}</h3>
              <p>{s.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

/* ---------- Features ----------
   A grid of six cards describing what's inside the dashboard.
   Each card has a `key` (also used to pick its icon), a title, a description,
   and a short sample of what the feature looks like in the real product.    */
const FEATURES = [
  {
    key: "story",
    title: "Today's story",
    body: "The single most important move for the asset you're looking at, written like a friend would tell it — then one tap to see it on the chart.",
    sample: "“Shares fell 4.1% today. The main reason: worries that big tech will slow spending on chips.”",
  },
  {
    key: "why",
    title: "Why it moved",
    body: "The three biggest moves in any timeframe, each labeled with its cause. Select one and the chart jumps to that exact day.",
    sample: "Earnings · Interest rates · Sector-wide",
  },
  {
    key: "forecast",
    title: "Honest forecasts",
    body: "Estimates from our own model, shown as a shaded range with the top factors behind it. Wide range? We tell you why.",
    sample: "“Low confidence — this asset swings a lot, so the range is wide.”",
  },
  {
    key: "calendar",
    title: "Economic calendar",
    body: "The next scheduled events that tend to move prices — rate decisions, inflation reports, jobs numbers, earnings — each with one line on why it matters.",
    sample: "Inflation report · Wed 8:30 AM ET",
  },
  {
    key: "news",
    title: "News, sorted for you",
    body: "Headlines tagged with the tickers they touch and a Positive, Negative or Mixed label — always written out, never just a color.",
    sample: "Mixed · Rate decision · 2 hours ago",
  },
  {
    key: "watch",
    title: "A watchlist that teaches",
    body: "Start with companies you already know — the maker of your phone, your favorite drink — and mix in an index fund or a crypto asset.",
    sample: "Stocks · ETFs · Crypto",
  },
];

/* FeatureIcon
   Draws a small line icon for a feature card.
   Prop: name — which icon to draw ("story", "why", "forecast", ...).
   `common` holds drawing settings shared by every icon; {...common} copies
   them onto each shape. "currentColor" means "use the text color", so the
   icons automatically change color with the theme.                          */
function FeatureIcon({ name }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" };
  const paths = {
    story: <path {...common} d="M5 4h11l3 3v13H5z M8 10h8 M8 14h8 M8 18h5" />,   // a page of text
    why: (                                                                          // a line with a marked point
      <g {...common}>
        <path d="M3 18l5-6 4 3 7-9" />
        <circle cx="12" cy="15" r="2.4" />
      </g>
    ),
    forecast: (                                                                     // a line fanning into a cone
      <g {...common}>
        <path d="M3 16l5-4 4 2 4-3" />
        <path d="M16 11l5-2" strokeDasharray="2 2.5" />
        <path d="M16 11l5-5v10z" strokeWidth="1.2" opacity="0.5" />
      </g>
    ),
    calendar: (                                                                     // a calendar
      <g {...common}>
        <rect x="4" y="5" width="16" height="15" rx="2" />
        <path d="M4 10h16 M9 3v4 M15 3v4" />
      </g>
    ),
    news: <path {...common} d="M4 6h13v12H6a2 2 0 0 1-2-2z M17 9h3v7a2 2 0 0 1-2 2 M7 9h7 M7 12h7 M7 15h4" />, // a newspaper
    watch: <path {...common} d="M12 4l2.4 5 5.6.6-4.2 3.8 1.2 5.6L12 16.2 7 19l1.2-5.6L4 9.6 9.6 9z" />,     // a star
  };
  return (
    // Icons are decorative (the card title says the same thing), so we hide
    // them from screen readers with aria-hidden.
    <svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true" focusable="false">
      {paths[name]}
    </svg>
  );
}

function Features() {
  return (
    <section id="features" className="section section--rule" aria-labelledby="features-title">
      <div className="wrap">
        <p className="eyebrow">Inside the dashboard</p>
        <h2 id="features-title" className="section__title">
          Everything that moves a price, on one page.
        </h2>
        <ul className="features">
          {FEATURES.map((f) => (
            <li key={f.key} className="feature">
              <span className="feature__icon">
                <FeatureIcon name={f.key} />
              </span>
              <h3 className="feature__title">{f.title}</h3>
              <p className="feature__body">{f.body}</p>
              <p className="feature__sample">{f.sample}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* ---------- Learning mode ----------
   Shows off the "Learning mode" feature: clickable jargon words on the left,
   and on the right a small demo card with a switch that shows or hides a
   plain-English caption under each number.                                  */
const STATS = [
  { label: "Market cap", value: "$3.1T", caption: "What it would cost to buy the entire company." },
  { label: "P/E ratio", value: "28.4", caption: "How many dollars investors pay for each $1 of yearly profit." },
  { label: "Volatility", value: "High", caption: "How much the price tends to swing up and down." },
  { label: "52-week range", value: "$96 – $131", caption: "The lowest and highest price over the past year." },
];

function LearningMode() {
  const [on, setOn] = useState(true); // is the learning-mode switch on?

  return (
    <section id="learn" className="section section--tinted" aria-labelledby="learn-title">
      <div className="wrap learn">
        {/* Left column: the explanation, with clickable glossary words. */}
        <div className="learn__copy">
          <p className="eyebrow">Learning mode</p>
          <h2 id="learn-title" className="section__title">
            Every number comes with a sentence.
          </h2>
          <p className="section__lede">
            {/* {" "} adds a real space. JSX drops spaces at line breaks, so we
                add them back where a sentence continues on the next line. */}
            Turn on Learning mode and the same dashboard explains itself. Jargon like{" "}
            <Toggletip term="index fund">A fund that buys every company in a list, like the S&P 500, so you own a small slice of all of them at once.</Toggletip>
            ,{" "}
            <Toggletip term="volatility">How much a price tends to swing. High volatility means bigger jumps — in both directions.</Toggletip>{" "}
            or <Toggletip term="earnings">The profit a company reports each quarter. Prices often move on whether it beat or missed expectations.</Toggletip>{" "}
            becomes a button you can tap for a plain definition.
          </p>
          <p className="learn__note">It's on by default for your first five sessions. Turn it off whenever you feel ready.</p>
        </div>

        {/* Right column: the demo card. */}
        <div className="card learn__demo">
          <div className="learn__bar">
            <span className="learn__demo-title" id="learn-demo-title">
              Key numbers <span className="badge">Sample</span>
            </span>
            {/* An on/off switch. It's really a <button>; role="switch" and
                aria-checked tell screen readers "this is a switch, and it's on/off". */}
            <label className="switch">
              <span className="switch__label">Learning mode</span>
              <button
                type="button"
                role="switch"
                aria-checked={on}
                className="switch__track"
                onClick={() => setOn((v) => !v)}
              >
                <span className="switch__thumb" aria-hidden="true" />
              </button>
            </label>
          </div>

          {/* <dl> is a "description list": pairs of a term (<dt>) and its
              details (<dd>). A good fit for "label: value" data. */}
          <dl className="stats" aria-labelledby="learn-demo-title">
            {STATS.map((s) => (
              <div key={s.label} className="stat">
                <dt>{s.label}</dt>
                <dd className="num stat__value">{s.value}</dd>
                {/* The plain-English caption only appears when the switch is on. */}
                {on && <dd className="stat__caption">{s.caption}</dd>}
              </div>
            ))}
          </dl>
        </div>
      </div>
    </section>
  );
}

/* ---------- Audience ----------
   Three short descriptions of the kinds of people the product is for.       */
const PEOPLE = [
  {
    who: "Starting out",
    line: "Your first paycheck, your first “should I be investing?”",
    need: "Learn what an index fund is before anyone tries to sell you one.",
  },
  {
    who: "Mid-career",
    line: "A 401(k) you contribute to and never really look at.",
    need: "Understand why your balance dropped last month — and whether it matters.",
  },
  {
    who: "Nearing retirement",
    line: "Headlines about rates and inflation feel personal now.",
    need: "See how scheduled events like rate decisions ripple through the market.",
  },
];

function Audience() {
  return (
    <section className="section" aria-labelledby="who-title">
      <div className="wrap">
        <p className="eyebrow">Built for 18 to 65</p>
        <h2 id="who-title" className="section__title">
          Wherever you're starting from.
        </h2>
        <ul className="people">
          {PEOPLE.map((p) => (
            <li key={p.who} className="person">
              <h3 className="person__who">{p.who}</h3>
              <p className="person__line">{p.line}</p>
              <p className="person__need">{p.need}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* ---------- Honesty ----------
   Builds trust: explains that forecasts are estimates, shows how accuracy is
   reported, and lists what the product will never do.                       */
function Honesty() {
  return (
    <section className="section section--rule" aria-labelledby="honest-title">
      <div className="wrap honest">
        <div>
          <p className="eyebrow">Our promise</p>
          <h2 id="honest-title" className="section__title">
            We'll show you our misses, too.
          </h2>
        </div>
        <div className="honest__body">
          <p>
            Anyone who says they know where a stock is going is guessing. Our forecasts are guesses with receipts: every estimate shows a range,
            a confidence level in words, and a running record of how often past estimates landed inside that range.
          </p>
          {/* An example accuracy number — clearly labeled as an example. */}
          <div className="honest__record card">
            <p className="honest__metric">
              <span className="num">58%</span>
              <span>of past 1-month estimates landed in range</span>
            </p>
            <p className="honest__small">Example of how accuracy is reported. Real figures appear per asset in the dashboard.</p>
          </div>
          <ul className="honest__list">
            <li>Educational only — no buy or sell buttons, ever.</li>
            <li>No brokerage logins or bank connections.</li>
            <li>Sentiment and direction are always written out, not color-coded alone.</li>
          </ul>
        </div>
      </div>
    </section>
  );
}

/* ---------- FAQ ----------
   Frequently asked questions as an "accordion": click a question to show its
   answer. Only one answer is open at a time.                                */
const FAQS = [
  {
    q: "Is this a trading app?",
    a: "No. Money Moves is for understanding the market, not trading in it. There are no buy or sell buttons and no brokerage connections. When you're ready, we'll point you to a practice mode that uses pretend money.",
  },
  {
    q: "Where do the forecasts come from?",
    a: "From our own model, which looks at things like price history, scheduled events and sector trends. Every forecast is shown as a range with a confidence level, and some assets don't get one at all when there isn't enough trading data to be honest about it.",
  },
  {
    q: "Which markets does it cover?",
    a: "US stocks, ETFs and index funds, and major cryptocurrencies. Each asset shows its own market status, since stocks follow trading hours and holidays while crypto trades around the clock.",
  },
  {
    q: "Is the data live?",
    a: "Yes — prices stream in real time while markets are open. When the stock market is closed, you'll see the last closing price and the time it was recorded, in your own time zone.",
  },
  {
    q: "Does it work with a screen reader or keyboard?",
    a: "Yes. Every chart has a written summary and a table view, you can step through data points with arrow keys, and live prices never interrupt your screen reader with constant announcements.",
  },
];

function Faq() {
  // Which question is open, by its position in the list. Starts with the
  // first one (0) open. −1 means "all closed".
  const [open, setOpen] = useState(0);
  const baseId = useId(); // a unique prefix for building matching IDs below

  return (
    <section id="faq" className="section section--tinted" aria-labelledby="faq-title">
      <div className="wrap faq">
        <div>
          <p className="eyebrow">Questions</p>
          <h2 id="faq-title" className="section__title">
            Fair questions.
          </h2>
        </div>
        <div className="faq__list">
          {FAQS.map((f, i) => {
            const isOpen = open === i;
            // Matching IDs so the question button and its answer panel can
            // point at each other for screen readers.
            const btnId = `${baseId}-q${i}`;
            const panelId = `${baseId}-a${i}`;
            return (
              <div key={f.q} className="faq__item">
                <h3 className="faq__q">
                  <button
                    id={btnId}
                    type="button"
                    aria-expanded={isOpen}  // "expanded" or "collapsed" for screen readers
                    aria-controls={panelId} // which panel this button opens
                    onClick={() => setOpen(isOpen ? -1 : i)} // clicking an open one closes it
                  >
                    <span>{f.q}</span>
                    <span className="faq__icon" aria-hidden="true">
                      {isOpen ? "−" : "+"}
                    </span>
                  </button>
                </h3>
                {/* The answer. The HTML "hidden" attribute hides it completely
                    (from screen readers too) while it's closed. */}
                <div id={panelId} role="region" aria-labelledby={btnId} hidden={!isOpen} className="faq__a">
                  <p>{f.a}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

/* ---------- Signup ----------
   The email signup form. It checks the email, shows clear error messages, and
   shows a thank-you message on success.
   NOTE: it doesn't send the email anywhere yet. See "Replace with your real
   signup request" below for where to connect your backend.                 */

/* ---------- SiteFooter ----------
   The bottom of the page: brand name, disclaimer and copyright.
   new Date().getFullYear() fills in the current year automatically.         */
function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="wrap site-footer__inner">
        <p className="brand brand--footer">
          <span className="brand__name">{BRAND}</span>
        </p>
        <p className="site-footer__disclaimer">{COPY.disclaimer}</p>
        <p className="site-footer__small">
          Sample prices and companies on this page are for demonstration only. © {new Date().getFullYear()} {BRAND}.
        </p>
      </div>
    </footer>
  );
}


/* -----------------------------------------------------------------------------
   7. THE PAGE ITSELF
   -----------------------------------------------------------------------------
   LandingPage is the main component. It stacks every section above in order.
   "export default" makes it the main thing this file provides, so another file
   (like App.jsx or main.jsx) can import it and show it:
       import LandingPage from "./LandingPage";
   -------------------------------------------------------------------------- */
export default function LandingPage() {
  const [theme, toggleTheme] = useTheme();
  usePrefersReducedMotion(); // the CSS handles motion for now; kept for future animations

  return (
    <div className="pm" id="top">
      {/* "Skip link": invisible until a keyboard user presses Tab on page
          load. It lets them jump past the header straight to the content,
          instead of tabbing through every link each time. */}
      <a className="skip-link" href="#main">
        {COPY.skip}
      </a>

      <SiteHeader theme={theme} onToggleTheme={toggleTheme} />
      <TickerStrip />

      {/* <main> marks the page's main content. tabIndex={-1} lets the skip
          link move keyboard focus here. */}
      <main id="main" tabIndex={-1}>
        <Hero />
        <HowItWorks />
        <Features />
      
        <Audience />
     
        <Faq />
       
      </main>

      <SiteFooter />
    </div>
  );
}
