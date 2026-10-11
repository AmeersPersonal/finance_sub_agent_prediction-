"""Command-line entry point.

    python main.py AAPL                       # predict and log
    python main.py AAPL MSFT NVDA --horizon 1
    python main.py AAPL --strategy day_trader --age 18-24 --age 25-39
    python main.py AAPL --modes temps         # each persona at 3 temperatures
    python main.py AAPL --weights long_term=2,day_trader=0.5
    python main.py AAPL --weights auto        # weights from the scored log
    python main.py AAPL --live --audit        # websocket price; risk, checks and news digest
    python main.py AAPL --json
    python main.py --score                    # score logged predictions whose horizon passed
    python main.py SPY --backtest             # regression walk-forward only, no LLM
    python main.py SPY --backtest --features return_1d,return_63d
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import sys
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from ai.evaluation import DEFAULT_LOG, Report, log_prediction, score_log
from ai.live import live_feed_from_env
from ai.llm import JsonLLM, build_llm
from ai.main import predict
from ai.modes import resolve_modes
from ai.personas import AGE_BANDS, Strategy
from ai.schemas import Prediction
from ai.tool import clean_daily, fetch_daily, fetch_snapshot
from audit.analysis import audit_prediction
from finance.linear_regression import FEATURE_FUNCTIONS, FEATURES, RegressionResult, run_regression

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def parse_weights(spec: str) -> dict[str, float]:
    """'long_term=2,day_trader=0.5' -> {'long_term': 2.0, 'day_trader': 0.5}."""
    strategies = {s.value for s in Strategy}
    weights: dict[str, float] = {}
    for part in spec.split(","):
        name, sep, raw = (piece.strip() for piece in part.partition("="))
        if not sep or name not in strategies:
            raise ValueError(
                f"bad weight {part.strip()!r}: use strategy=number with strategies "
                f"{', '.join(sorted(strategies))}, or 'auto'"
            )
        try:
            weight = float(raw)
        except ValueError:
            raise ValueError(f"bad weight {part.strip()!r}: {raw!r} isn't a number") from None
        if not math.isfinite(weight) or weight < 0:
            raise ValueError(f"bad weight {part.strip()!r}: must be zero or more")
        weights[name] = weight
    if not any(weights.values()):
        raise ValueError("at least one weight must be above zero")
    return weights


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Predict a stock's direction from trader personas")
    parser.add_argument("tickers", nargs="*")
    parser.add_argument("--horizon", type=int, default=5, help="trading days ahead (default 5)")
    parser.add_argument(
        "--strategy", action="append", choices=[s.value for s in Strategy],
        help="run only these strategies (repeatable)",
    )
    parser.add_argument(
        "--age", action="append", choices=[b.label for b in AGE_BANDS],
        help="run only these age bands (repeatable)",
    )
    parser.add_argument(
        "--modes", default="default",
        help="reasoning modes: a preset (default, temps, models, full) or comma-separated "
        "mode names; every persona runs once per mode",
    )
    parser.add_argument(
        "--weights",
        help="strategy weights, e.g. long_term=2,day_trader=0.5 (missing strategies weigh 1), "
        "or 'auto' to derive them from the scored prediction log",
    )
    parser.add_argument(
        "--live", action="store_true", help="take the last price from Yahoo's live websocket"
    )
    parser.add_argument(
        "--audit", action="store_true",
        help="add a company overview, data checks, a risk checklist and a news digest "
        "(one extra LLM call)",
    )
    parser.add_argument("--json", action="store_true", help="print the full prediction as JSON")
    parser.add_argument("--score", action="store_true", help="score the prediction log")
    parser.add_argument(
        "--backtest", action="store_true",
        help="walk-forward backtest of the linear-regression baseline only (no LLM, not logged)",
    )
    parser.add_argument(
        "--features",
        help=f"with --backtest: comma-separated regression features; known: "
        f"{', '.join(FEATURE_FUNCTIONS)}",
    )
    parser.add_argument("--no-log", action="store_true", help="don't append to the prediction log")
    parser.add_argument("--database", action="store_true", help="save/read predictions in PostgreSQL instead of JSONL")
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    if not args.tickers and not args.score:
        parser.error("give at least one ticker, or --score")
    if args.horizon < 1:
        parser.error("--horizon must be at least 1")
    try:
        args.mode_list = resolve_modes(args.modes)
    except ValueError as exc:
        parser.error(str(exc))
    args.weight_map = None
    if args.weights and args.weights != "auto":
        try:
            args.weight_map = parse_weights(args.weights)
        except ValueError as exc:
            parser.error(str(exc))
    args.feature_list = FEATURES
    if args.features:
        if not args.backtest:
            parser.error("--features only applies to --backtest")
        args.feature_list = tuple(f.strip() for f in args.features.split(",") if f.strip())
        unknown = [f for f in args.feature_list if f not in FEATURE_FUNCTIONS]
        if unknown or not args.feature_list:
            parser.error(f"unknown features {unknown}; choose from {', '.join(FEATURE_FUNCTIONS)}")
    return args


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _regression_lines(lr: dict) -> list[str]:
    lines = [
        f"  linear regression predicts {lr['predicted_return_pct']:+.2f}%; walk-forward since "
        f"{lr['test_start']}: {lr['oos_accuracy']:.0%} right vs always-up "
        f"{lr['always_up_accuracy']:.0%} (R^2 {lr['oos_r2']:+.3f}, n={lr['n_test']})"
    ]
    for label, m in (("trading it", lr["strategy"]), ("buy & hold", lr["buy_and_hold"])):
        lines.append(
            f"  {label:<10} ({lr['cost_bps']:g} bps costs): return {m['total_return_pct']:+.1f}%  "
            f"Sharpe {_ratio(m['sharpe'])}  Sortino {_ratio(m['sortino'])}  "
            f"max DD {m['max_drawdown_pct']:.1f}%  profit factor {_ratio(m['profit_factor'])}"
        )
    return lines


def _audit_lines(audit: dict) -> list[str]:
    lines = ["", "Audit:"]
    company = audit.get("company") or {}
    if company.get("name"):
        where = " / ".join(x for x in (company.get("sector"), company.get("industry")) if x)
        lines.append(f"  {company['name']}" + (f" ({where})" if where else ""))
    checks = audit.get("checks") or []
    failed = [c for c in checks if c["ok"] is False]
    unknown = [c for c in checks if c["ok"] is None]
    lines.append(
        f"  Data checks: {len(checks) - len(failed) - len(unknown)}/{len(checks)} passed"
        + (f", {len(unknown)} couldn't be checked" if unknown else "")
    )
    lines += [f"    FAILED {c['check']}: {c['detail']}" for c in failed]
    risk = audit.get("risk") or {}
    lines.append(f"  Risk: {risk.get('level', 'n/a').upper()}")
    lines += [f"    [{f['level']}] {f['factor']}: {f['detail']}" for f in risk.get("flags", [])]
    news = audit.get("news")
    if news:
        lines.append(f"  News: {news['summary']}")
        for item in news["items"]:
            text = item["tldr"] or item["title"]
            meta = ", ".join(x for x in (item["source"], item["published"]) if x)
            lines.append(f"    - {text}" + (f" ({meta})" if meta else ""))
            if item["link"]:
                lines.append(f"      {item['link']}")
    lines += [f"  warning: {w}" for w in audit.get("warnings", [])]
    return lines


def render(p: Prediction) -> str:
    quote = "" if p.quote_source == "yfinance" else f", live quote via {p.quote_source}"
    lines = [
        f"{p.ticker}  last {p.last_price:.2f}  (data as of {p.data_as_of}, model {p.model}{quote})",
        "",
    ]
    head = f"Next {p.horizon_days} trading days:"
    if p.direction in ("up", "down"):
        lines.append(
            f"{head} {p.direction.upper()}  strength {p.confidence:.2f}  "
            f"agreement {p.agreement:.0%}  net {p.net_score:+.2f}"
        )
    elif p.direction == "flat":
        lines.append(
            f"{head} FLAT (within +/-{p.flat_band_pct:g}%)  strength {p.confidence:.2f}  "
            f"agreement {p.agreement:.0%}"
        )
    else:
        lines.append(f"{head} UNCLEAR, personas split or lean only weakly (net {p.net_score:+.2f})")
    lines.append(f"Flat band: +/-{p.flat_band_pct:g}% (scaled to this stock's volatility)")
    if p.next_earnings_date:
        where = "INSIDE the horizon" if p.earnings_within_horizon else "after the horizon"
        lines.append(f"Next earnings: {p.next_earnings_date} ({where})")
    if p.headline_sentiment:
        s = p.headline_sentiment
        lines.append(
            f"Headline sentiment: {s['overall']:+.2f} ({s['positive']} positive, "
            f"{s['negative']} negative, {s['neutral']} neutral). {s['summary']}"
        )
    if p.risk:
        r = p.risk
        lines.append(
            f"Risk: ATR {r['atr_14_pct']}% a day; a 2-ATR stop sits {r['stop_distance_2atr_pct']}% "
            f"away, so risking 1% of an account allows a position of at most "
            f"{r['max_position_pct_of_account_risking_1pct']}% of it"
        )

    lines += ["", "By strategy (net score, -1 to +1):"]
    lines += [f"  {strategy:<15} {score:+.2f}" for strategy, score in p.by_strategy.items()]
    if len(p.modes) > 1:
        lines += ["", f"Reasoning modes (stability {_pct(p.stability)} of samples match the call):"]
        lines += [f"  {mode:<15} {score:+.2f}" for mode, score in p.by_mode.items()]

    lines += ["", "Baselines: " + "  ".join(f"{k}={v}" for k, v in p.baselines.items())]
    if p.linear_regression:
        lines += _regression_lines(p.linear_regression)

    lines += ["", "Personas:"]
    labels = [r.persona_id if r.mode == "default" else f"{r.persona_id}@{r.mode}" for r in p.personas]
    width = max([22, *map(len, labels)])
    for r, label in zip(p.personas, labels):
        if r.view is None:
            lines.append(f"  {label:<{width}} FAILED  {r.error}")
        else:
            rationale = r.view.rationale if len(r.view.rationale) <= 90 else r.view.rationale[:87] + "..."
            lines.append(
                f"  {label:<{width}} {r.view.direction:<5} {r.view.conviction:.2f}  {rationale}"
            )
    if p.audit:
        lines += _audit_lines(p.audit)
    if p.data_warnings:
        lines += ["", "Data warnings:"] + [f"  {w}" for w in p.data_warnings]
    return "\n".join(lines)


def render_pending(r: Report, limit: int = 20) -> list[str]:
    """Why each unscored prediction is still waiting (holidays, missing bars, ...)."""
    if not r.pending_details:
        return []
    lines = ["", "Pending, and why:"]
    for p in r.pending_details[:limit]:
        lines.append(f"  {p.prediction.ticker:<6} {p.prediction.data_as_of} +{p.prediction.horizon_days}d  {p.detail}")
    if len(r.pending_details) > limit:
        lines.append(f"  ... and {len(r.pending_details) - limit} more")
    return lines


def render_report(r: Report) -> str:
    if not r.scored:
        return "\n".join(
            [f"No predictions have resolved yet ({r.pending} pending, {r.unreadable} unreadable)."]
            + render_pending(r)
        )
    lines = [
        f"Scored {r.scored} predictions ({r.pending} pending, {r.unreadable} unreadable). "
        "Small samples are noisy; treat fewer than ~50 as anecdotes.",
        "",
        "Accuracy, 3-way up / flat / down:",
        f"  {'personas':<18} {_pct(r.accuracy['personas'])}   (made a call {_pct(r.coverage)} "
        f"of the time, {_pct(r.accuracy_when_called)} right when it did)",
    ]
    lines += [f"  {name:<18} {_pct(acc)}" for name, acc in r.accuracy.items() if name != "personas"]
    if r.relative:
        rel = r.relative
        lines += ["", f"Relative to {rel['benchmark']} ({rel['scored']} scored; always-up can't ride the market here):"]
        lines += [f"  {name:<18} {_pct(acc)}" for name, acc in rel["accuracy"].items()]
    lines += ["", "Persona up/down calls by strength (is higher strength more often right?):"]
    lines += [f"  {bucket}  n={n:<4} {_pct(acc)}" for bucket, (n, acc) in r.by_confidence.items()]
    if any(n for n, _ in r.by_stability.values()):
        lines += ["By stability (share of persona-mode samples matching the call):"]
        lines += [f"  {bucket}  n={n:<4} {_pct(acc)}" for bucket, (n, acc) in r.by_stability.items()]
    lines += ["", "Individual persona votes, by strategy:"]
    lines += [f"  {s:<15} {_pct(acc)}" for s, acc in r.by_strategy.items()]
    lines += ["By age band:"]
    lines += [f"  {a:<15} {_pct(acc)}" for a, acc in r.by_age_band.items()]
    if len(r.by_mode) > 1:
        lines += ["By reasoning mode:"]
        lines += [f"  {m:<15} {_pct(acc)}" for m, acc in r.by_mode.items()]
    if len(r.by_model) > 1:
        lines += ["By model:"]
        lines += [f"  {m:<25} {_pct(acc)}" for m, acc in r.by_model.items()]
    if r.strategy_weights:
        lines += ["", "Suggested strategy weights (applied by --weights auto):"]
        lines += [f"  {s:<15} {w:.3f}" for s, w in r.strategy_weights.items()]
    lines += render_pending(r)
    return "\n".join(lines)


def render_backtest(ticker: str, result: RegressionResult) -> str:
    lines = [
        f"{ticker} linear-regression baseline, {result.horizon_days}-day horizon "
        f"(features as of {result.features_as_of}, first fit on {result.n_train} days)",
        *_regression_lines(vars(result)),
        "",
        "Coefficients (% return per 1 std move in the feature):",
    ]
    lines += [f"  {name:<24} {coef:+.4f}" for name, coef in result.coefficients.items()]
    return "\n".join(lines)


def run_backtests(args: argparse.Namespace) -> int:
    failures = 0
    for ticker in args.tickers:
        try:
            daily = clean_daily(fetch_daily(ticker))
            if daily.empty:
                raise ValueError(f"no price history for {ticker.upper()!r}")
            result = run_regression(daily, args.horizon, features=args.feature_list)
        except ValueError as exc:
            print(f"{ticker.upper()}: error: {exc}", file=sys.stderr)
            failures += 1
            continue
        print(render_backtest(ticker.upper(), result))
        print()
    return failures


def resolve_weights(
    args: argparse.Namespace, report: Report | None
) -> dict[str, float] | Literal["auto"] | None:
    """`args.weight_map`, or with --weights auto the weights `report` suggests
    ("auto" itself with --database, where the service reads saved evaluations)."""
    if args.weights != "auto":
        return args.weight_map
    if args.database and not args.no_log:
        return "auto"  # predict_and_store derives them from saved evaluations
    report = report or score_log(args.log_file)
    if not report.strategy_weights:
        print("--weights auto: no scored predictions yet, using equal weights", file=sys.stderr)
        return None
    shown = ", ".join(f"{s}={w:g}" for s, w in report.strategy_weights.items())
    print(f"--weights auto: {shown} (from {report.scored} scored predictions)", file=sys.stderr)
    return report.strategy_weights


async def _predict_all(
    args: argparse.Namespace,
    weights: dict[str, float] | Literal["auto"] | None,
    llm: JsonLLM | None = None,
) -> int:
    try:
        llm = llm or build_llm()
    except RuntimeError as exc:  # missing API key
        print(f"error: {exc}", file=sys.stderr)
        return len(args.tickers)
    try:
        feed = live_feed_from_env() if args.live else None
    except (RuntimeError, ValueError) as exc:  # unknown LIVE_FEED or missing FINNHUB_API_KEY
        print(f"error: {exc}", file=sys.stderr)
        return len(args.tickers)
    failures = 0
    for ticker in args.tickers:
        try:
            if args.database and not args.no_log:
                from database.service import predict_and_store

                prediction = await predict_and_store(
                    ticker,
                    horizon_days=args.horizon,
                    strategies=[Strategy(s) for s in args.strategy] if args.strategy else None,
                    age_bands=args.age,
                    llm=llm,
                    strategy_weights=weights,
                    modes=args.mode_list,
                    live=args.live,
                    audit=args.audit,
                )
            else:
                snapshot = await asyncio.to_thread(fetch_snapshot, ticker)
                prediction = await predict(
                    ticker,
                    horizon_days=args.horizon,
                    strategies=[Strategy(s) for s in args.strategy] if args.strategy else None,
                    age_bands=args.age,
                    strategy_weights=weights,
                    modes=args.mode_list,
                    llm=llm,
                    snapshot=snapshot,
                    live_feed=feed,
                )
                if args.audit:
                    prediction.audit = await audit_prediction(prediction, snapshot, llm)
        except (RuntimeError, ValueError) as exc:  # bad ticker, all personas failed
            print(f"{ticker.upper()}: error: {exc}", file=sys.stderr)
            failures += 1
            continue
        if not args.no_log:
            if not args.database:
                log_prediction(prediction, args.log_file)
        print(prediction.model_dump_json(indent=2) if args.json else render(prediction))
        print()
    return failures


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    load_dotenv(ENV_FILE)
    from database.connection import DatabaseError

    failures = 0
    try:
        if args.database:
            from database.connection import connect

            # Fail before spending Gemini calls if persistence isn't configured.
            with connect() as connection:
                connection.execute("SELECT id FROM prediction_runs LIMIT 0")
        report = None
        if args.score:
            if args.database:
                from database.service import score_database

                report = score_database()
            else:
                report = score_log(args.log_file)
            print(render_report(report))
        if args.tickers and args.backtest:
            failures += run_backtests(args)
        elif args.tickers:
            failures += asyncio.run(_predict_all(args, resolve_weights(args, report)))
    except DatabaseError as exc:
        print(str(exc), file=sys.stderr)
        failures += 1
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
