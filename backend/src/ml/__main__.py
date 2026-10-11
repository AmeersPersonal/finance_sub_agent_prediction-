"""Train and evaluate the ml models (`ml/spec.md`). From `backend/src/`:

    python -m ml price                          # model A, 25 tickers, 1- and 5-day, gate verdict
    python -m ml price SPY AAPL --horizon 20 --horizon 60   # lever 7: longer horizons
    python -m ml price --target relative        # lever 4: return relative to SPY
    python -m ml price --models logistic --save # also fit on every row and store it
    python -m ml stacker [--save]               # model B; needs 300 scored predictions
    python -m ml stacker --target relative      # model B on the outcome relative to SPY
    python -m ml coverage                       # levers 1, 2, 5 and 6 on scored persona calls
    python -m ml stacker --database             # the same, on forecasts saved in PostgreSQL

An explicit command, never run at request time. `price` downloads daily bars
from Yahoo; `stacker` and `coverage` score the prediction log (Yahoo closes).
No LLM calls.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from ai.evaluation import DEFAULT_LOG, score_log
from ai.personas import AGE_BANDS
from ai.tool import clean_daily, fetch_daily
from finance.linear_regression import FEATURE_FUNCTIONS, FEATURES
from ml.calibration import (
    CalibrationScore,
    CoverageRow,
    coverage_report,
    evaluate_calibration,
    persona_rank_spread,
)
from ml.dataset import pooled_price_rows, stacker_rows
from ml.model import MODELS, LogisticModel, get_device, make_model
from ml.replay import (
    DEFAULT_REPLAY_FILE,
    REPLAY_AGE_BAND,
    RunSummary,
    render_result,
    run_collect,
    run_replay,
    train,
)
from ml.store import save
from ml.universe import DEFAULT_TICKERS, UNIVERSES
from ml.walkforward import (
    GATE_MARGIN,
    MIN_SCORED_FOR_STACKER,
    ModelScore,
    PriceReport,
    StackerReport,
    evaluate_price_models,
    evaluate_stacker,
)

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

BENCHMARK = "SPY"
GATE_HORIZONS = (1, 5)
REPLAY_HORIZONS = (1, 5)


def _names(spec: str, known: Sequence[str], what: str) -> tuple[str, ...]:
    names = tuple(n.strip() for n in spec.split(",") if n.strip())
    unknown = [n for n in names if n not in known]
    if unknown or not names:
        raise argparse.ArgumentTypeError(f"unknown {what} {unknown}; choose from {', '.join(known)}")
    return names


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m ml", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    models_help = f"comma-separated, simplest first: {', '.join(MODELS)}"

    price = commands.add_parser("price", help="model A: pooled price-feature classifier")
    price.add_argument("tickers", nargs="*", help=f"default: {len(DEFAULT_TICKERS)} large caps and ETFs")
    price.add_argument("--horizon", type=int, action="append", help="trading days; repeatable (default 1 and 5)")
    price.add_argument("--target", choices=("absolute", "relative"), default="absolute",
                       help=f"relative: return vs {BENCHMARK}, its own flat band (lever 4)")
    price.add_argument("--models", type=lambda s: _names(s, list(MODELS), "models"), default=tuple(MODELS),
                       help=models_help)
    price.add_argument("--features", type=lambda s: _names(s, list(FEATURE_FUNCTIONS), "features"),
                       default=FEATURES, help=f"comma-separated; known: {', '.join(FEATURE_FUNCTIONS)}")
    price.add_argument("--universe", choices=tuple(UNIVERSES), default="default",
                       help="ticker list when none are given: default (25) or large (~100)")
    price.add_argument("--years", type=int, default=5,
                       help="years of daily history per ticker (default 5; 10+ adds market regimes)")
    price.add_argument("--test-fraction", type=float, default=0.2)
    price.add_argument("--refit-every", type=int, default=21, help="test dates per refit")
    price.add_argument("--cost-bps", type=float, default=5.0)
    price.add_argument("--save", action="store_true", help="fit each model on every row and store it")

    stacker = commands.add_parser("stacker", help="model B: learn how much to trust each persona")
    stacker.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    stacker.add_argument("--database", action="store_true",
                         help="score forecasts saved in PostgreSQL (API, main.py --database) instead of the log")
    stacker.add_argument("--models", type=lambda s: _names(s, list(MODELS), "models"), default=("logistic",),
                         help=models_help + " (default logistic)")
    stacker.add_argument("--test-fraction", type=float, default=0.3)
    stacker.add_argument("--refit-every", type=int, default=5, help="prediction dates per refit")
    stacker.add_argument("--min-scored", type=int, default=MIN_SCORED_FOR_STACKER,
                         help="refuse to evaluate below this many scored predictions")
    stacker.add_argument("--include-packet", action="store_true",
                         help="also learn from Prediction.features (hundreds of columns)")
    stacker.add_argument("--target", choices=("absolute", "relative"), default="absolute",
                         help=f"relative: the outcome vs {BENCHMARK}, from the scorer's relative outcome")
    stacker.add_argument("--save", action="store_true")

    coverage = commands.add_parser("coverage", help="accuracy at coverage and strength calibration")
    coverage.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    coverage.add_argument("--database", action="store_true",
                          help="score forecasts saved in PostgreSQL instead of the log")

    replay = commands.add_parser(
        "replay", help="forecast the last N sessions, score them, train model B and adjust weights"
    )
    _forecast_args(replay)
    replay.add_argument("--sessions", type=int, default=10, help="as-of sessions per horizon (default 10)")
    replay.add_argument("--file", type=Path, default=DEFAULT_REPLAY_FILE,
                        help="replay forecasts; resumable, never the live log")
    replay.add_argument("--score-only", action="store_true",
                        help="skip the LLM: score and train on forecasts already in --file")
    replay.add_argument("--models", type=lambda s: _names(s, list(MODELS), "models"),
                        default=("logistic", "mlp"), help=models_help + " (default logistic,mlp)")
    replay.add_argument("--target", choices=("absolute", "relative"), default="absolute")
    replay.add_argument("--test-fraction", type=float, default=0.3)
    replay.add_argument("--refit-every", type=int, default=3, help="prediction dates per refit")
    replay.add_argument("--min-scored", type=int, default=60)
    replay.add_argument("--no-save", action="store_true", help="don't store the fitted models")

    collect = commands.add_parser("collect", help="today's live forecasts, appended to the prediction log")
    _forecast_args(collect)
    collect.add_argument("--log-file", type=Path, default=DEFAULT_LOG)

    args = parser.parse_args(argv)
    if args.command == "price":
        args.horizons = tuple(dict.fromkeys(args.horizon or GATE_HORIZONS))
        if min(args.horizons) < 1:
            parser.error("--horizon must be at least 1")
        if args.years < 1:
            parser.error("--years must be at least 1")
        args.tickers = [t.upper() for t in args.tickers] or list(UNIVERSES[args.universe])
    elif args.command in ("replay", "collect"):
        args.horizons = tuple(dict.fromkeys(args.horizon or REPLAY_HORIZONS))
        if min(args.horizons) < 1:
            parser.error("--horizon must be at least 1")
        args.tickers = [t.upper() for t in args.tickers] or list(UNIVERSES[args.universe])
        args.age = args.age or [REPLAY_AGE_BAND]
    return args


def _forecast_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("tickers", nargs="*", help="default: the --universe list")
    parser.add_argument("--universe", choices=tuple(UNIVERSES), default="default")
    parser.add_argument("--horizon", type=int, action="append", help="trading days; repeatable (default 1 and 5)")
    parser.add_argument("--age", action="append", choices=[b.label for b in AGE_BANDS],
                        help=f"age band; repeatable (default {REPLAY_AGE_BAND}: one persona per strategy)")
    parser.add_argument("--concurrency", type=int, default=4, help="forecasts in flight at once")


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _num(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


# --- price (model A) -------------------------------------------------------------


def fetch_dailies(
    tickers: Sequence[str], years: int = 5
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    dailies, errors = {}, {}
    for ticker in dict.fromkeys(tickers):
        try:
            daily = clean_daily(fetch_daily(ticker, years))
        except Exception as exc:  # yfinance raises many types; one ticker mustn't stop the run
            errors[ticker] = f"{type(exc).__name__}: {exc}"
            continue
        if daily.empty:
            errors[ticker] = "no price history"
        else:
            dailies[ticker] = daily
    return dailies, errors


def _reliability_line(m: ModelScore) -> str:
    parts = [
        f"{b.label} {_pct(b.hit_rate)} vs {_pct(b.mean_probability)} (n={b.n})"
        for b in m.reliability if b.n
    ]
    return f"  {m.name:<10} " + "; ".join(parts)


def render_price(r: PriceReport) -> str:
    baselines = "  ".join(f"{k} {_pct(v)}" for k, v in r.baselines.items())
    hold = r.buy_and_hold
    lines = [
        f"Model A, {r.horizon_days}-day horizon, {r.target} target: {len(r.tickers)} tickers, "
        f"{r.n_test:,} test rows from {r.test_start} (refit every {r.refit_every} dates)",
        f"Baselines, 3-way accuracy on the same rows: {baselines}",
        f"Buy & hold, equal weight: return {hold['total_return_pct']:+.1f}%  "
        f"Sharpe {_num(hold['sharpe'])}",
        "",
        f"  {'model':<10} {'accuracy':>8} {'vs up':>8} {'beats up':>9} {'log-loss':>9} "
        f"{'Brier':>6} {'return':>8} {'Sharpe':>7}  rank spread (top - bottom 20%)",
        f"  {'prior':<10} {'':>8} {'':>8} {'':>9} {r.prior_log_loss:>9.4f}",
    ]
    for m in r.models:
        edge = (m.accuracy - r.baselines["always_up"]) * 100
        spread = m.rank_spread
        spread_text = (
            f"{spread['mean_spread_pct']:+.2f}% a period, positive {spread['positive_share']:.0%}"
            if spread else "n/a (under 5 tickers)"
        )
        lines.append(
            f"  {m.name:<10} {_pct(m.accuracy):>8} {edge:>+6.1f}pp {_pct(m.beats_always_up_share):>9} "
            f"{m.log_loss:>9.4f} {m.brier:>6.3f} {m.trading['total_return_pct']:>+7.1f}% "
            f"{_num(m.trading['sharpe']):>7}  {spread_text}"
        )
    lines += ["", "Reliability, predicted-class probability bin: hit rate vs mean probability:"]
    lines += [_reliability_line(m) for m in r.models]
    return "\n".join(lines)


def _price_meta(data, report: PriceReport, score: ModelScore) -> dict:
    return {
        "kind": "model_a",
        "horizon_days": report.horizon_days,
        "target": report.target,
        "features": list(data.feature_names),
        "tickers": report.tickers,
        "rows": len(data),
        "data_through": str(data.dates.max()),
        "walk_forward": {
            "accuracy": score.accuracy,
            "always_up": report.baselines["always_up"],
            "log_loss": score.log_loss,
            "passes_gate": score.passes_gate,
        },
    }


def run_price(args: argparse.Namespace) -> int:
    relative = args.target == "relative"
    dailies, errors = fetch_dailies([*args.tickers, *([BENCHMARK] if relative else [])], args.years)
    for ticker, why in errors.items():
        print(f"{ticker}: skipped: {why}", file=sys.stderr)
    benchmark = dailies.get(BENCHMARK) if relative else None
    if relative and benchmark is None:
        print(f"error: --target relative needs {BENCHMARK} prices", file=sys.stderr)
        return 1
    # The benchmark relative to itself is a constant: no information, every row "flat".
    pool = {t: d for t, d in dailies.items() if t in args.tickers and not (relative and t == BENCHMARK)}
    if not pool:
        print("error: no ticker has price history", file=sys.stderr)
        return 1
    print(f"MLP device: {get_device()}\n")

    passed: dict[str, list[bool]] = defaultdict(list)
    for horizon in args.horizons:
        data = pooled_price_rows(pool, horizon, args.features, benchmark)
        report = evaluate_price_models(
            data, args.models, args.test_fraction, args.refit_every, args.cost_bps
        )
        print(render_price(report), "\n")
        for score in report.models:
            if horizon in GATE_HORIZONS:
                passed[score.name].append(score.passes_gate)
            if args.save:
                model = make_model(score.name).fit(data.X, data.y)
                path = save(model, f"price-{score.name}-{horizon}d-{args.target}",
                            _price_meta(data, report, score))
                print(f"saved {path}")

    print(
        f"Gate (ml/spec.md): beat always-up by more than {GATE_MARGIN * 100:g} points and on "
        f"more than half the tickers, at both the 1- and 5-day horizons."
    )
    if not set(GATE_HORIZONS) <= set(args.horizons):
        print("  not judged: run --horizon 1 and --horizon 5 (the default) to judge it")
        return 0
    for name, results in passed.items():
        print(f"  {name:<10} {'PASS' if all(results) else 'FAIL'}")
    return 0


# --- stacker (model B) -----------------------------------------------------------


def render_stacker(r: StackerReport, target: str = "absolute") -> str:
    name = "Model B (persona stacker)" + (f", relative to {BENCHMARK}" if target == "relative" else "")
    if r.blocked:
        return f"{name}: blocked, {r.blocked}. Keep logging live predictions."
    baselines = "  ".join(f"{k} {_pct(v)}" for k, v in r.baselines.items())
    lines = [
        f"{name}: {r.scored} scored predictions, {r.n_test} held out from {r.test_start}",
        f"Baselines, 3-way accuracy on the held-out rows: {baselines}",
        "",
        f"  {'model':<13} {'accuracy':>8} {'log-loss':>9} {'Brier':>6}",
        f"  {'prior':<13} {'':>8} {r.prior_log_loss:>9.4f}",
    ]
    for m in [r.weights_auto, *r.models]:
        verdict = "" if m is r.weights_auto else ("  PASS" if m.passes_gate else "  FAIL")
        lines.append(f"  {m.name:<13} {_pct(m.accuracy):>8} {m.log_loss:>9.4f} {m.brier:>6.3f}{verdict}")
    lines += ["", "Gate (ml/spec.md): better log-loss and accuracy than --weights auto on held-out dates."]
    return "\n".join(lines)


def render_coefficients(model: LogisticModel, columns: Sequence[str], top: int = 12) -> str:
    """Lever 3: what the stacker leans on, and persona columns it nearly ignores."""
    coefs = model.coefficients(columns)
    if not coefs:
        return ""
    weight = {f: max(abs(v) for v in by_class.values()) for f, by_class in coefs.items()}
    ranked = sorted(weight, key=weight.get, reverse=True)
    lines = ["", "Logistic stacker, largest weights (per std of the column; up / flat / down):"]
    for f in ranked[:top]:
        c = coefs[f]
        lines.append(
            f"  {f:<40} {c.get('up', 0):+.3f} / {c.get('flat', 0):+.3f} / {c.get('down', 0):+.3f}"
        )
    idle = [f for f in ranked if f.startswith("persona.") and weight[f] < 0.05]
    if idle:
        lines.append("Persona columns adding little (max |weight| < 0.05): " + ", ".join(idle))
    return "\n".join(lines)


def scored_predictions(args: argparse.Namespace):
    """The scorer's report on the JSONL log, or on the database with --database.

    The API saves forecasts only to PostgreSQL, so Phase 1 data collected through
    it is visible here only with --database.
    """
    if not args.database:
        return score_log(args.log_file)
    from dotenv import load_dotenv

    from database.service import score_database

    load_dotenv(ENV_FILE)
    return score_database()


def run_stacker(args: argparse.Namespace) -> int:
    scored = scored_predictions(args)
    data = stacker_rows(scored.outcomes, include_packet=args.include_packet, target=args.target)
    report = evaluate_stacker(
        data, args.models, args.test_fraction, args.refit_every, min_scored=args.min_scored
    )
    print(render_stacker(report, args.target))
    if report.blocked:
        return 0
    for name in args.models:
        model = make_model(name).fit(data.X, data.y)
        if isinstance(model, LogisticModel):
            print(render_coefficients(model, data.feature_names))
        if args.save:
            score = next(m for m in report.models if m.name == name)
            meta = {
                "kind": "model_b",
                "target": args.target,
                "columns": list(data.feature_names),
                "rows": len(data),
                "data_through": str(data.dates.max()),
                "walk_forward": {"accuracy": score.accuracy, "log_loss": score.log_loss,
                                 "passes_gate": score.passes_gate},
            }
            suffix = "-relative" if args.target == "relative" else ""
            print(f"saved {save(model, f'stacker-{name}{suffix}', meta)}")
    return 0


# --- coverage (levers 1, 2, 5) ---------------------------------------------------


def render_rank_spread(spread: dict | None) -> list[str]:
    if spread is None:
        return ["", "Persona ranking (lever 6): no day had 5 or more tickers predicted yet."]
    return [
        "",
        f"Persona ranking (lever 6), long the top fifth by net score and short the bottom: "
        f"{spread['mean_spread_pct']:+.2f}% a period over {spread['periods']} days "
        f"(~{spread['mean_tickers']:.0f} tickers each), positive {spread['positive_share']:.0%}. "
        "Periods overlap for horizons over a day.",
    ]


def render_coverage(tables: dict[str, list[CoverageRow]], calibration: CalibrationScore | None,
                    spread: dict | None = None) -> str:
    lines = ["Persona calls at coverage: 3-way accuracy, always-up on the same rows:"]
    for title, rows in tables.items():
        lines.append(f"  {title}")
        if not rows or not rows[0].n:
            lines.append("    no calls")
            continue
        for row in rows:
            threshold = "" if row.min_strength is None else f"strength >= {row.min_strength:.2f}"
            lines.append(
                f"    {row.label:<9} n={row.n:<5} {threshold:<17} {_pct(row.accuracy):>6}  "
                f"(always-up {_pct(row.always_up)})"
            )
    lines += render_rank_spread(spread)
    if calibration is None:
        lines += ["", "Strength calibration: too few resolved calls to fit before a held-out block."]
        return "\n".join(lines)
    brier = "  ".join(f"{m} {v:.4f}" for m, v in calibration.brier.items())
    lines += [
        "",
        f"Strength -> P(call right), walk-forward Brier on {calibration.n_test} held-out calls "
        f"(lower is better; constant = training hit rate): {brier}",
    ]
    for method, curve in calibration.curve.items():
        points = "  ".join(f"{s:.2f}->{p:.0%}" for s, p in curve)
        lines.append(f"  {method:<9} fit on every call: {points}")
    return "\n".join(lines)


def run_coverage(args: argparse.Namespace) -> int:
    report = scored_predictions(args)
    if not report.outcomes:
        print(f"No predictions have resolved yet ({report.pending} pending).")
        return 0
    print(render_coverage(coverage_report(report.outcomes), evaluate_calibration(report.outcomes),
                          persona_rank_spread(report.outcomes)))
    return 0


# --- replay and collect ----------------------------------------------------------


def _print_summary(summary: RunSummary, what: str) -> None:
    print(f"{what}: {summary.saved} forecasts saved, {summary.skipped_done} already done, "
          f"{len(summary.failed)} failed of {summary.requested} requested")
    for name, why in list(summary.failed.items())[:10]:
        print(f"  {name}: {why}", file=sys.stderr)
    if len(summary.failed) > 10:
        print(f"  ... and {len(summary.failed) - 10} more", file=sys.stderr)


def run_replay_command(args: argparse.Namespace) -> int:
    from dotenv import load_dotenv

    load_dotenv(ENV_FILE)
    if not args.score_only:
        try:
            summary = asyncio.run(run_replay(
                args.tickers, args.horizons, args.sessions, args.age, args.file, args.concurrency
            ))
        except RuntimeError as exc:  # missing API key
            print(f"error: {exc}", file=sys.stderr)
            return 1
        _print_summary(summary, "Replay")
    if not args.file.exists():
        print(f"error: no replay file at {args.file}", file=sys.stderr)
        return 1
    report = score_log(args.file)
    if not report.outcomes:
        print(f"Nothing has resolved yet ({report.pending} pending).")
        return 0
    result = train(report, args.models, args.target, args.test_fraction, args.refit_every,
                   save_models=not args.no_save, min_scored=args.min_scored)
    print()
    print(render_result(result))
    return 0


def run_collect_command(args: argparse.Namespace) -> int:
    from dotenv import load_dotenv

    load_dotenv(ENV_FILE)
    try:
        summary = asyncio.run(run_collect(
            args.tickers, args.horizons, args.age, args.log_file, args.concurrency
        ))
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_summary(summary, "Collect")
    return 1 if summary.failed and not summary.saved else 0


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    run = {
        "price": run_price, "stacker": run_stacker, "coverage": run_coverage,
        "replay": run_replay_command, "collect": run_collect_command,
    }[args.command]
    if run(args):
        sys.exit(1)


if __name__ == "__main__":
    main()
