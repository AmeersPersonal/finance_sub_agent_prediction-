import asyncio
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

import ml.__main__ as cli
from ai.agents import PROMPT_VERSION
from ai.evaluation import BENCHMARK, Report, load_log, score
from ml.replay import (
    BLIND_SOURCES,
    PriceBook,
    ReplayTask,
    as_of_view,
    blind_snapshot,
    cluster_ci,
    compare,
    compare_runs,
    fetch_price_book,
    plan,
    replay_sessions,
    run_replay,
    verdict,
)
from test_ml import _outcome, _view

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=NY)  # a Saturday: Friday 2026-10-09 has settled
LAST = date(2026, 10, 9)


def _raw(seed: int, start_price: float = 100.0, days: int = 700, ends: date = LAST) -> pd.DataFrame:
    """Raw daily bars as Yahoo returns them with auto_adjust=False, actions=True."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range(end=pd.Timestamp(ends), periods=days)
    close = start_price * np.exp(np.cumsum(rng.normal(0.0003, 0.012, days)))
    return pd.DataFrame(
        {"Open": close * 0.999, "High": close * 1.01, "Low": close * 0.99, "Close": close,
         "Volume": rng.integers(1_000_000, 5_000_000, days).astype(float),
         "Dividends": 0.0, "Stock Splits": 0.0},
        index=index,
    )


def _book(tickers=("AAA", "BBB"), sector="Technology") -> PriceBook:
    book = PriceBook()
    symbols = {"SPY": 400, "QQQ": 500, "^VIX": 18, "^IRX": 4, "^FVX": 4, "^TNX": 4, "XLK": 200}
    for i, (symbol, price) in enumerate(symbols.items()):
        book.frames[symbol], book.splits[symbol] = _raw(i, price), {}
    for i, ticker in enumerate(tickers):
        book.frames[ticker] = _raw(20 + i)
        book.splits[ticker], book.sectors[ticker], book.names[ticker] = {}, sector, f"{ticker} Corp"
    return book


# --- which days -----------------------------------------------------------------


def test_replay_dates_end_where_the_longest_outcome_has_settled():
    assert replay_sessions(NOW, 5, 3, 5) == [date(2026, 9, 18), date(2026, 9, 25), date(2026, 10, 2)]
    assert replay_sessions(NOW, 1, 2, 1) == [date(2026, 10, 7), date(2026, 10, 8)]
    assert replay_sessions(NOW, 5, 3, 5, after=date(2026, 9, 25)) == [date(2026, 9, 25), date(2026, 10, 2)]


def test_a_session_that_has_not_settled_is_not_used():
    friday_afternoon = datetime(2026, 10, 9, 15, 0, tzinfo=NY)  # before the close + 30 minutes
    assert replay_sessions(friday_afternoon, 1, 1, 1) == [date(2026, 10, 7)]
    assert replay_sessions(datetime(2026, 10, 9, 17, 0, tzinfo=NY), 1, 1, 1) == [date(2026, 10, 8)]
    with pytest.raises(ValueError):
        replay_sessions(NOW, 5, 0, 5)


def test_plan_is_every_ticker_date_and_horizon():
    tasks = plan(["A", "B"], [date(2026, 9, 25), date(2026, 10, 2)], [1, 5])
    assert len(tasks) == 8 and tasks[0] == ReplayTask("A", date(2026, 9, 25), 1)


# --- the as-of view -------------------------------------------------------------


def test_view_restates_prices_in_the_units_of_the_day():
    frame = _raw(0, 50.0)
    split = date(2026, 9, 30)  # a 2:1 split after the forecast date: Yahoo has halved the history
    view = as_of_view(frame, date(2026, 9, 25), {split: 2.0})
    assert view.index[-1].date() == date(2026, 9, 25)
    last = frame.loc[frame.index.date == date(2026, 9, 25)].iloc[0]
    assert view["Close"].iloc[-1] == pytest.approx(2 * last["Close"])
    assert view["Volume"].iloc[-1] == pytest.approx(last["Volume"] / 2)
    after = as_of_view(frame, date(2026, 10, 2), {split: 2.0})  # the split is already behind it
    assert after["Close"].iloc[-1] == pytest.approx(frame.loc[frame.index.date == date(2026, 10, 2)].iloc[0]["Close"])


def test_blind_snapshot_has_prices_and_nothing_from_after_the_date():
    as_of = date(2026, 9, 25)
    snap = blind_snapshot("AAA", as_of, _book())
    assert snap.daily.index[-1].date() == as_of and snap.last_price == snap.daily["Close"].iloc[-1]
    for frame in (snap.market_daily, snap.nasdaq_daily, snap.vix_daily, snap.sector_daily):
        assert frame is not None and frame.index[-1].date() <= as_of
    assert snap.sector_etf == "XLK"
    assert set(snap.yields) == {"3m", "5y", "10y"}
    assert all(s.index[-1].date() <= as_of and len(s) <= 63 for s in snap.yields.values())
    assert snap.info == {"sector": "Technology", "shortName": "AAA Corp", "quoteType": "EQUITY"}
    # Everything that is today's value is withheld and listed as unavailable.
    assert snap.intraday is None and snap.options is None and snap.income_stmt is None
    assert snap.headlines == [] and snap.news == [] and snap.earnings_dates == []
    assert snap.price_targets == {} and snap.rating_changes is None and snap.labor == {}
    assert set(snap.errors) == set(BLIND_SOURCES)


def test_blind_snapshot_refuses_what_it_cannot_forecast_from():
    book = _book()
    with pytest.raises(ValueError, match="no bar for 2026-10-10"):
        blind_snapshot("AAA", date(2026, 10, 10), book)
    book.frames["AAA"] = book.frames["AAA"].iloc[-100:]
    with pytest.raises(ValueError, match="only"):
        blind_snapshot("AAA", date(2026, 9, 25), book)
    with pytest.raises(KeyError):
        blind_snapshot("ZZZ", date(2026, 9, 25), book)


def test_price_book_collects_what_each_ticker_needs_and_reports_the_rest():
    frames = {s: _raw(i) for i, s in enumerate(["SPY", "QQQ", "^VIX", "^IRX", "^FVX", "^TNX", "XLK", "AAA"])}
    frames["AAA"].loc[frames["AAA"].index[-10], "Stock Splits"] = 4.0

    def fetch(symbol):
        if symbol == "BAD":
            raise ConnectionError("down")
        return frames.get(symbol, pd.DataFrame())

    book, problems = fetch_price_book(
        ["AAA", "BAD", "NONE"], fetch=fetch, sector_of=lambda t: ("Technology", f"{t} Corp"))
    assert set(book.frames) >= {"AAA", "SPY", "^VIX", "XLK"} and "BAD" not in book.frames
    assert problems["BAD"].startswith("ConnectionError") and problems["NONE"] == "no price history"
    assert list(book.splits["AAA"].values()) == [4.0] and "Dividends" not in book.frames["AAA"]


# --- running --------------------------------------------------------------------


def test_replay_forecasts_each_task_once_and_resumes(fake_llm, tmp_path):
    out = tmp_path / "replay.jsonl"
    tasks = plan(["AAA", "BBB"], [date(2026, 9, 18), date(2026, 9, 25)], [1, 5])
    progress = []
    run = asyncio.run(run_replay(tasks, _book(), fake_llm, out, age_bands=["25-39"],
                                 progress=progress.append))
    assert (run.done, run.skipped, run.failed, run.unavailable, run.aborted) == (8, 0, [], [], None)
    predictions, _ = load_log(out)
    assert len(predictions) == 8 and len(progress) == 8
    assert {p.data_as_of for p in predictions} == {"2026-09-18", "2026-09-25"}
    assert {p.horizon_days for p in predictions} == {1, 5}
    assert all(p.prompt_version == PROMPT_VERSION and "replay: backdated to" in p.data_warnings[-1]
               for p in predictions)
    assert len(fake_llm.calls) == 8 * 3  # three personas at one age band, no documents, no sentiment
    for _, prompt in fake_llm.calls:
        assert "income_stmt" in prompt and "unavailable_sources" in prompt  # told what is missing

    again = asyncio.run(run_replay(tasks, _book(), fake_llm, out, age_bands=["25-39"]))
    assert (again.done, again.skipped) == (0, 8) and len(load_log(out)[0]) == 8
    assert len(fake_llm.calls) == 8 * 3  # nothing was asked twice


def test_replay_notes_tickers_without_a_bar_that_day(fake_llm, tmp_path):
    book = _book(("AAA",))
    book.frames["AAA"] = book.frames["AAA"].drop(
        book.frames["AAA"].index[book.frames["AAA"].index.date == date(2026, 9, 25)])
    run = asyncio.run(run_replay(plan(["AAA", "NOPE"], [date(2026, 9, 25)], [5]), book, fake_llm,
                                 tmp_path / "r.jsonl", age_bands=["25-39"]))
    assert run.done == 0 and len(run.unavailable) == 2
    assert "no bar for 2026-09-25" in run.unavailable[0][1]


class _Broken:
    model = "broken"

    async def generate_json(self, *args, **kwargs):
        raise RuntimeError("quota exhausted")


def test_replay_stops_when_forecasts_keep_failing(tmp_path):
    tasks = plan(["AAA", "BBB"], [date(2026, 9, 11), date(2026, 9, 18), date(2026, 9, 25)], [5])
    run = asyncio.run(run_replay(tasks, _book(), _Broken(), tmp_path / "r.jsonl", age_bands=["25-39"],
                                 concurrency=1, max_failures=3))
    assert run.done == 0 and len(run.failed) == 3 and "3 forecasts in a row failed" in run.aborted
    assert not (tmp_path / "r.jsonl").exists()


# --- scored against what followed -------------------------------------------------


def test_a_replayed_forecast_scores_on_the_real_return_even_across_a_split(fake_llm, tmp_path):
    book = _book(("AAA",))
    split = date(2026, 9, 30)
    # What it was worth per share in the units of each day: V before the 2:1 split, and the
    # same V is quoted as V/2 once it has split. Yahoo restates the earlier days, so today's
    # history is V/2 throughout.
    traded = book.frames["AAA"]["Close"].copy()
    frame = book.frames["AAA"].copy()
    for column in ("Open", "High", "Low", "Close"):
        frame[column] = frame[column] / 2
    frame.loc[frame.index.date < split, "Volume"] *= 2
    book.frames["AAA"], book.splits["AAA"] = frame, {split: 2.0}

    out = tmp_path / "r.jsonl"
    asyncio.run(run_replay(plan(["AAA"], [date(2026, 9, 25)], [5]), book, fake_llm, out,
                           age_bands=["25-39"]))
    (prediction,) = load_log(out)[0]
    entry = float(traded[traded.index.date == date(2026, 9, 25)].iloc[0])
    assert prediction.last_price == pytest.approx(entry)  # the units of its own day

    closes = pd.Series(frame["Close"].to_numpy(), index=[ts.date() for ts in frame.index])
    closes.attrs.update(price_basis="yahoo_split_adjusted_close", actions_verified=True,
                        calendar="XNYS", stock_splits={split.isoformat(): 2.0})
    report = score([prediction], {"AAA": closes}, NOW)
    assert report.scored == 1
    outcome = report.outcomes[0]
    expected = float(traded[traded.index.date == date(2026, 10, 2)].iloc[0]) / entry - 1
    assert outcome.return_pct == pytest.approx(expected * 100, abs=0.01)
    assert outcome.split_factor == 2.0


# --- how sure the estimate is -----------------------------------------------------


def test_cluster_ci_widens_when_rows_share_a_date():
    flat = cluster_ci([1.0] * 12, ["a"] * 6 + ["b"] * 6)
    assert flat.mean == flat.low == flat.high == 1.0 and (flat.n, flat.clusters) == (12, 2)
    values = [1, 1, 1, 1, 0, 0, 0, 0]
    together = cluster_ci(values, ["a", "a", "a", "a", "b", "b", "b", "b"])
    apart = cluster_ci(values, list("abcdefgh"))
    assert together.mean == apart.mean == 0.5
    assert together.high - together.low > apart.high - apart.low  # same rows, fewer independent dates
    assert cluster_ci([], []).n == 0


@pytest.mark.parametrize("edge, words", [
    (dict(mean=0.08, low=0.04, high=0.12), "clears the gate margin"),
    (dict(mean=0.02, low=0.005, high=0.04), "not by the gate margin"),
    (dict(mean=-0.05, low=-0.09, high=-0.01), "behind always-up"),
    (dict(mean=0.0, low=-0.05, high=0.05), "can't be told apart"),
])
def test_verdict_reads_the_interval_not_the_mean(edge, words):
    from ml.replay import Estimate

    assert words in verdict(Estimate(n=100, clusters=10, **edge))


def _scored(day, actual, direction_votes, *, ticker="AAA", horizon=5, **fields):
    views = {f"long_term:25-39": [("default", _view(direction_votes, 0.9))]}
    outcome = _outcome(day, actual, views, ticker=ticker)
    return outcome


def test_compare_pairs_personas_with_always_up_on_the_same_rows():
    days = pd.bdate_range("2026-08-03", periods=20, freq="5B")
    outcomes = []
    for k, day in enumerate(days):
        actual = ["up", "down", "up", "flat"][k % 4]
        outcomes.append(_scored(day.date(), actual, actual))  # personas always right
    (absolute,) = [c for c in compare(outcomes) if c.target == "absolute"]
    assert absolute.horizon_days == 5 and absolute.n == 20 and absolute.dates == 20
    assert absolute.personas.mean == 1.0 and absolute.always_up.mean == 0.5
    assert absolute.edge_vs_always_up.mean == pytest.approx(0.5)
    assert verdict(absolute.edge_vs_always_up) == "clears the gate margin"
    assert absolute.called_share == 1.0 and absolute.accuracy_when_called == 1.0
    assert absolute.regression is None  # these rows logged no regression call


def test_cli_replay_dry_run_prints_the_plan_and_spends_nothing(capsys, monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr("ai.llm.build_llm", lambda: pytest.fail("a dry run must not build the LLM"))
    cli.main(["replay", "--dry-run", "aapl", "msft", "--dates", "2", "--horizon", "5", "--age", "25-39"])
    out = capsys.readouterr().out
    assert "2 tickers x 2 dates" in out and "= 4 forecasts" in out and "12 Gemini calls" in out
    assert f"prompt version {PROMPT_VERSION}" in out and f"replay-v{PROMPT_VERSION}.jsonl" in out
    cli.main(["replay", "--dry-run", "AAPL", "--dates", "2", "--step", "2", "--horizon", "5"])
    assert "outcome windows overlap" in capsys.readouterr().out


def test_cli_replay_report_scores_an_existing_file(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    days = pd.bdate_range("2026-08-03", periods=40, freq="5B")
    outcomes = [_scored(d.date(), ["up", "down", "up"][k % 3], ["up", "down", "up"][k % 3]) for k, d in enumerate(days)]
    report = Report(scored=40, pending=0, unreadable=0, accuracy={}, coverage=None,
                    accuracy_when_called=None, by_confidence={}, by_strategy={}, by_age_band={},
                    outcomes=outcomes)
    out = tmp_path / "replay.jsonl"
    out.write_text("{}\n")
    monkeypatch.setattr(cli, "score_log", lambda path: report)
    cli.main(["replay", "--report-only", "--out", str(out)])
    text = capsys.readouterr().out
    assert "Replay: 40 forecasts scored" in text and "a floor for the live app" in text
    assert "5-day horizon, outcome: 40 forecasts on 40 dates" in text
    assert "personas - always up" in text and "Where the personas went wrong" in text
    assert "Call policy that these rows would give (not saved)" in text
    with pytest.raises(SystemExit):  # nothing to report on is a failure
        cli.main(["replay", "--report-only", "--out", str(tmp_path / "missing.jsonl")])
    assert "No replay file at" in capsys.readouterr().out


def test_two_runs_are_compared_on_the_rows_they_share():
    days = pd.bdate_range("2026-08-03", periods=20, freq="5B")
    actuals = [["up", "down", "up", "flat"][k % 4] for k in range(20)]
    better = [_scored(d.date(), a, a) for d, a in zip(days, actuals)]  # always right
    worse = [_scored(d.date(), a, "up") for d, a in zip(days, actuals)]  # always up
    extra = _scored(date(2026, 12, 1), "up", "up", ticker="ZZZ")  # only in one run
    (change,) = compare_runs(better + [extra], worse)
    assert change.n == 20 and change.dates == 20
    assert change.this_run.mean == 1.0 and change.other_run.mean == 0.5
    assert change.change.mean == pytest.approx(0.5) and change.change.low > 0
    assert compare_runs(better, []) == []


def test_cli_replay_against_prints_the_paired_change(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    days = pd.bdate_range("2026-08-03", periods=30, freq="5B")
    actuals = [["up", "down", "up"][k % 3] for k in range(30)]

    def report(direction):
        outcomes = [_scored(d.date(), a, direction(a)) for d, a in zip(days, actuals)]
        return Report(scored=30, pending=0, unreadable=0, accuracy={}, coverage=None,
                      accuracy_when_called=None, by_confidence={}, by_strategy={}, by_age_band={},
                      outcomes=outcomes)

    reports = {"new.jsonl": report(lambda a: a), "old.jsonl": report(lambda a: "up")}
    for name in reports:
        (tmp_path / name).write_text("{}\n")
    monkeypatch.setattr(cli, "score_log", lambda path: reports[Path(path).name])
    cli.main(["replay", "--report-only", "--out", str(tmp_path / "new.jsonl"),
              "--against", str(tmp_path / "old.jsonl")])
    text = capsys.readouterr().out
    assert "This run (new.jsonl) against old.jsonl" in text and "this - other" in text and "better" in text
