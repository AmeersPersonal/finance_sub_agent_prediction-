from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import ml.__main__ as cli
from ai.confidence_score import aggregate
from ai.evaluation import Outcome
from ai.schemas import PersonaResult, PersonaView, Prediction
from finance.indicators import classify_move, flat_band_series
from ml.calibration import (
    StrengthCalibrator,
    accuracy_at_coverage,
    bias_report,
    call_rows,
    coverage_report,
    evaluate_calibration,
    insider_buying_cluster,
    persona_rank_spread,
)
from ml.dataset import CLASSES, DOWN, FLAT, UP, pooled_price_rows, price_rows, stacker_rows
from ml.model import BoostedTreesModel, LogisticModel, MLPModel, PriorModel
from ml.store import latest, load, save
from ml.walkforward import (
    GATE_MARGIN,
    brier,
    evaluate_price_models,
    evaluate_stacker,
    log_loss,
    reliability,
    schedule,
    walk_forward,
)

NY = "America/New_York"


def _daily(seed: int, days: int = 700, drift: float = 0.0004) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range(end="2026-10-09", periods=days, tz=NY)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.015, days)))
    return pd.DataFrame(
        {"Open": close * 0.998, "High": close * 1.01, "Low": close * 0.99, "Close": close,
         "Volume": rng.integers(1_000_000, 5_000_000, days).astype(float)},
        index=index,
    )


def _pool(n: int = 5) -> dict[str, pd.DataFrame]:
    return {f"T{i}": _daily(seed=i) for i in range(n)}


# --- dataset ----------------------------------------------------------------------


def test_price_rows_are_labelled_like_the_scorer():
    daily = _daily(0)
    data = price_rows(daily, 5, ticker="T0")
    close, band = daily["Close"], flat_band_series(daily["Close"], 5)
    days = [ts.date() for ts in daily.index]
    for i in np.random.default_rng(0).choice(len(data), 40, replace=False):
        j = days.index(data.dates[i].astype(object))
        ret = close.iloc[j + 5] / close.iloc[j] - 1
        assert CLASSES[data.y[i]] == classify_move(ret, band.iloc[j])
        assert data.known_on[i].astype(object) == days[j + 5]
        assert data.past_return[i] == pytest.approx(close.iloc[j] / close.iloc[j - 5] - 1)


def test_price_rows_use_no_future_data():
    daily = _daily(0)
    changed = daily.copy()
    changed.iloc[-10:, changed.columns.get_loc("Close")] *= 2  # rewrite the last 10 days
    first_changed = np.datetime64(daily.index[-10].date())
    before, after = price_rows(daily, 5), price_rows(changed, 5)
    earlier = before.dates < first_changed
    np.testing.assert_array_equal(before.X[earlier], after.X[earlier])
    known = before.known_on < first_changed
    np.testing.assert_array_equal(before.y[known], after.y[known])


def test_relative_target_measures_the_return_against_the_benchmark():
    benchmark = _daily(1)
    stock = benchmark.copy()
    stock["Close"] = benchmark["Close"] * np.exp(0.002 * np.arange(len(stock)))  # steady outperformance
    relative = price_rows(stock, 5, benchmark=benchmark)
    assert relative.target == "relative" and set(relative.y) == {UP}
    assert len(set(price_rows(stock, 5).y)) == 3  # in absolute terms it still moves both ways


def test_pooled_rows_are_in_date_order():
    data = pooled_price_rows(_pool(3), 5)
    assert np.all(np.diff(data.dates.astype(int)) >= 0)
    assert set(data.tickers) == {"T0", "T1", "T2"}


# --- walk-forward -----------------------------------------------------------------


def test_training_never_sees_labels_not_yet_known():
    data = pooled_price_rows(_pool(3), 5)
    days = np.unique(data.dates)
    blocks = schedule(data.dates, data.known_on, test_fraction=0.2, refit_every=21)
    assert blocks
    for block in blocks:
        assert data.known_on[block.train].max() <= block.start
        assert data.dates[block.test].min() >= block.start
        # the purge gap: the newest training row is at least a horizon before the block
        gap = np.searchsorted(days, block.start) - np.searchsorted(days, data.dates[block.train].max())
        assert gap >= 5


def test_walk_forward_predicts_every_test_row_once():
    data = pooled_price_rows(_pool(3), 5)
    run = walk_forward(data, PriorModel, test_fraction=0.2, refit_every=21)
    assert len(np.unique(run.rows)) == len(run.rows) and np.all(np.diff(run.rows) > 0)
    np.testing.assert_allclose(run.proba.sum(axis=1), 1)


def test_metrics_by_hand():
    proba = np.array([[0.2, 0.3, 0.5], [0.6, 0.2, 0.2]])
    y = np.array([UP, DOWN])
    assert log_loss(proba, y) == pytest.approx(-(np.log(0.5) + np.log(0.6)) / 2)
    assert brier(proba, y) == pytest.approx((0.04 + 0.09 + 0.25 + 0.16 + 0.04 + 0.04) / 2)
    bins = {b.label: b for b in reliability(proba, y)}
    assert bins["0.50-0.60"].n == 1 and bins["0.50-0.60"].hit_rate == 1.0
    assert bins["0.60-1.00"].n == 1 and bins["0.60-1.00"].hit_rate == 1.0


def test_price_report_scores_models_and_baselines_on_the_same_rows():
    data = pooled_price_rows(_pool(5), 5)
    report = evaluate_price_models(
        data, ["logistic", "mlp"], makers={"mlp": lambda: MLPModel(device="cpu", epochs=20)}
    )
    assert set(report.baselines) == {"always_up", "momentum", "linear_regression"}
    assert report.n_test > 500 and len(report.tickers) == 5
    for score in report.models:
        assert 0 <= score.accuracy <= 1 and 0 <= score.beats_always_up_share <= 1
        assert score.trading["periods"] > 0 and score.rank_spread["periods"] > 0
        assert not score.passes_gate  # a random walk has nothing to find
    assert report.prior_log_loss > 0


# --- models -----------------------------------------------------------------------


def _planted(n: int = 2000, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 4))
    score = X[:, 0] + 0.5 * X[:, 1]
    y = np.where(score > 0.5, UP, np.where(score < -0.5, DOWN, FLAT))
    X[rng.random(X.shape) < 0.02] = np.nan  # missing values must not break anything
    return X, y


MAKERS = {
    "logistic": LogisticModel,
    "lightgbm": BoostedTreesModel,
    "mlp": lambda: MLPModel(device="cpu", epochs=60),
}


@pytest.mark.parametrize("name", list(MAKERS))
def test_models_learn_a_planted_signal(name):
    X, y = _planted()
    model = MAKERS[name]().fit(X[:1500], y[:1500])
    proba = model.predict_proba(X[1500:])
    assert proba.shape == (500, 3)
    np.testing.assert_allclose(proba.sum(axis=1), 1, atol=1e-6)
    assert np.mean(proba.argmax(axis=1) == y[1500:]) > 0.8


@pytest.mark.parametrize("name", list(MAKERS))
def test_models_return_three_columns_whatever_classes_they_saw(name):
    X, y = _planted()
    two = MAKERS[name]().fit(X[y != FLAT], y[y != FLAT]).predict_proba(X[:10])
    assert two.shape == (10, 3) and np.all(two[:, FLAT] == 0)
    one = MAKERS[name]().fit(X[:50], np.full(50, UP)).predict_proba(X[:10])
    assert one.shape == (10, 3) and np.all(one.argmax(axis=1) == UP)


def test_logistic_coefficients_name_the_informative_column():
    X, y = _planted()
    coefs = LogisticModel().fit(X, y).coefficients(["a", "b", "c", "d"])
    assert coefs["a"]["up"] > abs(coefs["c"]["up"]) and coefs["a"]["down"] < 0


def test_store_round_trip(tmp_path):
    X, y = _planted(300)
    model = MLPModel(device="cpu", epochs=5).fit(X, y)
    path = save(model, "price-mlp-5d-absolute", {"horizon_days": 5}, tmp_path)
    loaded, meta = load(path)
    np.testing.assert_allclose(loaded.predict_proba(X[:20]), model.predict_proba(X[:20]), atol=1e-6)
    assert meta["model"] == "mlp" and meta["horizon_days"] == 5 and meta["file"] == path.name
    assert "git_revision" in meta and "trained_at" in meta
    assert latest("price-mlp-5d-absolute", tmp_path) == path
    assert latest("missing", tmp_path) is None


# --- model B and the persona-call levers ------------------------------------------

PERSONAS = (("long_term", "25-39"), ("long_term", "40-54"), ("day_trader", "25-39"),
            ("index_options", "25-39"))


def _view(direction: str, conviction: float) -> PersonaView:
    return PersonaView(direction=direction, conviction=conviction, rationale="", key_factors=[])


def _outcome(day: date, actual: str, views: dict, earnings: bool = False, **fields) -> Outcome:
    personas = [
        PersonaResult(persona_id=pid, strategy=pid.split(":")[0], age_band=pid.split(":")[1],
                      mode=mode, view=view)
        for pid, mode_views in views.items()
        for mode, view in mode_views
    ]
    combined = aggregate(personas)
    prediction = Prediction(
        ticker=fields.get("ticker", "TEST"), horizon_days=5, direction=combined.direction,
        confidence=combined.confidence, net_score=combined.net_score, agreement=combined.agreement,
        by_strategy=combined.by_strategy, by_mode=combined.by_mode, stability=combined.stability,
        flat_band_pct=1.0, last_price=100.0, data_as_of=day.isoformat(), next_earnings_date=None,
        earnings_within_horizon=earnings, baselines={"always_up": "up", "momentum": "down"},
        linear_regression=None, generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        model="fake", prompt_version="test", personas=personas, data_warnings=[],
    )
    resolved = (pd.Timestamp(day) + pd.offsets.BDay(5)).date()
    return Outcome(prediction=prediction, resolved_on=resolved, return_pct=0.0, actual=actual)


def _synthetic_outcomes(n: int = 400, seed: int = 0) -> list[Outcome]:
    """long_term:25-39 always calls the outcome with high conviction; the rest guess."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2025-01-01", periods=n // 2)
    outcomes = []
    for k in range(n):
        actual = CLASSES[rng.integers(3)]
        views = {
            f"{s}:{a}": [("default", _view(actual, 0.9))] if (s, a) == ("long_term", "25-39")
            else [("default", _view(CLASSES[rng.integers(3)], float(rng.uniform(0.3, 0.9))))]
            for s, a in PERSONAS
        }
        outcomes.append(_outcome(days[k // 2].date(), actual, views, ticker=f"T{k % 2}"))
    return outcomes


def test_stacker_rows_collapse_each_persona_across_modes():
    two_modes = _outcome(date(2026, 1, 5), "up", {
        "long_term:25-39": [("cool", _view("up", 0.8)), ("hot", _view("down", 0.4))],
    })
    other = _outcome(date(2026, 1, 6), "down", {"day_trader:25-39": [("default", _view("flat", 0.6))]})
    data = stacker_rows([other, two_modes])
    row = dict(zip(data.feature_names, data.X[0]))  # sorted by date: two_modes first
    assert row["persona.long_term:25-39.net"] == pytest.approx((0.8 - 0.4) / 2)
    assert row["persona.day_trader:25-39.net"] == 0.0  # didn't run: no vote
    assert "mode.cool" in row and "call.net_score" in row
    assert dict(zip(data.feature_names, data.X[1]))["persona.day_trader:25-39.flat"] == 0.6
    assert [CLASSES[c] for c in data.y] == ["up", "down"]
    assert stacker_rows([two_modes], columns=["persona.x.net", "call.stability"]).X.shape == (1, 2)


def test_stacker_is_blocked_below_the_minimum():
    data = stacker_rows(_synthetic_outcomes(20))
    report = evaluate_stacker(data, ["logistic"])
    assert report.blocked and "20 scored" in report.blocked and not report.models


def test_stacker_learns_which_persona_to_trust():
    data = stacker_rows(_synthetic_outcomes(400))
    report = evaluate_stacker(data, ["logistic"], min_scored=300)
    assert report.blocked is None and report.n_test > 50
    stacker = report.models[0]
    assert stacker.accuracy > report.weights_auto.accuracy and stacker.passes_gate
    assert stacker.accuracy > 0.8
    assert set(report.baselines) == {"personas", "always_up", "momentum", "linear_regression"}
    assert report.baselines["linear_regression"] is None  # never logged in these rows


def test_accuracy_at_coverage_ranks_by_strength():
    outcomes = [
        _outcome(date(2026, 1, 5), "up", {"long_term:25-39": [("default", _view("up", 0.9))]}),
        _outcome(date(2026, 1, 6), "down", {"long_term:25-39": [("default", _view("down", 0.8))]}),
        _outcome(date(2026, 1, 7), "up", {"long_term:25-39": [("default", _view("down", 0.2))]}),
        _outcome(date(2026, 1, 8), "flat", {"long_term:25-39": [("default", _view("up", 0.1))]}),
    ]
    rows = call_rows(outcomes)
    table = {r.label: r for r in accuracy_at_coverage(rows)}
    assert table["top 100%"].n == 4 and table["top 100%"].accuracy == 0.5
    assert table["top 50%"].n == 2 and table["top 50%"].accuracy == 1.0
    assert table["top 50%"].min_strength == pytest.approx(0.8)
    assert table["top 50%"].always_up == 0.5  # same rows: one up, one down


def test_coverage_report_splits_earnings_and_agreement():
    agree = {"long_term:25-39": [("default", _view("up", 0.9))],
             "day_trader:25-39": [("default", _view("up", 0.7))]}
    split = {"long_term:25-39": [("default", _view("up", 0.9))],
             "day_trader:25-39": [("default", _view("down", 0.2))]}
    outcomes = [_outcome(date(2026, 1, 5), "up", agree, earnings=True),
                _outcome(date(2026, 1, 6), "down", split)]
    tables = coverage_report(outcomes)
    assert tables["all strategies agree"][0].n == 1
    assert tables["earnings inside the horizon"][0].n == 1
    assert tables["no earnings inside the horizon"][0].n == 1


@pytest.mark.parametrize("method", ["isotonic", "platt"])
def test_strength_calibration_is_monotone(method):
    rng = np.random.default_rng(0)
    strength = rng.uniform(0, 1, 500)
    correct = rng.random(500) < 0.3 + 0.4 * strength
    fitted = StrengthCalibrator(method).fit(strength, correct).predict(np.linspace(0, 1, 11))
    assert np.all(np.diff(fitted) >= -1e-12) and fitted[-1] > fitted[0]


def test_calibration_walk_forward_scores_every_method():
    score = evaluate_calibration(_synthetic_outcomes(300))
    assert set(score.brier) == {"isotonic", "platt", "constant"} and score.n_test > 0
    assert evaluate_calibration([]) is None


# --- CLI --------------------------------------------------------------------------


def test_cli_price_prints_reports_and_the_gate(monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_dailies", lambda tickers: (
        {t: _daily(seed=i) for i, t in enumerate(tickers)}, {}))
    saved = []
    monkeypatch.setattr(cli, "save", lambda model, name, meta: saved.append((name, meta)) or Path(name))
    cli.main(["price", "aaa", "bbb", "ccc", "ddd", "eee", "--models", "logistic", "--save"])
    out = capsys.readouterr().out
    assert "Model A, 1-day horizon" in out and "Model A, 5-day horizon" in out
    assert "logistic   FAIL" in out
    assert [name for name, _ in saved] == ["price-logistic-1d-absolute", "price-logistic-5d-absolute"]
    assert saved[1][1]["tickers"] == ["AAA", "BBB", "CCC", "DDD", "EEE"]


def test_cli_price_relative_drops_the_benchmark_and_needs_both_horizons(monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_dailies", lambda tickers: (
        {t: _daily(seed=i) for i, t in enumerate(tickers)}, {}))
    cli.main(["price", "SPY", "AAA", "BBB", "--target", "relative", "--horizon", "5",
              "--models", "logistic"])
    out = capsys.readouterr().out
    assert "relative target: 2 tickers" in out and "not judged" in out


def test_cli_stacker_and_coverage_wait_for_scored_predictions(tmp_path, capsys):
    log = tmp_path / "empty.jsonl"
    cli.main(["stacker", "--log-file", str(log)])
    assert "blocked, 0 scored predictions" in capsys.readouterr().out
    cli.main(["coverage", "--log-file", str(log)])
    assert "No predictions have resolved yet" in capsys.readouterr().out


def test_cli_stacker_and_coverage_render_scored_outcomes(monkeypatch, capsys):
    from ai.evaluation import Report

    outcomes = _synthetic_outcomes(400)
    report = Report(scored=400, pending=0, unreadable=0, accuracy={}, coverage=None,
                    accuracy_when_called=None, by_confidence={}, by_strategy={}, by_age_band={},
                    outcomes=outcomes)
    monkeypatch.setattr(cli, "score_log", lambda path: report)
    saved = []
    monkeypatch.setattr(cli, "save", lambda model, name, meta: saved.append(name) or Path(name))
    cli.main(["stacker", "--save"])
    out = capsys.readouterr().out
    assert "Model B (persona stacker): 400 scored predictions" in out
    assert "weights_auto" in out and "logistic" in out and "PASS" in out
    assert "persona.long_term:25-39.net" in out  # the persona it learned to trust leads the table
    assert saved == ["stacker-logistic"]
    cli.main(["coverage"])
    out = capsys.readouterr().out
    assert "all strategies agree" in out and "earnings inside the horizon" in out
    assert "isotonic" in out and "platt" in out


def test_cli_rejects_unknown_models():
    with pytest.raises(SystemExit):
        cli.parse_args(["price", "--models", "lstm"])


def test_cli_reads_saved_forecasts_with_database(monkeypatch, capsys):
    from ai.evaluation import Report
    from database import service

    report = Report(scored=0, pending=2, unreadable=0, accuracy={}, coverage=None,
                    accuracy_when_called=None, by_confidence={}, by_strategy={}, by_age_band={})
    monkeypatch.setattr(cli, "score_log", lambda path: pytest.fail("--database must not read the log"))
    monkeypatch.setattr(service, "score_database", lambda: report)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)  # keep the real .env out of tests
    cli.main(["coverage", "--database"])
    assert "No predictions have resolved yet (2 pending)" in capsys.readouterr().out
    cli.main(["stacker", "--database"])
    assert "blocked, 0 scored predictions" in capsys.readouterr().out


# --- relative target for model B, insider clusters, persona ranking ------------------


def _with(outcome: Outcome, prediction_fields=None, **outcome_fields) -> Outcome:
    prediction = outcome.prediction.model_copy(update=prediction_fields or {})
    return replace(outcome, prediction=prediction, **outcome_fields)


def test_stacker_rows_can_target_the_outcome_relative_to_spy():
    views = {"long_term:25-39": [("default", _view("up", 0.9))]}
    scored = _with(_outcome(date(2026, 1, 5), "up", views), return_pct=3.0,
                   relative_return_pct=-1.5, relative_actual="down")
    no_spy = _outcome(date(2026, 1, 6), "up", views)
    absolute = stacker_rows([scored, no_spy])
    assert [CLASSES[c] for c in absolute.y] == ["up", "up"] and absolute.target == "absolute"
    relative = stacker_rows([scored, no_spy], target="relative")
    assert len(relative) == 1 and CLASSES[relative.y[0]] == "down"
    assert relative.forward_return[0] == pytest.approx(-0.015) and relative.target == "relative"
    with pytest.raises(ValueError):
        stacker_rows([scored], target="sideways")


def test_relative_stacker_scores_baselines_on_the_relative_label():
    outcomes = [_with(o, relative_actual="down" if o.actual == "up" else o.actual, relative_return_pct=0.0)
                for o in _synthetic_outcomes(400)]
    data = stacker_rows(outcomes, target="relative")
    report = evaluate_stacker(data, ["logistic"], min_scored=300)
    # Every "up" outcome is "down" relative to SPY here, so always-up never wins.
    assert report.baselines["always_up"] == 0.0


def _insiders(buys, net):
    return {"long_term.insiders_last_6m.buy_transactions": buys,
            "long_term.insiders_last_6m.net_shares": net}


def test_insider_buying_cluster_needs_several_buys_and_net_buying():
    base = _outcome(date(2026, 1, 5), "up", {"long_term:25-39": [("default", _view("up", 0.9))]}).prediction
    assert insider_buying_cluster(base.model_copy(update={"features": _insiders(4, 1e5)})) is True
    assert insider_buying_cluster(base.model_copy(update={"features": _insiders(2, 1e5)})) is False
    assert insider_buying_cluster(base.model_copy(update={"features": _insiders(5, -1e5)})) is False
    assert insider_buying_cluster(base.model_copy(update={"features": _insiders(None, None)})) is None
    assert insider_buying_cluster(base) is None  # logged before features existed


def test_coverage_report_splits_insider_clusters_and_skips_unknown():
    views = {"long_term:25-39": [("default", _view("up", 0.9))]}
    outcomes = [
        _with(_outcome(date(2026, 1, 5), "up", views), {"features": _insiders(4, 1e5)}),
        _with(_outcome(date(2026, 1, 6), "down", views), {"features": _insiders(1, -5e4)}),
        _outcome(date(2026, 1, 7), "up", views),  # no insider data: in neither table
    ]
    tables = coverage_report(outcomes)
    assert tables["insider buying cluster"][0].n == 1 and tables["insider buying cluster"][0].accuracy == 1.0
    assert tables["no insider buying cluster"][0].n == 1


def test_persona_rank_spread_goes_long_the_highest_net_scores():
    day = date(2026, 1, 5)
    outcomes = []
    # Net scores +0.9, +0.5, 0, -0.5, -0.9: the most bullish call made the most money.
    calls = [("up", 0.9, 4.0), ("up", 0.5, 2.0), ("flat", 0.5, 0.0), ("down", 0.5, -1.0), ("down", 0.9, -3.0)]
    for k, (direction, conviction, ret) in enumerate(calls):
        o = _outcome(day, "up", {"long_term:25-39": [("default", _view(direction, conviction))]},
                     ticker=f"T{k}")
        outcomes.append(_with(o, return_pct=ret))
    spread = persona_rank_spread(outcomes)
    assert spread["periods"] == 1 and spread["mean_tickers"] == 5
    assert spread["mean_spread_pct"] == pytest.approx(4.0 - (-3.0)) and spread["positive_share"] == 1.0
    assert persona_rank_spread(outcomes[:4]) is None  # fewer than 5 tickers that day


def test_cli_coverage_prints_the_new_levers(monkeypatch, capsys):
    from ai.evaluation import Report

    outcomes = _synthetic_outcomes(60)
    report = Report(scored=60, pending=0, unreadable=0, accuracy={}, coverage=None,
                    accuracy_when_called=None, by_confidence={}, by_strategy={}, by_age_band={},
                    outcomes=outcomes)
    monkeypatch.setattr(cli, "score_log", lambda path: report)
    cli.main(["coverage"])
    out = capsys.readouterr().out
    assert "insider buying cluster" in out and "no calls" in out  # these rows logged no insider data
    assert "Persona ranking (lever 6): no day had 5 or more tickers" in out
    cli.main(["stacker", "--target", "relative"])
    assert "relative to SPY: blocked, 0 scored predictions" in capsys.readouterr().out


# --- bias ----------------------------------------------------------------------------


def test_bias_report_crosses_calls_with_outcomes_and_flags_missing_data():
    missing = PersonaView(direction="flat", conviction=0.2, rationale="Valuation data is missing.",
                          key_factors=[])
    outcomes = [
        _outcome(date(2026, 1, 5), "up", {"long_term:25-39": [("default", missing)]}),
        _outcome(date(2026, 1, 6), "up", {"long_term:25-39": [("default", _view("up", 0.9))]}),
        _outcome(date(2026, 1, 7), "down", {"day_trader:25-39": [("default", _view("up", 0.9))]}),
    ]
    (report,) = bias_report(outcomes)
    assert report.horizon_days == 5 and report.n == 3
    assert report.confusion["up"] == {"down": 1, "flat": 0, "up": 1}
    assert report.confusion["flat"]["up"] == 1
    assert report.actual_share["up"] == pytest.approx(2 / 3)
    assert report.call_share["flat"] == pytest.approx(1 / 3)
    long_term = report.by_strategy["long_term"]
    assert long_term.votes == 2 and long_term.share["flat"] == 0.5
    assert long_term.hit_rate == {"down": None, "flat": 0.0, "up": 1.0}
    assert report.missing_data_share == pytest.approx(1 / 3)
    assert report.missing_data_hit_rate == 0.0 and report.other_hit_rate == 0.5


def test_cli_bias_prints_one_table_per_horizon(monkeypatch, capsys, tmp_path):
    from ai.evaluation import Report

    cli.main(["bias", "--log-file", str(tmp_path / "empty.jsonl")])
    assert "No predictions have resolved yet" in capsys.readouterr().out
    outcomes = _synthetic_outcomes(40)
    one_day = [_with(o, {"horizon_days": 1}) for o in outcomes[:10]]
    report = Report(scored=40, pending=0, unreadable=0, accuracy={}, coverage=None,
                    accuracy_when_called=None, by_confidence={}, by_strategy={}, by_age_band={},
                    outcomes=one_day + outcomes[10:])
    monkeypatch.setattr(cli, "score_log", lambda path: report)
    cli.main(["bias"])
    out = capsys.readouterr().out
    assert out.index("1-day horizon: 10 scored") < out.index("5-day horizon: 30 scored")
    assert "called / actual" in out and "long_term" in out and "cites missing data" in out


# --- the call policy and model A's logged signal --------------------------------------


def _policy_outcomes(n: int = 240) -> list[Outcome]:
    """Strong calls are right and weak ones wrong; outcomes rotate, so always-up is ~33%."""
    days = pd.bdate_range("2025-01-01", periods=n)
    outcomes = []
    for k in range(n):
        actual = CLASSES[k % 3]
        wrong = CLASSES[(k + 1) % 3]
        view = _view(actual, 0.9) if k % 2 else _view(wrong, 0.3)
        outcomes.append(_outcome(days[k].date(), actual, {"long_term:25-39": [("default", view)]}))
    return outcomes


def test_call_policy_abstains_when_strong_calls_beat_always_up():
    from ml.calibration import fit_call_policy

    policy = fit_call_policy(_policy_outcomes())
    rule = policy["abstain"]["5"]
    assert rule["enabled"] and 0.3 < rule["min_strength"] <= 0.9
    assert rule["held_out_accuracy"] == 1.0 and rule["held_out_always_up"] < 0.5
    assert policy["calibration"]["enabled"] and len(policy["calibration"]["curve"]) == 21
    few = fit_call_policy(_policy_outcomes(60))
    assert not few["abstain"]["5"]["enabled"] and "need 100" in few["abstain"]["5"]["reason"]


def test_call_policy_stays_off_when_strength_carries_nothing():
    from ml.calibration import fit_call_policy

    days = pd.bdate_range("2025-01-01", periods=240)
    outcomes = [  # always "down", strength unrelated to the outcome
        _outcome(days[k].date(), CLASSES[k % 3],
                 {"long_term:25-39": [("default", _view("down", 0.2 + 0.1 * (k % 7)))]})
        for k in range(240)
    ]
    policy = fit_call_policy(outcomes)
    rule = policy["abstain"]["5"]
    assert not rule["enabled"] and "don't beat always-up" in rule["reason"]
    assert rule["held_out_accuracy"] - rule["held_out_always_up"] <= GATE_MARGIN
    assert not policy["calibration"]["enabled"] and "curve" not in policy["calibration"]


def test_withheld_calls_count_as_made_when_refitting():
    o = _outcome(date(2026, 1, 5), "up", {"long_term:25-39": [("default", _view("up", 0.9))]})
    withheld = _with(o, {"direction": "unclear", "withheld_call": "up"})
    rows = call_rows([withheld])
    assert rows.correct[0] and rows.strength[0] == pytest.approx(0.9)
    (report,) = bias_report([withheld])
    assert report.confusion["up"]["up"] == 1


def test_stacker_sees_the_regression_and_model_a_only_after_its_training():
    o = _outcome(date(2026, 1, 5), "up", {"long_term:25-39": [("default", _view("up", 0.9))]})
    signal = {"p_up": 0.5, "p_flat": 0.2, "p_down": 0.3}
    late = _with(o, {"linear_regression": {"predicted_return_pct": 0.8},
                     "price_model": {**signal, "trained_through": "2026-01-02"}})
    seen = _with(o, {"price_model": {**signal, "trained_through": "2026-01-05"}})
    def row(outcome):
        data = stacker_rows([outcome])
        return dict(zip(data.feature_names, data.X[0]))

    assert row(late)["regression.predicted_return_pct"] == 0.8
    assert row(late)["price_model.edge"] == pytest.approx(0.2)
    assert np.isnan(row(seen)["price_model.edge"])  # model A trained on this outcome
    assert np.isnan(row(seen)["regression.predicted_return_pct"])


def test_price_signal_reads_the_saved_model_for_its_horizon(tmp_path):
    from ml.price_signal import price_signal

    daily = _daily(seed=1)
    data = price_rows(daily, 5)
    model = LogisticModel().fit(data.X, data.y)
    save(model, "price-logistic-5d-absolute", {"features": list(data.feature_names),
         "data_through": "2026-01-01", "walk_forward": {"passes_gate": False}}, tmp_path)
    assert price_signal(1, directory=tmp_path) is None
    result = price_signal(5, directory=tmp_path)(daily)
    assert result["p_up"] + result["p_flat"] + result["p_down"] == pytest.approx(1, abs=1e-3)
    assert result["trained_through"] == "2026-01-01" and result["passes_gate"] is False
    assert price_signal(5, directory=tmp_path)(daily.iloc[:5]) is None  # too short: no features


def test_cli_coverage_save_writes_the_policy(monkeypatch, capsys):
    from ai.evaluation import Report

    outcomes = _policy_outcomes()
    report = Report(scored=len(outcomes), pending=0, unreadable=0, accuracy={}, coverage=None,
                    accuracy_when_called=None, by_confidence={}, by_strategy={}, by_age_band={},
                    outcomes=outcomes)
    monkeypatch.setattr(cli, "score_log", lambda path: report)
    written = []
    monkeypatch.setattr(cli, "save_policy", lambda data: written.append(data) or Path("call_policy.json"))
    cli.main(["coverage", "--save"])
    out = capsys.readouterr().out
    assert "Call policy, fitted on 240 scored calls" in out and "5-day: abstain below" in out
    assert written[0]["abstain"]["5"]["enabled"] and written[0]["source"].endswith("predictions.jsonl")
