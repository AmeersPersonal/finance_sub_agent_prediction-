"""Command-line entry point.

    python main.py AAPL                       # predict and log
    python main.py AAPL MSFT NVDA --horizon 1
    python main.py AAPL --strategy day_trader --age 18-24 --age 25-39
    python main.py AAPL --json
    python main.py --score                    # score logged predictions whose horizon passed
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from ai.evaluation import DEFAULT_LOG, Report, log_prediction, score_log
from ai.main import predict
from ai.personas import AGE_BANDS, Strategy
from ai.schemas import Prediction

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def parse_args() -> argparse.Namespace:
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
    parser.add_argument("--json", action="store_true", help="print the full prediction as JSON")
    parser.add_argument("--score", action="store_true", help="score the prediction log")
    parser.add_argument("--no-log", action="store_true", help="don't append to the prediction log")
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    if not args.tickers and not args.score:
        parser.error("give at least one ticker, or --score")
    return args


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def render(p: Prediction) -> str:
    lines = [
        f"{p.ticker}  last {p.last_price:.2f}  (data as of {p.data_as_of}, model {p.model})",
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

    lines += ["", "Baselines: " + "  ".join(f"{k}={v}" for k, v in p.baselines.items())]
    if p.linear_regression:
        lr = p.linear_regression
        lines.append(
            f"  linear regression predicts {lr['predicted_return_pct']:+.2f}%; walk-forward since "
            f"{lr['test_start']}: {lr['oos_accuracy']:.0%} right vs always-up "
            f"{lr['always_up_accuracy']:.0%} (R^2 {lr['oos_r2']:+.3f}, n={lr['n_test']})"
        )
        for label, m in (("trading it", lr["strategy"]), ("buy & hold", lr["buy_and_hold"])):
            lines.append(
                f"  {label:<10} ({lr['cost_bps']:g} bps costs): return {m['total_return_pct']:+.1f}%  "
                f"Sharpe {_ratio(m['sharpe'])}  Sortino {_ratio(m['sortino'])}  "
                f"max DD {m['max_drawdown_pct']:.1f}%  profit factor {_ratio(m['profit_factor'])}"
            )

    lines += ["", "Personas:"]
    for r in p.personas:
        if r.view is None:
            lines.append(f"  {r.persona_id:<22} FAILED  {r.error}")
        else:
            rationale = r.view.rationale if len(r.view.rationale) <= 90 else r.view.rationale[:87] + "..."
            lines.append(
                f"  {r.persona_id:<22} {r.view.direction:<5} {r.view.conviction:.2f}  {rationale}"
            )
    if p.data_warnings:
        lines += ["", "Data warnings:"] + [f"  {w}" for w in p.data_warnings]
    return "\n".join(lines)


def render_report(r: Report) -> str:
    if not r.scored:
        return f"No predictions have resolved yet ({r.pending} pending, {r.unreadable} unreadable)."
    lines = [
        f"Scored {r.scored} predictions ({r.pending} pending, {r.unreadable} unreadable). "
        "Small samples are noisy; treat fewer than ~50 as anecdotes.",
        "",
        "Accuracy, 3-way up / flat / down:",
        f"  {'personas':<18} {_pct(r.accuracy['personas'])}   (made a call {_pct(r.coverage)} "
        f"of the time, {_pct(r.accuracy_when_called)} right when it did)",
    ]
    lines += [f"  {name:<18} {_pct(acc)}" for name, acc in r.accuracy.items() if name != "personas"]
    lines += ["", "Persona up/down calls by strength (is higher strength more often right?):"]
    lines += [f"  {bucket}  n={n:<4} {_pct(acc)}" for bucket, (n, acc) in r.by_confidence.items()]
    lines += ["", "Individual persona votes, by strategy:"]
    lines += [f"  {s:<15} {_pct(acc)}" for s, acc in r.by_strategy.items()]
    lines += ["By age band:"]
    lines += [f"  {a:<15} {_pct(acc)}" for a, acc in r.by_age_band.items()]
    return "\n".join(lines)


async def _predict_all(args: argparse.Namespace) -> int:
    failures = 0
    for ticker in args.tickers:
        try:
            prediction = await predict(
                ticker,
                horizon_days=args.horizon,
                strategies=[Strategy(s) for s in args.strategy] if args.strategy else None,
                age_bands=args.age,
            )
        except (RuntimeError, ValueError) as exc:  # missing key, bad ticker, all personas failed
            print(f"{ticker.upper()}: error: {exc}", file=sys.stderr)
            failures += 1
            continue
        if not args.no_log:
            log_prediction(prediction, args.log_file)
        print(prediction.model_dump_json(indent=2) if args.json else render(prediction))
        print()
    return failures


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    load_dotenv(ENV_FILE)
    if args.score:
        print(render_report(score_log(args.log_file)))
    if args.tickers and asyncio.run(_predict_all(args)):
        sys.exit(1)


if __name__ == "__main__":
    main()
