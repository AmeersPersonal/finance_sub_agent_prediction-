from datetime import date

import pytest

from finance.macro import labor_inflation_summary, yield_summary
from finance.positioning import (
    analyst_estimates,
    insider_activity,
    institutional_activity,
    rating_changes,
    short_interest,
)


def test_insider_activity(snapshot):
    a = insider_activity(snapshot.insider_purchases)
    assert (a["buy_transactions"], a["sell_transactions"]) == (12, 17)
    assert a["net_shares"] == 300_000
    assert a["net_pct_of_insider_holdings"] == pytest.approx(0.15)
    assert insider_activity(None) is None


def test_institutional_activity(snapshot):
    a = institutional_activity(snapshot.institutional_holders, snapshot.info)
    assert a["institutions_pct_held"] == pytest.approx(60.0)
    assert a["top_holders_avg_stake_change_pct"] == pytest.approx(0.5)
    assert (a["top_holders_increasing"], a["top_holders_decreasing"]) == (2, 1)
    assert a["as_of"] == "2026-06-30"


def test_short_interest(snapshot):
    s = short_interest(snapshot.info)
    assert s["short_pct_of_float"] == pytest.approx(2.0)
    assert s["days_to_cover"] == 2.5
    assert s["change_vs_prior_month_pct"] == pytest.approx(10.0)
    assert short_interest({}) is None


def test_analyst_estimates(snapshot):
    a = analyst_estimates(snapshot.eps_trend, snapshot.eps_revisions, snapshot.price_targets, 100.0)
    assert a["eps_this_year_change_30d_pct"] == pytest.approx((6.0 / 5.88 - 1) * 100)
    assert a["eps_next_year_change_90d_pct"] == pytest.approx(10.0)
    assert (a["eps_revisions_up_30d"], a["eps_revisions_down_30d"]) == (6, 1)
    assert a["price_target_upside_pct"] == pytest.approx(
        (snapshot.price_targets["mean"] / 100.0 - 1) * 100
    )


def test_rating_changes_only_counts_the_window(snapshot):
    r = rating_changes(snapshot.rating_changes, date(2026, 10, 9))
    assert r == {"days": 30, "upgrades": 1, "downgrades": 1, "target_raises": 2, "target_cuts": 1}


def test_yield_summary(snapshot):
    y = yield_summary(snapshot.yields)
    assert y["yield_10y_pct"] == pytest.approx(5.0)
    assert y["spread_10y_3m_pct_points"] == pytest.approx(1.0)
    assert y["curve_inverted"] is False
    assert y["yield_10y_change_1m_pct_points"] > 0
    assert yield_summary({}) is None


def test_labor_inflation_summary(snapshot):
    m = labor_inflation_summary(snapshot.labor)
    cpi = snapshot.labor["cpi"]
    assert m["cpi_yoy_pct"] == pytest.approx((cpi.iloc[-1] / cpi.iloc[-13] - 1) * 100)
    assert m["cpi_as_of"] == "2026-09"
    assert m["unemployment_rate_pct"] == pytest.approx(4.3)
    assert m["payrolls_avg_monthly_change_3m_thousands"] == pytest.approx(100.0)
    assert labor_inflation_summary({}) is None
