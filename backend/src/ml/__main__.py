"""Train and evaluate the ml models (`ml/spec.md`). From `backend/src/`:

    python -m ml price                          # model A, 25 tickers, 1- and 5-day, gate verdict
    python -m ml price SPY AAPL --horizon 20 --horizon 60   # lever 7: longer horizons
    python -m ml price --target relative        # lever 4: return relative to SPY
    python -m ml price --models logistic --save # also fit on every row and store it
    python -m ml stacker [--save]               # model B; needs 300 scored predictions
    python -m ml stacker --target relative      # model B on the outcome relative to SPY
    python -m ml coverage                       # levers 1, 2, 5 and 6 on scored persona calls
    python -m ml coverage --save                # also fit data/call_policy.json (main.py --policy)
    python -m ml bias                           # persona calls and votes vs what happened
    python -m ml stacker --database             # the same, on forecasts saved in PostgreSQL
    python -m ml replay --dry-run               # plan a backdated run: forecasts and Gemini calls
    python -m ml replay                         # run it, then print an estimated accuracy (spends quota)
    python -m ml replay --report-only           # score a finished replay file again

An explicit command, never run at request time. `price` downloads daily bars
from Yahoo; `stacker`, `coverage` and `bias` score the prediction log (Yahoo
closes). They make no LLM calls; `replay` makes one per persona per forecast.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from ai.agents import PROMPT_VERSION
from ai.evaluation import DEFAULT_LOG, MARKET_TZ, score_log
from ai.personas import build_personas
from ai.policy import save_policy
from ai.tool import clean_daily, fetch_daily
from finance.linear_regression import FEATURE_FUNCTIONS, FEATURES
from ml.calibration import (
    ACTUALS,
    BiasReport,
    CalibrationScore,
    CoverageRow,
    bias_report,
    coverage_report,
    evaluate_calibration,
    fit_call_policy,
    persona_rank_spread,
)
from ml.dataset import pooled_price_rows, stacker_rows
from ml.model import MODELS, LogisticModel, get_device, make_model
from ml.store import save
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
REPLAY_DIR = Path(__file__).resolve().parents[2] / "data"

# The 25-ticker set of the regression feature experiment (finance/spec.md).
DEFAULT_TICKERS = (
    "SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "XOM",
    "JNJ", "PG", "KO", "WMT", "UNH", "HD", "CAT", "BA", "DIS", "NFLX", "AMD", "INTC", "PFE",
)
BENCHMARK = "SPY"
GATE_HORIZONS = (1, 5)
# Twelve single stocks across sectors for `replay`: ETFs have no fundamentals to blind.
REPLAY_TICKERS = (
    "AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "JNJ", "PG", "KO", "CAT", "NFLX", "AMD",
)
REPLAY_DATES = 12
REPLAY_STEP = 5  # sessions between forecast dates: no overlap at the 5-day horizon


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
    coverage.add_argument("--save", action="store_true",
                          help="fit the call policy (abstain threshold, calibration) and write "
                          "data/call_policy.json for main.py --policy")

    bias = commands.add_parser("bias", help="persona calls and votes against what happened")
    bias.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    bias.add_argument("--database", action="store_true",
                      help="score forecasts saved in PostgreSQL instead of the log")

    replay = commands.add_parser(
        "replay", help="backdated forecasts through the real pipeline, scored on what followed")
    replay.add_argument("tickers", nargs="*", help=f"default: {', '.join(REPLAY_TICKERS)}")
    replay.add_argument("--dates", type=int, default=REPLAY_DATES, help="forecast dates (default %(default)s)")
    replay.add_argument("--step", type=int, default=REPLAY_STEP, help="sessions between dates (default %(default)s)")
    replay.add_argument("--horizon", type=int, action="append", help="trading days; repeatable (default 1 and 5)")
    replay.add_argument("--after", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="skip dates before this: the LLM's training cutoff, if you know it")
    replay.add_argument("--age", action="append", help="run only these age bands (repeatable; faster)")
    replay.add_argument("--out", type=Path, help="JSONL file (default data/replay-v<prompt version>.jsonl)")
    replay.add_argument("--concurrency", type=int, default=2, help="forecasts at once (default %(default)s)")
    replay.add_argument("--max-failures", type=int, default=5,
                        help="stop after this many forecasts in a row fail, e.g. a spent quota")
    replay.add_argument("--dry-run", action="store_true", help="print the plan and the Gemini calls it needs")
    replay.add_argument("--report-only", action="store_true", help="score --out without forecasting")
    replay.add_argument("--against", type=Path, metavar="FILE",
                        help="another replay file (say, an earlier prompt version): also compare the "
                        "two on the rows they share")

    args = parser.parse_args(argv)
    if args.command == "replay":
        args.horizons = tuple(dict.fromkeys(args.horizon or GATE_HORIZONS))
        if min(args.horizons) < 1 or args.dates < 1 or args.step < 1:
            parser.error("--horizon, --dates and --step must each be at least 1")
        args.tickers = [t.upper() for t in args.tickers] or list(REPLAY_TICKERS)
        args.out = args.out or REPLAY_DIR / f"replay-v{PROMPT_VERSION}.jsonl"
    if args.command == "price":
        args.horizons = tuple(dict.fromkeys(args.horizon or GATE_HORIZONS))
        if min(args.horizons) < 1:
            parser.error("--horizon must be at least 1")
        args.tickers = [t.upper() for t in args.tickers] or list(DEFAULT_TICKERS)
    return args


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _num(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


# --- price (model A) -------------------------------------------------------------


def fetch_dailies(tickers: Sequence[str]) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    dailies, errors = {}, {}
    for ticker in dict.fromkeys(tickers):
        try:
            daily = clean_daily(fetch_daily(ticker))
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
    dailies, errors = fetch_dailies([*args.tickers, *([BENCHMARK] if relative else [])])
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
    if args.save:
        policy = fit_call_policy(report.outcomes)
        policy["source"] = "database" if args.database else str(args.log_file)
        print(render_policy(policy))
        print(f"saved {save_policy(policy)}")
    return 0


def render_policy(policy: dict) -> str:
    lines = ["", f"Call policy, fitted on {policy['scored']} scored calls:"]
    for horizon, rule in policy["abstain"].items():
        if rule["enabled"]:
            lines.append(
                f"  {horizon}-day: abstain below strength {rule['min_strength']:.2f}; held out, the kept "
                f"calls were right {_pct(rule['held_out_accuracy'])} vs always-up "
                f"{_pct(rule['held_out_always_up'])} (n={rule['held_out_kept']})"
            )
        else:
            lines.append(f"  {horizon}-day: no abstain threshold, {rule['reason']}")
    calibration = policy["calibration"]
    lines.append(
        f"  calibration: {calibration['method']} curve" if calibration["enabled"]
        else f"  calibration: off, {calibration['reason']}"
    )
    return "\n".join(lines)


# --- bias ------------------------------------------------------------------------


def render_bias(r: BiasReport) -> str:
    lines = [
        f"Persona calls, {r.horizon_days}-day horizon: {r.n} scored",
        f"  {'called / actual':<16}" + "".join(f"{a:>7}" for a in ACTUALS) + f"{'total':>7}{'right':>8}",
    ]
    for call, row in r.confusion.items():
        total = sum(row.values())
        right = _pct(row[call] / total) if total and call in row else "-"  # unclear is never right
        lines.append(f"  {call:<16}" + "".join(f"{row[a]:>7}" for a in ACTUALS) + f"{total:>7}{right:>8}")
    lines += [
        f"  {'actual share':<16}" + "".join(f"{_pct(r.actual_share[a]):>7}" for a in ACTUALS),
        f"  {'call share':<16}" + "".join(f"{_pct(r.call_share[a]):>7}" for a in ACTUALS)
        + f"  (unclear {_pct(r.call_share['unclear'])})",
        "",
        "  Persona votes by strategy, share of votes (hit rate when voting it):",
    ]
    for strategy, v in r.by_strategy.items():
        parts = "  ".join(f"{d} {_pct(v.share[d])} ({_pct(v.hit_rate[d])})" for d in ACTUALS)
        lines.append(f"    {strategy:<14} n={v.votes:<5} {parts}")
    lines.append(
        f"  Votes whose rationale cites missing data: {_pct(r.missing_data_share)}, "
        f"right {_pct(r.missing_data_hit_rate)} vs {_pct(r.other_hit_rate)} for the rest"
    )
    return "\n".join(lines)


def run_bias(args: argparse.Namespace) -> int:
    report = scored_predictions(args)
    if not report.outcomes:
        print(f"No predictions have resolved yet ({report.pending} pending).")
        return 0
    print("\n\n".join(render_bias(r) for r in bias_report(report.outcomes)))
    return 0


# --- replay ----------------------------------------------------------------------


def _ci(e) -> str:
    return f"{e.mean:6.1%}  [{e.low:.1%}, {e.high:.1%}]"


def _edge(e) -> str:
    return f"{e.mean * 100:+5.1f} pts  [{e.low * 100:+.1f}, {e.high * 100:+.1f}]"


def render_comparison(c) -> str:
    from ml.replay import verdict

    label = "outcome vs SPY" if c.target == "relative" else "outcome"
    lines = [
        f"{c.horizon_days}-day horizon, {label}: {c.n} forecasts on {c.dates} dates, {c.tickers} tickers",
        f"  {'call':<24}{'3-way accuracy':>28}   (95% interval, whole dates resampled)",
        f"  {'personas':<24}{_ci(c.personas):>28}",
        f"  {'always up':<24}{_ci(c.always_up):>28}",
        f"  {'momentum':<24}{_ci(c.momentum):>28}",
    ]
    if c.regression is not None:
        lines.append(f"  {'linear regression':<24}{_ci(c.regression):>28}")
    lines.append(f"  {'personas - always up':<24}{_edge(c.edge_vs_always_up):>28}   "
                 f"{verdict(c.edge_vs_always_up)}")
    if c.edge_vs_regression is not None:
        lines.append(f"  {'personas - regression':<24}{_edge(c.edge_vs_regression):>28}   "
                     f"{verdict(c.edge_vs_regression)}")
    when_called = "n/a" if c.accuracy_when_called is None else f"{c.accuracy_when_called:.1%}"
    lines.append(f"  called {c.called_share:.0%} of the time, right {when_called} of those calls")
    return "\n".join(lines)


def render_run_comparison(runs, this: str, other: str) -> str:
    lines = [f"This run ({this}) against {other}, on the rows both scored:"]
    for r in runs:
        lines += [
            f"{r.horizon_days}-day horizon: {r.n} forecasts on {r.dates} dates",
            f"  {'this run':<20}{_ci(r.this_run):>28}",
            f"  {'other run':<20}{_ci(r.other_run):>28}",
            f"  {'always up':<20}{_ci(r.always_up):>28}",
            f"  {'this - other':<20}{_edge(r.change):>28}   "
            + ("better" if r.change.low > 0 else "worse" if r.change.high < 0
               else "can't be told apart"),
        ]
    return "\n".join(lines) if runs else lines[0] + "\n  no rows in common"


def render_replay_report(report, model: str | None = None) -> str:
    from ml.replay import compare

    outcomes = report.outcomes
    days = sorted({o.prediction.data_as_of for o in outcomes})
    header = (f"Replay: {report.scored} forecasts scored ({report.pending} pending), "
              f"{days[0]} to {days[-1]}, prompt version "
              f"{', '.join(sorted({o.prediction.prompt_version for o in outcomes}))}"
              + (f", model {model}" if model else ""))
    lines = [
        header,
        "Prices only (fundamentals, analysts, options, news and earnings dates withheld), so this is",
        "a floor for the live app and not live accuracy. Always-up is the bar.",
        "",
    ]
    lines += [render_comparison(c) + "\n" for c in compare(outcomes)]
    return "\n".join(lines).rstrip()


def run_replay_command(args: argparse.Namespace) -> int:
    from dotenv import load_dotenv

    from ml.replay import (
        default_horizon_note,
        fetch_price_book,
        plan,
        replay_sessions,
        run_replay,
    )

    load_dotenv(ENV_FILE)
    personas = len(build_personas(age_bands=args.age))
    dates = replay_sessions(datetime.now(MARKET_TZ), max(args.horizons), args.dates, args.step, args.after)
    if not dates and not args.report_only:
        print("error: no forecast dates left after --after", file=sys.stderr)
        return 1
    tasks = plan(args.tickers, dates, args.horizons)
    if not args.report_only:
        calls = len(tasks) * personas
        print(f"Replay plan: {len(args.tickers)} tickers x {len(dates)} dates ({dates[0]} to {dates[-1]}, "
              f"every {args.step} sessions) x horizons {list(args.horizons)} = {len(tasks)} forecasts, "
              f"{personas} personas each = {calls} Gemini calls, prompt version {PROMPT_VERSION}")
        print(f"  output: {args.out}")
        if note := default_horizon_note(args.step, args.horizons):
            print(f"  note: {note}")
        if args.dry_run:
            return 0
        from ai.llm import build_llm
        from ml.replay import done_keys

        try:
            llm = build_llm()
        except RuntimeError as exc:  # no API key
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"  model: {llm.model}. The replay is clean only for dates after its training cutoff"
              + ("" if args.after else "; pass --after DATE if you know it"))
        book, problems = fetch_price_book(args.tickers)
        for symbol, why in problems.items():
            print(f"  {symbol}: skipped: {why}", file=sys.stderr)
        tickers = [t for t in args.tickers if t in book.frames]
        tasks = plan(tickers, dates, args.horizons)
        print(f"  {len(done_keys(args.out))} forecasts already in the file are skipped")

        async def go():
            try:
                return await run_replay(
                    tasks, book, llm, args.out, age_bands=args.age, concurrency=args.concurrency,
                    max_failures=args.max_failures, progress=lambda line: print("  " + line, flush=True),
                )
            finally:
                await llm.aclose()

        run = asyncio.run(go())
        print(f"\nForecast {run.done}, skipped {run.skipped} already done, "
              f"{len(run.unavailable)} without usable history, {len(run.failed)} failed")
        for task, why in run.failed[:5]:
            print(f"  failed {task.ticker} {task.as_of} {task.horizon}d: {why}", file=sys.stderr)
        if run.aborted:
            print(f"STOPPED: {run.aborted}. Re-run to resume from the file.", file=sys.stderr)
            if not run.done and not args.out.exists():
                return 1

    if not args.out.exists():
        print(f"No replay file at {args.out}.")
        return 1
    report = score_log(args.out)
    if not report.outcomes:
        print(f"No replayed forecasts have resolved yet ({report.pending} pending).")
        return 0
    model = next(iter({o.prediction.model for o in report.outcomes}), None)
    print("\n" + render_replay_report(report, model))
    if args.against:
        from ml.replay import compare_runs

        if not args.against.exists():
            print(f"\nNo file at {args.against} to compare against.", file=sys.stderr)
            return 1
        other = score_log(args.against)
        print("\n" + render_run_comparison(
            compare_runs(report.outcomes, other.outcomes), args.out.name, args.against.name))
    print("\nWhere the personas went wrong:\n")
    print("\n\n".join(render_bias(r) for r in bias_report(report.outcomes)))
    print(render_policy(fit_call_policy(report.outcomes)).replace(
        "Call policy, fitted on", "Call policy that these rows would give (not saved), fitted on"))
    return 0


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    run = {"price": run_price, "stacker": run_stacker, "coverage": run_coverage, "bias": run_bias,
           "replay": run_replay_command}[args.command]
    if run(args):
        sys.exit(1)


if __name__ == "__main__":
    main()
