import asyncio
import json

import pytest

import main
from ai.evaluation import Report
from ai.main import predict
from finance.linear_regression import FEATURES, run_regression


def _report(**overrides) -> Report:
    fields = dict(
        scored=60, pending=2, unreadable=1,
        accuracy={"personas": 0.5, "always_up": 0.45, "momentum": 0.4},
        coverage=0.8, accuracy_when_called=0.55,
        by_confidence={"0.00-0.25": (10, 0.4), "0.25-0.50": (20, 0.5), "0.50-1.00": (5, None)},
        by_strategy={"day_trader": 0.4, "long_term": 0.6}, by_age_band={"18-24": 0.5},
        strategy_weights={"day_trader": 0.9, "long_term": 1.1},
    )
    return Report(**{**fields, **overrides})


# --- argument handling -----------------------------------------------------------


def test_defaults():
    args = main.parse_args(["AAPL"])
    assert (args.tickers, args.horizon, args.weight_map) == (["AAPL"], 5, None)
    assert [m.name for m in args.mode_list] == ["default"]
    assert args.feature_list == FEATURES and not (args.live or args.audit or args.backtest)


@pytest.mark.parametrize(
    "argv",
    [
        [],  # neither a ticker nor --score
        ["AAPL", "--horizon", "0"],
        ["AAPL", "--strategy", "swing"],
        ["AAPL", "--age", "70-80"],
        ["AAPL", "--modes", "nonsense"],
        ["AAPL", "--weights", "long_term"],
        ["AAPL", "--weights", "scalper=2"],
        ["AAPL", "--weights", "long_term=-1"],
        ["AAPL", "--weights", "long_term=lots"],
        ["AAPL", "--weights", "long_term=0"],  # nobody left to vote
        ["AAPL", "--features", "return_1d"],  # only with --backtest
        ["AAPL", "--backtest", "--features", "astrology"],
    ],
)
def test_bad_arguments_exit(argv, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main.parse_args(argv)
    assert exit_info.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_weights_and_features_are_parsed():
    args = main.parse_args(["AAPL", "--weights", "long_term=2, day_trader=0.5"])
    assert args.weight_map == {"long_term": 2.0, "day_trader": 0.5}
    assert main.parse_args(["AAPL", "--weights", "auto"]).weight_map is None
    args = main.parse_args(["SPY", "--backtest", "--features", "return_1d,return_63d"])
    assert args.feature_list == ("return_1d", "return_63d")
    assert main.parse_args(["--score"]).tickers == []


def test_weights_auto_uses_the_report(capsys):
    args = main.parse_args(["AAPL", "--weights", "auto"])
    assert main.resolve_weights(args, _report()) == {"day_trader": 0.9, "long_term": 1.1}
    assert main.resolve_weights(args, _report(strategy_weights={})) is None
    assert "equal weights" in capsys.readouterr().err


def test_weights_auto_with_an_empty_log(tmp_path):
    args = main.parse_args(["AAPL", "--weights", "auto", "--log-file", str(tmp_path / "none.jsonl")])
    assert main.resolve_weights(args, None) is None  # nothing logged: no network, equal weights


# --- rendering ---------------------------------------------------------------------


def test_render_shows_the_call_and_every_persona(snapshot, fake_llm):
    prediction = asyncio.run(predict("TEST", llm=fake_llm, snapshot=snapshot))
    text = main.render(prediction)
    assert "Next 5 trading days: UP" in text and "INSIDE the horizon" in text
    assert "linear regression predicts" in text and "buy & hold" in text
    assert text.count("day_trader:") == 4 and "Audit:" not in text


def test_render_marks_failures_live_quotes_and_unclear_calls(snapshot, failing_llm):
    prediction = asyncio.run(predict("TEST", llm=failing_llm, snapshot=snapshot))
    prediction = prediction.model_copy(update={"direction": "unclear", "quote_source": "yahoo-websocket"})
    text = main.render(prediction)
    assert "UNCLEAR" in text and "live quote via yahoo-websocket" in text
    # Stored errors name the exception type only; provider messages stay out of saved results.
    assert text.count("FAILED  RuntimeError: persona generation failed") == 3
    assert "simulated API failure" not in text


def test_render_includes_the_audit(snapshot, fake_llm):
    from audit.analysis import audit_prediction

    prediction = asyncio.run(predict("TEST", llm=fake_llm, snapshot=snapshot))
    prediction.audit = asyncio.run(audit_prediction(prediction, snapshot, fake_llm))
    text = main.render(prediction)
    assert "Risk: HIGH" in text and "[high] earnings:" in text
    assert "Beat on revenue." in text and "https://finance.yahoo.com/news/test-corp-beats" in text
    assert "couldn't be checked" in text  # the fixture has no quoteType / currency


def test_render_report():
    assert main.render_report(_report(scored=0)).startswith("No predictions have resolved yet")
    text = main.render_report(_report())
    assert "Scored 60 predictions" in text and "always_up" in text
    assert "n=5    n/a" in text  # empty bucket
    assert "long_term       1.100" in text


def test_render_backtest(snapshot):
    result = run_regression(snapshot.daily, 5, features=("return_1d", "rsi_14"))
    text = main.render_backtest("TEST", result)
    assert text.startswith("TEST linear-regression baseline, 5-day horizon")
    assert "return_1d" in text and "rsi_14" in text and "volume_vs_20d" not in text


def test_backtest_entry_point(snapshot, monkeypatch, capsys):
    monkeypatch.setattr(main, "fetch_daily", lambda ticker: snapshot.daily)
    args = main.parse_args(["test", "--backtest", "--horizon", "1"])
    assert main.run_backtests(args) == 0
    assert "TEST linear-regression baseline, 1-day horizon" in capsys.readouterr().out
    monkeypatch.setattr(main, "fetch_daily", lambda ticker: snapshot.daily.iloc[:0])
    assert main.run_backtests(args) == 1


# --- predicting --------------------------------------------------------------------


def test_predict_all_logs_and_prints(snapshot, fake_llm, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(main, "fetch_snapshot", lambda ticker: snapshot)
    log = tmp_path / "log.jsonl"
    args = main.parse_args(["TEST", "--audit", "--json", "--log-file", str(log),
                            "--weights", "day_trader=10"])
    failures = asyncio.run(main._predict_all(args, args.weight_map, llm=fake_llm))
    assert failures == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["direction"] == "down"  # day traders outvote the rest at weight 10
    assert printed["audit"]["risk"]["level"] == "high"
    assert json.loads(log.read_text().splitlines()[0])["id"] == printed["id"]


def test_predict_all_reports_failures_and_keeps_going(snapshot, fake_llm, monkeypatch, capsys):
    def fetch(ticker):
        if ticker == "BAD":
            raise ValueError("No price history for 'BAD'")
        return snapshot

    monkeypatch.setattr(main, "fetch_snapshot", fetch)
    args = main.parse_args(["BAD", "TEST", "--no-log"])
    assert asyncio.run(main._predict_all(args, None, llm=fake_llm)) == 1
    captured = capsys.readouterr()
    assert "BAD: error: No price history" in captured.err and "TEST  last" in captured.out


def test_missing_api_key_fails_every_ticker(monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    args = main.parse_args(["AAPL", "MSFT"])
    assert asyncio.run(main._predict_all(args, None)) == 2
    assert "GEMINI_API_KEY is not set" in capsys.readouterr().err


def test_main_exits_nonzero_on_failure(snapshot, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "load_dotenv", lambda path: None)  # keep the real .env out of tests
    monkeypatch.setattr(main, "fetch_daily", lambda ticker: snapshot.daily.iloc[:0])
    with pytest.raises(SystemExit) as exit_info:
        main.main(["NOPE", "--backtest"])
    assert exit_info.value.code == 1


def test_score_report_explains_pending_predictions():
    from types import SimpleNamespace

    from ai.evaluation import Report
    from main import render_report

    waiting = SimpleNamespace(
        prediction=SimpleNamespace(ticker="AAPL", data_as_of="2026-11-25", horizon_days=2),
        detail="The 2-trading-day horizon ends on 2026-11-30 (Monday).",
    )
    report = Report(scored=0, pending=1, unreadable=0, accuracy={}, coverage=None,
                    accuracy_when_called=None, by_confidence={}, by_strategy={}, by_age_band={},
                    pending_details=[waiting])
    text = render_report(report)
    assert "Pending, and why:" in text
    assert "AAPL   2026-11-25 +2d  The 2-trading-day horizon ends on 2026-11-30 (Monday)." in text
