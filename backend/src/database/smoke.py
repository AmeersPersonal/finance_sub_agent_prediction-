"""Live end-to-end check against real providers, Gemini and the configured database.

Not a pytest test: it uses the network, spends Gemini quota and writes one real
forecast to DATABASE_URL. Run from backend/src with the venv active:

    python -m database.smoke AAPL              # 3 personas (one per strategy)
    python -m database.smoke AAPL --skip-live  # only the 5-day backdated check

Part 1 (live) runs predict_and_store and verifies what was saved: the frozen
regression dataset, the per-strategy evidence, and the API's view of the run.

Part 2 (backdated) cuts the fetched price history back 5 trading sessions,
forecasts from that point, and scores it against the real closes since. It is a
pipeline check of resolve/score on real yfinance data, NOT an accuracy result:
fundamentals, options, analyst data and headlines are still today's values, so
the forecast sees information from after its pretend date. Nothing from part 2
is saved to the database.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import exchange_calendars as xcals
import pandas as pd
from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
AGE_BAND = "25-39"  # eligible for every strategy: 3 personas, light on Gemini quota

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(("  PASS  " if ok else "  FAIL  ") + message)
    if not ok:
        failures.append(message)


def last_settled_session(now: datetime) -> pd.Timestamp:
    calendar = xcals.get_calendar("XNYS")
    session = calendar.date_to_session(pd.Timestamp(now.date()), direction="previous")
    if pd.Timestamp(now) < calendar.session_close(session) + pd.Timedelta(minutes=30):
        session = calendar.previous_session(session)
    return session


async def live(ticker: str, horizon: int) -> None:
    from api.main import app
    from database.connection import connect
    from database.service import predict_and_store
    from fastapi.testclient import TestClient

    print(f"\n[1] Live forecast for {ticker} (saved to DATABASE_URL)")
    p = await predict_and_store(ticker, horizon_days=horizon, age_bands=[AGE_BAND])
    print(f"  prediction {p.id}: {p.direction} (strength {p.confidence}), data as of {p.data_as_of}")
    for warning in p.data_warnings:
        print(f"  warning: {warning}")

    dataset = p.input_snapshot.get("regression_dataset") or {}
    check(bool(dataset.get("dataset_id")), "forecast records a frozen regression dataset id")
    with connect() as connection:
        row = connection.execute(
            "SELECT ticker, metadata, jsonb_array_length(price_rows) AS n FROM model_datasets WHERE id = %s",
            (dataset.get("dataset_id"),)).fetchone()
        check(row is not None and row["n"] == dataset.get("rows"),
              f"model_datasets row exists with {dataset.get('rows')} price rows")
        if row is not None:
            check(row["metadata"]["sha256"] == dataset.get("sha256"), "saved dataset fingerprint matches the forecast")
        evidence = connection.execute(
            "SELECT evidence_role, metadata->>'strategy' AS strategy, metadata->'cited_by' AS cited_by "
            "FROM prediction_evidence WHERE run_id = %s", (p.id,)).fetchall()
    by_strategy = Counter(r["strategy"] for r in evidence)
    print(f"  evidence passages by strategy: {dict(by_strategy) or 'none'}")
    print(f"  evidence roles: {dict(Counter(r['evidence_role'] for r in evidence)) or 'none'}")
    cited = sum(1 for r in evidence if r["cited_by"])
    print(f"  passages cited by at least one persona: {cited}/{len(evidence)}")
    check(len(evidence) == sum(len(s["strategies"]) for s in p.sources),
          "saved evidence matches the forecast's source list")
    if not evidence:
        print("  note: no documents retrieved (check the Yahoo feed and SEC_USER_AGENT warnings above)")

    with TestClient(app) as client:
        response = client.get(f"/predictions/{p.id}")
        check(response.status_code == 200 and response.json().get("id") == p.id,
              "API returns the saved prediction")
        response = client.get(f"/predictions/{p.id}/evaluation")
        check(response.status_code == 200, "API evaluation endpoint answers (pending until the horizon passes)")


async def backdated(ticker: str, horizon: int) -> None:
    from ai.evaluation import MARKET_TZ, fetch_closes, score
    from ai.main import predict
    from ai.tool import fetch_snapshot

    now = datetime.now(MARKET_TZ)
    target = last_settled_session(now)
    as_of = xcals.get_calendar("XNYS").session_offset(target, -horizon)
    print(f"\n[2] Backdated pipeline check: forecast as of {as_of.date()}, scored on {target.date()} "
          "(not saved; leaks today's fundamentals/news, so not an accuracy result)")

    snapshot = await asyncio.to_thread(fetch_snapshot, ticker)
    cut = lambda frame: None if frame is None else frame[frame.index.date <= as_of.date()]
    snapshot.daily = cut(snapshot.daily)
    for name in ("market_daily", "nasdaq_daily", "sector_daily", "vix_daily"):
        setattr(snapshot, name, cut(getattr(snapshot, name)))
    snapshot.intraday = None  # intraday bars after the pretend date would leak the outcome
    check(not snapshot.daily.empty and snapshot.daily.index[-1].date() == as_of.date(),
          f"history cut back to {as_of.date()}")
    snapshot.last_price = float(snapshot.daily["Close"].iloc[-1])
    snapshot.previous_close = float(snapshot.daily["Close"].iloc[-2])
    snapshot.fetched_at = datetime.combine(as_of.date(), datetime.min.time(), timezone.utc)

    p = await predict(ticker, horizon_days=horizon, age_bands=[AGE_BAND], snapshot=snapshot,
                      documents_by_strategy={})
    print(f"  forecast: {p.direction} (strength {p.confidence}), entry {p.last_price:.2f}, "
          f"flat band ±{p.flat_band_pct:.2f}%")
    closes = await asyncio.to_thread(fetch_closes, [ticker], as_of.date())
    check(ticker in closes, "fetched real closes for scoring")
    if ticker not in closes:
        return
    series = closes[ticker]
    print(f"  provider basis: {series.attrs.get('price_basis')}, calendar {series.attrs.get('calendar')}, "
          f"splits since entry: {series.attrs.get('stock_splits') or 'none'}")
    report = score([p], closes, now)
    check(report.scored == 1, "scorer resolved the forecast on the expected session")
    if report.outcomes:
        outcome = report.outcomes[0]
        check(outcome.resolved_on == target.date(), f"resolved on {outcome.resolved_on}")
        print(f"  actual: {outcome.actual} ({outcome.return_pct:+.2f}%, split factor {outcome.split_factor})")
        for name, hit in report.accuracy.items():
            call = p.direction if name == "personas" else p.baselines.get(name)
            print(f"    {name:18} called {str(call):8} -> {'right' if hit else 'wrong'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ticker")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--skip-live", action="store_true", help="skip the database-saving live forecast")
    args = parser.parse_args()
    load_dotenv(ENV_FILE)
    ticker = args.ticker.strip().upper()
    if not args.skip_live:
        asyncio.run(live(ticker, args.horizon))
    asyncio.run(backdated(ticker, args.horizon))
    print(f"\n{'All checks passed.' if not failures else f'{len(failures)} check(s) failed.'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
